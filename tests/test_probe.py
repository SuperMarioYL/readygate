"""Tests for the pure probe validator (no HTTP needed)."""

from __future__ import annotations

import readygate.probe as probe_mod
from readygate.probe import LAYER_ENDPOINT, LAYER_JSON, LAYER_TEMPLATE, validate_response
from readygate.suites import build_suite
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


# --- suite + detection smoke (no HTTP) -----------------------------------


def test_suite_has_three_probes_with_expected_functions():
    suite = build_suite(GENERIC_PROFILE)
    assert len(suite) == 3
    names = {p.name for p in suite}
    assert names == {"single_call", "parallel_calls", "nested_args"}
    assert suite[0].expected_functions == ("get_weather",)
    assert suite[2].expected_functions == ("schedule_meeting",)


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
