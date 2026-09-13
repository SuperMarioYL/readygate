"""Tests for the pure probe validator (no HTTP needed)."""

from __future__ import annotations

import json

import httpx

import readygate.probe as probe_mod
from readygate.probe import (
    LAYER_ENDPOINT,
    LAYER_JSON,
    LAYER_TEMPLATE,
    ProbeEngine,
    validate_response,
    validate_response_repaired,
)
from readygate.suites import SUITE_VERSION, build_suite
from readygate.profiles import GENERIC_PROFILE


def _ok_tool_call(name: str = "get_weather", args: str = '{"location":"Tokyo"}', call_id: str = "c1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


def _resp(tool_calls: list[dict] | None = None, content: str | None = None) -> dict:
    msg: dict = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls"}]}


# --- happy path: structured tool_calls, valid JSON ------------------------


def test_validate_passes_perfect_response():
    r = validate_response(_resp(tool_calls=[_ok_tool_call()]), ("get_weather",))
    assert r.passed is True
    assert r.http_ok and r.chat_template_ok and r.tool_call_json_ok
    assert not r.extracted_from_content


def test_validate_passes_parallel_calls():
    calls = [_ok_tool_call("get_weather", '{"location":"Tokyo"}', "c1"),
             _ok_tool_call("get_weather", '{"location":"Paris"}', "c2")]
    r = validate_response(_resp(tool_calls=calls), ("get_weather",))
    assert r.passed is True
    assert len(r.tool_calls) == 2


def test_validate_passes_nested_args():
    args = '{"attendees":["Alice","Bob"],"time":{"start":"2026-09-01T09:00:00+09:00","minutes":30}}'
    r = validate_response(_resp(tool_calls=[_ok_tool_call("schedule_meeting", args)]), ("schedule_meeting",))
    assert r.passed is True
    assert r.tool_call_json_ok


# --- endpoint_stability layer --------------------------------------------


def test_validate_fails_on_none_response():
    r = validate_response(None, ("get_weather",))
    assert r.passed is False
    assert r.http_ok is False
    assert LAYER_ENDPOINT in r.evidence


def test_validate_fails_on_no_choices():
    r = validate_response({"choices": []}, ("get_weather",))
    assert r.http_ok is False
    assert r.passed is False


# --- malformed response shapes classify, never crash --------------------


def test_validate_classifies_non_dict_choice_as_endpoint_failure():
    # v0.1.0 raised AttributeError: 'str' object has no attribute 'get'
    r = validate_response({"choices": ["boom"]}, ("get_weather",))
    assert r.http_ok is False
    assert r.passed is False
    assert "choices[0]" in r.evidence[LAYER_ENDPOINT]


def test_validate_classifies_non_dict_message_as_endpoint_failure():
    r = validate_response({"choices": [{"index": 0, "message": "just text"}]}, ("get_weather",))
    assert r.http_ok is False
    assert r.passed is False
    assert "message" in r.evidence[LAYER_ENDPOINT]


def test_validate_records_non_dict_function_as_json_finding():
    tc = {"id": "c1", "type": "function", "function": "get_weather"}
    r = validate_response(_resp(tool_calls=[tc]), ("get_weather",))
    assert r.http_ok and r.chat_template_ok
    assert r.tool_call_json_ok is False
    assert "function is not an object" in r.evidence[LAYER_JSON]


def test_object_arguments_are_a_finding_strict_and_valid_repaired():
    # lax servers emit arguments already parsed — v0.1.0 crashed on the
    # re-verify pass with AttributeError: 'dict' object has no attribute 'strip'
    tc = {
        "id": "c1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": {"location": "Tokyo"}},
    }
    strict = validate_response(_resp(tool_calls=[tc]), ("get_weather",))
    assert strict.chat_template_ok is True
    assert strict.tool_call_json_ok is False  # spec says arguments is a string
    assert "not a string" in strict.evidence[LAYER_JSON]
    repaired = validate_response_repaired(_resp(tool_calls=[tc]), ("get_weather",))
    assert repaired.tool_call_json_ok is True
    assert repaired.passed is True


# --- chat_template layer -------------------------------------------------


def test_validate_fails_when_tool_calls_missing():
    r = validate_response(_resp(content="Sure, I'll check the weather."), ("get_weather",))
    assert r.http_ok is True
    assert r.chat_template_ok is False
    assert r.passed is False
    assert not r.extracted_from_content


def test_validate_recovers_tool_call_buried_in_content():
    content = 'I called the tool: {"name":"get_weather","arguments":{"location":"Tokyo"}}'
    r = validate_response(_resp(content=content), ("get_weather",))
    assert r.chat_template_ok is False          # structured field still empty
    assert r.extracted_from_content is True
    assert r.tool_calls and r.tool_calls[0]["name"] == "get_weather"


# --- tool_call_json layer ------------------------------------------------


def test_validate_fails_on_malformed_arguments():
    # single-quoted JSON is invalid JSON — tool_call_json layer breaks
    r = validate_response(
        _resp(tool_calls=[_ok_tool_call("get_weather", "{'location':'Tokyo'}")]),
        ("get_weather",),
    )
    assert r.http_ok and r.chat_template_ok
    assert r.tool_call_json_ok is False
    assert "unparseable" in r.evidence[LAYER_JSON]
    assert r.passed is False


def test_validate_fails_on_unexpected_function_name():
    r = validate_response(
        _resp(tool_calls=[_ok_tool_call("unknown_fn", '{"x":1}')]),
        ("get_weather",),
    )
    assert r.tool_call_json_ok is False
    assert "unknown_fn" in r.evidence[LAYER_JSON]


# --- no_tool probes: empty expected_functions means no call expected -----


def test_no_tool_probe_passes_on_content_answer():
    r = validate_response(_resp(content="42"), ())
    assert r.passed is True
    assert r.http_ok and r.chat_template_ok and r.tool_call_json_ok
    assert "no tool call" in r.evidence[LAYER_TEMPLATE]


def test_no_tool_probe_fails_over_eager_calls():
    r = validate_response(_resp(tool_calls=[_ok_tool_call()]), ())
    assert r.passed is False
    assert r.chat_template_ok is False
    assert "over-eager" in r.evidence[LAYER_TEMPLATE]
    assert "skipped" in r.evidence[LAYER_JSON]


def test_no_tool_probe_fails_on_empty_response():
    r = validate_response(_resp(content=""), ())
    assert r.passed is False
    assert r.chat_template_ok is False
    assert "empty" in r.evidence[LAYER_TEMPLATE]


# --- suite + detection smoke (no HTTP) -----------------------------------


def test_suite_has_four_probes_with_expected_functions():
    suite = build_suite(GENERIC_PROFILE)
    assert len(suite) == 4
    names = {p.name for p in suite}
    assert names == {"single_call", "parallel_calls", "nested_args", "no_tool"}
    assert suite[0].expected_functions == ("get_weather",)
    assert suite[2].expected_functions == ("schedule_meeting",)
    # the no_tool probe: weather tool attached, but no call expected
    assert suite[3].expected_functions == ()
    assert suite[3].tools


def test_suite_version_bumped_for_no_tool_probe():
    # cn-tc-v2 added the no_tool probe; certificates key off this
    assert SUITE_VERSION == "cn-tc-v2"


def test_probe_result_layers_dict_matches_layer_names():
    r = validate_response(_resp(tool_calls=[_ok_tool_call()]), ("get_weather",))
    assert set(r.layers) == {LAYER_ENDPOINT, LAYER_TEMPLATE, LAYER_JSON}


def test_probe_result_name_is_stamped_by_caller_not_validator():
    # the generic validator returns an empty name; the engine/caller stamps it
    r = validate_response(_resp(tool_calls=[_ok_tool_call()]), ("get_weather",))
    assert r.name == ""
    r.name = "single_call"
    assert r.name == "single_call"


def test_layer_hint_covers_each_probe():
    suite = build_suite(GENERIC_PROFILE)
    assert {p.layer_hint for p in suite} == {
        probe_mod.LAYER_ENDPOINT,
        probe_mod.LAYER_TEMPLATE,
        probe_mod.LAYER_JSON,
    }


# --- engine state: the detected model id must reach the payloads ---------


def _ok_completion_response() -> dict:
    return {
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"location":"Tokyo"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }


def _recording_client(log: list[dict], *, models_status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        log.append({"path": request.url.path, "body": body})
        if request.url.path.endswith("/models"):
            if models_status != 200:
                return httpx.Response(models_status, json={"error": "boom"})
            return httpx.Response(200, json={"object": "list", "data": [{"id": "Qwen3.8-27B-Instruct"}]})
        return httpx.Response(200, json=_ok_completion_response())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_detected_model_id_is_sent_in_probe_payloads():
    # v0.1.0 shipped "model": "" in every payload while the header and
    # certificate claimed the detected id — strict servers rejected it.
    log: list[dict] = []
    engine = ProbeEngine("http://mock/v1", None, client=_recording_client(log))
    with engine:
        detected, profile = engine.detect_model()
        assert detected == "Qwen3.8-27B-Instruct"
        assert profile.family == "qwen3"
        for probe in engine.suite():
            engine.run_probe(probe)
    sent = [e["body"]["model"] for e in log if e["path"].endswith("/chat/completions")]
    assert sent and all(m == "Qwen3.8-27B-Instruct" for m in sent)


def test_explicit_model_override_is_sent():
    log: list[dict] = []
    engine = ProbeEngine("http://mock/v1", "my-model", client=_recording_client(log))
    with engine:
        detected, _profile = engine.detect_model()
        assert detected == "my-model"
        engine.run_probe(engine.suite()[0])
    sent = [e["body"]["model"] for e in log if e["path"].endswith("/chat/completions")]
    assert sent and all(m == "my-model" for m in sent)


def test_unreachable_models_endpoint_falls_back_to_empty_model():
    # fail-soft: detection failure must not break the probe run
    log: list[dict] = []
    engine = ProbeEngine("http://mock/v1", None, client=_recording_client(log, models_status=500))
    with engine:
        detected, profile = engine.detect_model()
        assert detected == ""
        assert profile.family == "generic"
        engine.run_probe(engine.suite()[0])
    sent = [e["body"]["model"] for e in log if e["path"].endswith("/chat/completions")]
    assert sent == [""]
