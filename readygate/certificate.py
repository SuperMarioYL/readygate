"""AgentReadinessCertificate — the structured, machine-readable verdict that
is ReadyGate's defensible primitive (mvp_plan §2).

The certificate owns three things and nothing else:

1. the **verdict** (``yes`` / ``no`` — agent-ready),
2. a per-**layer** breakdown (endpoint_stability / chat_template /
   tool_call_json) with status + evidence + a ``repaired`` flag,
3. the **suite_version** + timestamp that make the verdict falsifiable
   and comparable across runs.

It is a pydantic model so the JSON contract is validated, not hand-rolled.
The emitter renders a rich table to stdout and writes ``readygate-cert.json``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from readygate.probe import LAYER_ENDPOINT, LAYER_JSON, LAYER_TEMPLATE, ProbeResult
from readygate.suites import SUITE_VERSION
from readygate.repair import RepairAction

# Canonical layer order for display + JSON.
LAYER_ORDER = (LAYER_ENDPOINT, LAYER_TEMPLATE, LAYER_JSON)

LayerStatus = Literal["pass", "fail", "repaired"]


class LayerResult(BaseModel):
    name: str
    status: LayerStatus
    evidence: str
    repaired: bool = False


class AgentReadinessCertificate(BaseModel):
    model: str
    endpoint: str
    verdict: Literal["yes", "no"]
    layers: list[LayerResult]
    suite_version: str = SUITE_VERSION
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _layer_passed(results: list[ProbeResult], layer: str) -> bool:
    return all(getattr(r, _layer_attr(layer)) for r in results) if results else False


def _layer_attr(layer: str) -> str:
    return {
        LAYER_ENDPOINT: "http_ok",
        LAYER_TEMPLATE: "chat_template_ok",
        LAYER_JSON: "tool_call_json_ok",
    }[layer]


def _layer_evidence(results: list[ProbeResult], layer: str) -> str:
    bits = [r.evidence.get(layer, "") for r in results if r.evidence.get(layer)]
    return " | ".join(bits) or "no evidence recorded"


def build_certificate(
    model: str,
    endpoint: str,
    initial_results: list[ProbeResult],
    final_results: list[ProbeResult],
    repairs: list[RepairAction],
    suite_version: str = SUITE_VERSION,
) -> AgentReadinessCertificate:
    """Assemble the certificate from the verify→repair→re-verify loop outputs.

    A layer is ``repaired`` when it failed in ``initial_results`` but passes in
    ``final_results``; ``pass`` when it passes in both; ``fail`` otherwise.
    """
    repaired_names = {a.name for a in repairs if a.applied}

    layers: list[LayerResult] = []
    all_ok = True
    for layer in LAYER_ORDER:
        final_ok = _layer_passed(final_results, layer)
        initial_ok = _layer_passed(initial_results, layer)
        if not final_ok:
            status: LayerStatus = "fail"
            repaired = False
            all_ok = False
        elif not initial_ok and final_ok:
            # failed, then a repair brought it back — record which fixers ran
            status = "repaired"
            repaired = True
        else:
            status = "pass"
            repaired = False

        evidence = _layer_evidence(final_results, layer)
        if repaired:
            applied = ", ".join(sorted(repaired_names)) or "repair"
            evidence = f"repaired ({applied}) → {evidence}"
        layers.append(LayerResult(name=layer, status=status, evidence=evidence, repaired=repaired))

    verdict: Literal["yes", "no"] = "yes" if all_ok else "no"
    return AgentReadinessCertificate(
        model=model,
        endpoint=endpoint,
        verdict=verdict,
        layers=layers,
        suite_version=suite_version,
    )


def emit(cert: AgentReadinessCertificate, out_path: str, console: Console | None = None) -> None:
    """Print the rich certificate table to stdout and write the JSON file."""
    console = console or Console()

    color = "green" if cert.verdict == "yes" else "red"
    console.print()
    console.print(f"[bold {color}]agent-ready: {cert.verdict.upper()}[/bold {color}]")
    console.print(f"[dim]model={cert.model or '(undetected)'}  endpoint={cert.endpoint}[/dim]")
    console.print()

    table = Table(title="AgentReadinessCertificate", show_lines=False, border_style="dim")
    table.add_column("Layer", style="bold")
    table.add_column("Status")
    table.add_column("Repaired")
    table.add_column("Evidence", overflow="fold")
    for layer in cert.layers:
        status_style = {"pass": "green", "repaired": "yellow", "fail": "red"}[layer.status]
        table.add_row(
            layer.name,
            f"[{status_style}]{layer.status}[/{status_style}]",
            "✓" if layer.repaired else "—",
            layer.evidence,
        )
    console.print(table)
    console.print()

    payload = cert.model_dump_json(indent=2)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(payload)
    console.print(f"[dim]certificate written to {out_path} (suite={cert.suite_version})[/dim]")
