"""Probe Engine — sends the CN tool-call suite to a local ``/v1`` endpoint
and validates each response against three readiness layers (mvp_plan §2, §4):

* ``endpoint_stability`` — the endpoint answered with a parseable chat completion.
* ``chat_template``      — the model emitted structured ``tool_calls`` (not prose).
* ``tool_call_json``    — every tool call's ``function.arguments`` is valid JSON
  and its ``function.name`` matches the suite's expectation.

Validation is a *pure* function (``validate_response``) so it is unit-testable
without any HTTP. The engine only owns transport + the ``/v1/models`` detection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from readygate.profiles import ModelProfile, detect_family
from readygate.repair import extract_tool_call_from_content, normalize_arguments
from readygate.suites import ToolProbe, build_suite

# Layers the validator reasons about — the certificate uses the same names.
LAYER_ENDPOINT = "endpoint_stability"
LAYER_TEMPLATE = "chat_template"
LAYER_JSON = "tool_call_json"


@dataclass
class ProbeResult:
    """Outcome of running one ``ToolProbe`` against the endpoint."""

    name: str
    passed: bool
    http_ok: bool
    chat_template_ok: bool
    tool_call_json_ok: bool
    tool_calls: list[dict] = field(default_factory=list)
    extracted_from_content: bool = False
    evidence: dict[str, str] = field(default_factory=dict)  # layer -> human detail
    raw_response: dict | None = None

    @property
    def layers(self) -> dict[str, bool]:
        return {
            LAYER_ENDPOINT: self.http_ok,
            LAYER_TEMPLATE: self.chat_template_ok,
            LAYER_JSON: self.tool_call_json_ok,
        }


def _parse_arguments(args_raw: Any, repair: bool) -> tuple[object | None, str]:
    """Return ``(parsed, evidence)`` for one tool_call's arguments.

    Strict mode (first pass) only accepts already-valid JSON — a malformed
    payload is a *finding* that triggers the repair loop, not something to
    paper over here. Repair mode (re-verify) delegates to
    :func:`normalize_arguments` so the json_normalize fixer gets to run.
    """
    if repair:
        return normalize_arguments(args_raw)
    if not isinstance(args_raw, str):
        return None, "arguments is not a string"
    try:
        return json.loads(args_raw), "valid"
    except (json.JSONDecodeError, TypeError):
        return None, "malformed JSON (repairable on re-verify)"


def _classify(
    response: dict | None,
    expected_functions: tuple[str, ...],
    repair: bool = False,
) -> ProbeResult:
    """Pure per-layer classifier shared by detect and re-verify.

    ``repair=False`` (first pass) is strict: malformed JSON fails the
    tool_call_json layer so the verify→repair→re-verify loop has something
    to do. ``repair=True`` (re-verify) applies the json_normalize fixer.
    """
    result = ProbeResult(
        name="",
        passed=False,
        http_ok=False,
        chat_template_ok=False,
        tool_call_json_ok=False,
    )

    if not isinstance(response, dict):
        result.evidence[LAYER_ENDPOINT] = "no parseable response body"
        return result

    result.raw_response = response
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        result.evidence[LAYER_ENDPOINT] = "response had no choices"
        return result

    # endpoint answered with a structurally valid chat completion
    result.http_ok = True
    result.evidence[LAYER_ENDPOINT] = "ok: choices[0] present"

    message = choices[0].get("message") or {}
    tool_calls = message.get("tool_calls") or []
    content = message.get("content") or ""

    # --- chat_template layer: did the model speak the tool_calls field? ---
    if isinstance(tool_calls, list) and tool_calls:
        result.chat_template_ok = True
        result.evidence[LAYER_TEMPLATE] = f"ok: {len(tool_calls)} tool_call(s) in structured field"
    else:
        # maybe the call is buried in content prose
        recovered = extract_tool_call_from_content(content) if isinstance(content, str) else None
        if recovered:
            result.extracted_from_content = True
            result.tool_calls = [recovered]
            result.evidence[LAYER_TEMPLATE] = (
                "broken: tool_calls empty but a call was found in content"
            )
        else:
            result.evidence[LAYER_TEMPLATE] = "broken: no tool_calls and nothing recoverable in content"
        # tool_call_json cannot pass if the structured field was empty
        result.evidence.setdefault(LAYER_JSON, "skipped: chat_template layer failed first")
        result.passed = False
        return result

    # --- tool_call_json layer: are the arguments valid JSON + names valid? ---
    result.tool_calls = list(tool_calls)
    json_errors: list[str] = []
    valid_calls = 0
    for idx, tc in enumerate(tool_calls):
        if not isinstance(tc, dict):
            json_errors.append(f"call[{idx}] is not an object")
            continue
        fn = tc.get("function") or {}
        name = fn.get("name")
        if name not in expected_functions:
            json_errors.append(f"call[{idx}] name {name!r} not in expected {list(expected_functions)}")
            continue
        args_raw = fn.get("arguments", "")
        parsed, evidence = _parse_arguments(args_raw, repair)
        if parsed is None:
            json_errors.append(f"call[{idx}] arguments unparseable ({evidence})")
            continue
        valid_calls += 1

    if not json_errors and valid_calls == len(tool_calls):
        result.tool_call_json_ok = True
        result.evidence[LAYER_JSON] = f"ok: {valid_calls} call(s) with valid JSON arguments"
    else:
        result.evidence[LAYER_JSON] = "broken: " + "; ".join(json_errors)

    result.passed = result.http_ok and result.chat_template_ok and result.tool_call_json_ok
    return result


def validate_response(response: dict | None, expected_functions: tuple[str, ...]) -> ProbeResult:
    """Strict first-pass detection — no repair applied, so breakage triggers the loop."""
    return _classify(response, expected_functions, repair=False)


def validate_response_repaired(response: dict | None, expected_functions: tuple[str, ...]) -> ProbeResult:
    """Post-repair re-verify: classifies after the json_normalize fixer has run."""
    return _classify(response, expected_functions, repair=True)


class ProbeEngine:
    """Owns HTTP transport and model detection; delegates validation to the pure function."""

    def __init__(
        self,
        endpoint: str,
        model: str | None,
        profile: ModelProfile | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        # normalise: store a base URL without a trailing slash so we can join paths
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.profile = profile or (detect_family(model) if model else None)
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "ProbeEngine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- model detection -------------------------------------------------

    def detect_model(self) -> tuple[str, ModelProfile]:
        """Return ``(model_id, profile)`` from ``/v1/models`` (or the --model override)."""
        if self.model:
            return self.model, self.profile or detect_family(self.model)
        models_url = f"{self.endpoint}/models"
        try:
            resp = self._client.get(models_url)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            # no detection possible — fall back to generic so the suite still runs
            return "", detect_family("")
        first_id = ""
        data_obj = data.get("data") if isinstance(data, dict) else data
        if isinstance(data_obj, list) and data_obj:
            first = data_obj[0]
            if isinstance(first, dict):
                first_id = str(first.get("id") or "")
        return first_id, detect_family(first_id)

    # --- suite dispatch --------------------------------------------------

    def suite(self) -> list[ToolProbe]:
        return build_suite(self.profile or detect_family(self.model or ""))

    def run_probe(self, probe: ToolProbe, repair: bool = False) -> ProbeResult:
        """Send one probe to the endpoint and return its validated result.

        ``repair=False`` (default) is the strict first-pass detection;
        ``repair=True`` is the post-repair re-verify, which applies the
        json_normalize fixer while classifying.
        """
        payload = {
            "model": self.model or "",
            "messages": probe.messages,
            "tools": probe.tools,
            "tool_choice": "auto",
            "temperature": 0.0,
        }
        validator = validate_response_repaired if repair else validate_response
        try:
            resp = self._client.post(f"{self.endpoint}/chat/completions", json=payload)
            resp.raise_for_status()
            response = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            result = validator(None, probe.expected_functions)
            result.name = probe.name
            result.evidence[LAYER_ENDPOINT] = f"request failed: {exc.__class__.__name__}"
            return result
        result = validator(response, probe.expected_functions)
        result.name = probe.name
        return result

    def run_suite(self) -> list[ProbeResult]:
        return [self.run_probe(p) for p in self.suite()]
