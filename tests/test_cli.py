"""Tests for the CLI surface: the exit-code contract and --out validation.

Exit codes: 0 = agent-ready yes, 1 = no, 2 = usage error. The unreachable
endpoint used here is a dead loopback port — connection refused classifies
to a clean NO verdict without needing a server.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

import readygate.cli as cli_mod
from readygate.cli import app
from readygate.probe import LAYER_JSON, LAYER_TEMPLATE, ProbeResult
from readygate.profiles import GENERIC_PROFILE
from readygate.suites import build_suite

runner = CliRunner()

DEAD_ENDPOINT = "http://127.0.0.1:9/v1"


# --- --out usage errors: clean exit 2, no traceback ----------------------


def test_probe_rejects_out_with_missing_parent(tmp_path):
    result = runner.invoke(app, ["probe", DEAD_ENDPOINT, "-o", str(tmp_path / "nope" / "cert.json")])
    assert result.exit_code == 2
    assert "Error" in result.output
    assert "Traceback" not in result.output
    assert "nope" in result.output


def test_probe_rejects_out_that_is_an_existing_directory(tmp_path):
    result = runner.invoke(app, ["probe", DEAD_ENDPOINT, "-o", str(tmp_path)])
    assert result.exit_code == 2
    assert "Error" in result.output
    assert "Traceback" not in result.output
    assert "directory" in result.output


def test_bad_out_fails_fast_before_any_probe_traffic(tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("engine must not be constructed for a bad --out")

    monkeypatch.setattr(cli_mod, "ProbeEngine", _boom)
    result = runner.invoke(app, ["probe", DEAD_ENDPOINT, "-o", str(tmp_path / "nope" / "c.json")])
    # exit 2 (not the AssertionError path) proves the engine was never built
    assert result.exit_code == 2
    assert "must not be constructed" not in result.output


def test_write_time_oserror_surfaces_as_clean_exit_2(tmp_path, monkeypatch):
    def _raising_emit(cert, out_path, console=None):
        raise PermissionError(13, "Permission denied", out_path)

    monkeypatch.setattr(cli_mod, "emit", _raising_emit)
    result = runner.invoke(app, ["probe", DEAD_ENDPOINT, "-o", str(tmp_path / "cert.json")])
    assert result.exit_code == 2
    assert "could not write certificate" in result.output
    assert "Traceback" not in result.output


# --- verdict exit codes ---------------------------------------------------


def test_probe_unreachable_endpoint_exits_1_and_writes_certificate(tmp_path):
    out = tmp_path / "cert.json"
    result = runner.invoke(app, ["probe", DEAD_ENDPOINT, "-o", str(out)])
    assert result.exit_code == 1
    assert "agent-ready: NO" in result.output
    cert = json.loads(out.read_text(encoding="utf-8"))
    assert cert["verdict"] == "no"


class _StubEngine:
    """Replaces ProbeEngine so the CLI loop is driven without HTTP."""

    def __init__(self, *args, **kwargs):
        self.calls: list[tuple[str, bool]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def detect_model(self):
        return "stub-model", GENERIC_PROFILE

    def suite(self):
        return build_suite(GENERIC_PROFILE)

    def run_probe(self, probe, repair=False):
        self.calls.append((probe.name, repair))
        if probe.name == "no_tool":
            return ProbeResult(
                name=probe.name,
                passed=False,
                http_ok=True,
                chat_template_ok=False,
                tool_call_json_ok=False,
                evidence={
                    LAYER_TEMPLATE: "over-eager: 1 tool call(s) emitted when none was expected",
                    LAYER_JSON: "skipped: over-eager calls are not validated",
                },
            )
        return ProbeResult(
            name=probe.name,
            passed=True,
            http_ok=True,
            chat_template_ok=True,
            tool_call_json_ok=True,
            evidence={},
        )


def test_over_eager_no_tool_failure_is_not_repaired(tmp_path, monkeypatch):
    engine_holder = {}

    def _stub_engine(*args, **kwargs):
        engine_holder["engine"] = _StubEngine(*args, **kwargs)
        return engine_holder["engine"]

    monkeypatch.setattr(cli_mod, "ProbeEngine", _stub_engine)
    result = runner.invoke(app, ["probe", DEAD_ENDPOINT, "-o", str(tmp_path / "cert.json")])
    assert result.exit_code == 1
    engine = engine_holder["engine"]
    # every probe ran exactly once — the over-eager no_tool failure
    # triggered no re-probe (the template repair demands tool calls,
    # the opposite of what a no-tool turn needs)
    assert engine.calls.count(("no_tool", False)) == 1
    assert ("no_tool", True) not in engine.calls
    cert = json.loads((tmp_path / "cert.json").read_text(encoding="utf-8"))
    assert cert["verdict"] == "no"
    template_layer = next(l for l in cert["layers"] if l["name"] == "chat_template")
    assert template_layer["status"] == "fail"
    assert "over-eager" in template_layer["evidence"]


def test_passing_endpoint_exits_0(tmp_path, monkeypatch):
    class _PassingEngine(_StubEngine):
        def run_probe(self, probe, repair=False):
            self.calls.append((probe.name, repair))
            return ProbeResult(
                name=probe.name,
                passed=True,
                http_ok=True,
                chat_template_ok=True,
                tool_call_json_ok=True,
                evidence={},
            )

    monkeypatch.setattr(cli_mod, "ProbeEngine", _PassingEngine)
    result = runner.invoke(app, ["probe", DEAD_ENDPOINT, "-o", str(tmp_path / "cert.json")])
    assert result.exit_code == 0
    assert "agent-ready: YES" in result.output
    cert = json.loads((tmp_path / "cert.json").read_text(encoding="utf-8"))
    assert cert["verdict"] == "yes"
