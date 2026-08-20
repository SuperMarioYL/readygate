"""Rule-based, request-level repairers for the two breakage patterns
ReadyGate targets (mvp_plan §2, §4):

1. **tool_call_json** — the model emitted a tool_calls entry but its
   ``function.arguments`` is not valid JSON (single quotes, trailing
   commas, unquoted keys, wrapped in markdown fences, or the whole call
   buried in the ``content`` text). :func:`normalize_arguments` fixes the
   response-side JSON in place.

2. **chat_template** — the model printed the tool call as prose instead of
   in the structured ``tool_calls`` field. :func:`augment_probe_for_reprobe`
   tightens the request (system prompt) and asks the engine to re-probe
   once. This is request-level: ReadyGate never rewrites the server's
   chat-template file (mvp_plan §6 — out of scope).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from readygate.suites import ToolProbe


@dataclass(frozen=True)
class RepairAction:
    """A single repair applied during the verify→repair→re-verify loop."""

    name: str        # "json_normalize" | "template_token_fix"
    applied: bool    # whether it actually changed anything
    detail: str      # human-readable evidence of what was fixed


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _strip_fences(raw: str) -> str:
    return _FENCE_RE.sub("", raw).strip()


def _coerce_single_quotes(raw: str) -> str:
    # Cheap, conservative: only swap single quotes that wrap a token
    # value (i.e. preceded by ':' or '{' or ',' or '[' and a space).
    return re.sub(r"([:\[{,]\s*)'([^']*)'", r'\1"\2"', raw)


def _drop_trailing_commas(raw: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", raw)


def normalize_arguments(raw: str) -> tuple[object | None, str]:
    """Best-effort parse of a malformed ``function.arguments`` string.

    Returns ``(parsed_or_None, evidence)``. ``evidence`` describes the fix
    applied (or ``"valid"`` if the input already parsed). The caller decides
    whether ``None`` is a hard failure.
    """
    if raw is None:
        return None, "missing arguments payload"

    candidate = raw.strip()
    if not candidate:
        return None, "empty arguments payload"

    # 1. direct parse — happy path
    try:
        return json.loads(candidate), "valid"
    except json.JSONDecodeError:
        pass

    applied: list[str] = []

    # 2. strip markdown fences (```json ... ```)
    stripped = _strip_fences(candidate)
    if stripped != candidate:
        applied.append("removed markdown fences")
        candidate = stripped

    try:
        return json.loads(candidate), ", ".join(applied) if applied else "valid"
    except json.JSONDecodeError:
        pass

    # 3. single-quote → double-quote for values
    coerced = _coerce_single_quotes(candidate)
    if coerced != candidate:
        applied.append("single->double quotes")
        candidate = coerced

    try:
        return json.loads(candidate), ", ".join(applied) if applied else "valid"
    except json.JSONDecodeError:
        pass

    # 4. drop trailing commas (a notorious CN-model breakage)
    cleaned = _drop_trailing_commas(candidate)
    if cleaned != candidate:
        applied.append("dropped trailing commas")
        candidate = cleaned

    try:
        return json.loads(candidate), ", ".join(applied) if applied else "valid"
    except json.JSONDecodeError:
        pass

    return None, "unrepairable after: " + (", ".join(applied) if applied else "no rule matched")


def _balanced_object(s: str, start: int) -> str | None:
    """Return the brace-balanced object beginning at ``s[start] == '{'``.

    Walks the string tracking string context and brace depth so nested
    objects (e.g. ``arguments`` with nested args) are captured whole — a
    naive regex drops the outer closing brace and leaves invalid JSON.
    """
    if start >= len(s) or s[start] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None  # unbalanced


def extract_tool_call_from_content(content: str) -> dict | None:
    """If the model buried a tool call in ``content`` text, pull it out.

    Returns a normalised ``{"name": str, "arguments": dict}`` dict, or
    ``None`` if nothing tool-call-shaped is found. This is the bridge
    between "model printed prose" and "model filled tool_calls" — used as
    repair evidence, not as a silent fix-up (the certificate records it was
    needed).
    """
    if not content:
        return None
    cursor = 0
    while True:
        start = content.find("{", cursor)
        if start == -1:
            return None
        blob = _balanced_object(content, start)
        cursor = start + 1
        if blob is None:
            continue
        parsed, _evidence = normalize_arguments(blob)
        if not isinstance(parsed, dict):
            continue
        name = parsed.get("name")
        if not isinstance(name, str):
            continue
        args = parsed.get("arguments", parsed)
        if isinstance(args, str):
            args_parsed, _ = normalize_arguments(args)
            args = args_parsed if isinstance(args_parsed, dict) else {}
        return {"name": name, "arguments": args if isinstance(args, dict) else {}}


# --- request-side: tighten the probe so a re-probe is likelier to pass ----


_REPAIR_SYSTEM_SUFFIX = (
    " If any of the provided tools can satisfy the request, you MUST respond "
    "with the assistant message's tool_calls array populated; each entry must "
    "be {\"type\":\"function\",\"function\":{\"name\":<tool>,\"arguments\":<valid JSON>}}. "
    "Do not emit tool calls inside content."
)


def augment_probe_for_reprobe(probe: ToolProbe) -> ToolProbe:
    """Return a copy of ``probe`` with a stricter system prompt for the one re-probe.

    Request-level only: we change *what we send*, never the server config.
    """
    new_messages = [
        {**m, "content": m["content"] + _REPAIR_SYSTEM_SUFFIX}
        if m.get("role") == "system"
        else m
        for m in probe.messages
    ]
    return ToolProbe(
        name=probe.name,
        description=probe.description,
        messages=new_messages,
        tools=probe.tools,
        expected_functions=probe.expected_functions,
    )


def repair_for(probe: ToolProbe, *, broke_template: bool, broke_json: bool) -> tuple[ToolProbe, list[RepairAction]]:
    """Decide the repair for a failed probe and return the (probe, actions) to run.

    * ``broke_template`` — tool_calls missing/buried in content → re-probe
      with a tightened system prompt (template_token_fix).
    * ``broke_json``    — arguments malformed → json_normalize is applied by
      the validator against the *captured* response; here we also re-probe so
      the model gets a second chance to emit clean JSON.

    At least one re-probe is always issued when either flag is set; the
    verify→repair→re-verify loop runs exactly once (mvp_plan §3 step 5).
    """
    actions: list[RepairAction] = []
    out_probe = probe

    if broke_template:
        out_probe = augment_probe_for_reprobe(probe)
        actions.append(
            RepairAction(
                name="template_token_fix",
                applied=True,
                detail="tightened system prompt to require structured tool_calls emission",
            )
        )
    if broke_json:
        actions.append(
            RepairAction(
                name="json_normalize",
                applied=True,
                detail="response-side JSON normaliser armed for malformed arguments",
            )
        )

    return out_probe, actions
