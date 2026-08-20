"""``readygate`` CLI — the verify → repair → re-verify → certify loop.

One command, ``readygate probe <endpoint>``, runs the full pre-flight:

1. detect the model family from ``/v1/models`` (or honour ``--model``),
2. send the 3-probe CN tool-call suite,
3. if any layer failed, apply request-level repair and re-probe once,
4. emit the ``AgentReadinessCertificate`` (rich stdout + JSON file).

Exit code 0 when ``agent-ready: yes``, 1 otherwise — so a shell one-liner
or CI step can branch on the verdict.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import typer
from rich.console import Console

from readygate import __version__
from readygate.certificate import build_certificate, emit
from readygate.probe import LAYER_JSON, LAYER_TEMPLATE, ProbeEngine, ProbeResult
from readygate.repair import repair_for
from readygate.suites import SUITE_VERSION

app = typer.Typer(
    name="readygate",
    help="Pre-flight agent-readiness gate for local CN model endpoints.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"readygate {__version__} (suite {SUITE_VERSION})")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show ReadyGate version and exit.",
    ),
) -> None:
    """ReadyGate — is your local CN model endpoint actually agent-ready?"""
    _ = version  # --version handled by callback


@app.command()
def probe(
    endpoint: str = typer.Argument(..., help="OpenAI-compatible base URL, e.g. http://localhost:8000/v1"),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model id override; auto-detected from /v1/models if omitted.",
    ),
    out: Path = typer.Option(
        Path("readygate-cert.json"),
        "--out",
        "-o",
        help="Where to write the JSON certificate.",
    ),
    timeout: float = typer.Option(30.0, "--timeout", "-t", help="Per-request timeout (seconds)."),
) -> None:
    """Probe an endpoint and print agent-ready: YES / NO."""
    base = endpoint.rstrip("/")
    with ProbeEngine(base, model, timeout=timeout) as engine:
        detected_model, profile = engine.detect_model()
        console.print(
            f"[bold]readygate[/bold] → [cyan]{base}[/cyan]  "
            f"[dim]model={detected_model or '(undetected)'} family={profile.display_name}[/dim]"
        )

        suite = engine.suite()
        console.print(f"[dim]running {len(suite)}-probe suite ({SUITE_VERSION})…[/dim]")
        initial_results = [engine.run_probe(p) for p in suite]

        # verify → repair → re-verify (exactly one re-probe pass)
        final_results: list[ProbeResult] = []
        repairs = []
        for probe, initial in zip(suite, initial_results):
            if initial.passed:
                final_results.append(initial)
                continue
            broke_template = not initial.chat_template_ok
            broke_json = not initial.tool_call_json_ok
            if not (broke_template or broke_json):
                # endpoint_stability failed — nothing to repair
                final_results.append(initial)
                continue
            repaired_probe, probe_repairs = repair_for(probe, broke_template=broke_template, broke_json=broke_json)
            repairs.extend(probe_repairs)
            if probe_repairs:
                console.print(
                    f"[yellow]repair[/yellow] {probe.name}: "
                    + ", ".join(a.name for a in probe_repairs)
                )
                # re-verify once, applying the json_normalize fixer (repair=True)
                final_results.append(engine.run_probe(repaired_probe, repair=True))
            else:
                final_results.append(initial)

    cert = build_certificate(
        model=detected_model or (model or ""),
        endpoint=base,
        initial_results=initial_results,
        final_results=final_results,
        repairs=repairs,
    )
    emit(cert, str(out), console=console)

    raise typer.Exit(code=0 if cert.verdict == "yes" else 1)
