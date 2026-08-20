"""Tests for the AgentReadinessCertificate contract + builder."""

from __future__ import annotations

import json
from datetime import datetime

from readygate.certificate import (
    LAYER_ORDER,
    AgentReadinessCertificate,
    LayerResult,
    build_certificate,
)
from readygate.probe import LAYER_ENDPOINT, LAYER_JSON, LAYER_TEMPLATE, ProbeResult
from readygate.repair import RepairAction
from readygate.suites import SUITE_VERSION


def _result(
    name: str,
    http: bool = True,
    tmpl: bool = True,
    json_ok: bool = True,
) -> ProbeResult:
    return ProbeResult(
        name=name,
        passed=http and tmpl and json_ok,
        http_ok=http,
        chat_template_ok=tmpl,
        tool_call_json_ok=json_ok,
        tool_calls=[],
        extracted_from_content=False,
        evidence={
            LAYER_ENDPOINT: "ok" if http else "broken",
            LAYER_TEMPLATE: "ok" if tmpl else "broken",
            LAYER_JSON: "ok" if json_ok else "broken",
        },
        raw_response=None,
    )


# --- happy path ----------------------------------------------------------


def test_certificate_all_pass_verdict_yes():
    results = [_result("single_call"), _result("parallel_calls"), _result("nested_args")]
    cert = build_certificate(
        model="qwen3-8b",
        endpoint="http://localhost:8000/v1",
        initial_results=results,
        final_results=results,
        repairs=[],
    )
    assert cert.verdict == "yes"
    assert [l.status for l in cert.layers] == ["pass", "pass", "pass"]
    assert [l.repaired for l in cert.layers] == [False, False, False]


def test_certificate_layer_order_is_canonical():
    results = [_result("single_call")]
    cert = build_certificate("m", "e", results, results, [])
    assert [l.name for l in cert.layers] == list(LAYER_ORDER)


def test_certificate_suite_version_and_timestamp():
    results = [_result("single_call")]
    cert = build_certificate("m", "e", results, results, [])
    assert cert.suite_version == SUITE_VERSION
    # ISO8601 with tz — parses cleanly
    parsed = datetime.fromisoformat(cert.timestamp)
    assert parsed.tzinfo is not None


# --- the verify→repair→re-verify semantics -------------------------------


def test_certificate_marks_layer_repaired_when_it_recovers():
    initial = [_result("single_call", tmpl=False, json_ok=False)]
    final = [_result("single_call", tmpl=True, json_ok=True)]
    repairs = [RepairAction("template_token_fix", True, "tightened prompt"),
               RepairAction("json_normalize", True, "fixed quotes")]
    cert = build_certificate("m", "e", initial, final, repairs)
    assert cert.verdict == "yes"
    chat_layer = next(l for l in cert.layers if l.name == LAYER_TEMPLATE)
    json_layer = next(l for l in cert.layers if l.name == LAYER_JSON)
    assert chat_layer.status == "repaired"
    assert chat_layer.repaired is True
    assert json_layer.status == "repaired"
    assert "repaired" in chat_layer.evidence


def test_certificate_fails_when_layer_still_broken_after_repair():
    initial = [_result("single_call", json_ok=False)]
    final = [_result("single_call", json_ok=False)]
    repairs = [RepairAction("json_normalize", True, "armed")]
    cert = build_certificate("m", "e", initial, final, repairs)
    assert cert.verdict == "no"
    json_layer = next(l for l in cert.layers if l.name == LAYER_JSON)
    assert json_layer.status == "fail"
    assert json_layer.repaired is False


def test_certificate_endpoint_failure_blocks_everything():
    initial = [_result("single_call", http=False, tmpl=False, json_ok=False)]
    final = initial  # no repair can fix endpoint stability
    cert = build_certificate("m", "e", initial, final, [])
    assert cert.verdict == "no"
    ep = next(l for l in cert.layers if l.name == LAYER_ENDPOINT)
    assert ep.status == "fail"


def test_certificate_partial_repair_some_layers_still_fail():
    # template recovers, json stays broken
    initial = [_result("single_call", tmpl=False, json_ok=False)]
    final = [_result("single_call", tmpl=True, json_ok=False)]
    repairs = [RepairAction("template_token_fix", True, "tightened prompt")]
    cert = build_certificate("m", "e", initial, final, repairs)
    assert cert.verdict == "no"
    tmpl_layer = next(l for l in cert.layers if l.name == LAYER_TEMPLATE)
    json_layer = next(l for l in cert.layers if l.name == LAYER_JSON)
    assert tmpl_layer.status == "repaired"
    assert json_layer.status == "fail"


# --- JSON contract -------------------------------------------------------


def test_certificate_round_trips_through_json():
    results = [_result("single_call")]
    cert = build_certificate("qwen3-8b", "http://localhost:8000/v1", results, results, [])
    blob = cert.model_dump_json()
    parsed = json.loads(blob)
    assert parsed["verdict"] == "yes"
    assert parsed["model"] == "qwen3-8b"
    assert isinstance(parsed["layers"], list)
    assert {l["name"] for l in parsed["layers"]} == set(LAYER_ORDER)
    # round-trip back into the model
    again = AgentReadinessCertificate.model_validate_json(blob)
    assert again.verdict == cert.verdict
    assert again.layers[0].name == cert.layers[0].name


def test_layer_result_model_validates_status_enum():
    lr = LayerResult(name=LAYER_TEMPLATE, status="repaired", evidence="x", repaired=True)
    assert lr.status == "repaired"
    # invalid status should raise via pydantic
    import pytest
    with pytest.raises(Exception):
        LayerResult.model_validate({"name": LAYER_TEMPLATE, "status": "bogus", "evidence": "x"})
