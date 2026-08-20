"""Tests for the rule-based, request-level repairers."""

from __future__ import annotations

import json

from readygate.repair import (
    augment_probe_for_reprobe,
    extract_tool_call_from_content,
    normalize_arguments,
    repair_for,
)
from readygate.suites import build_suite
from readygate.profiles import GENERIC_PROFILE


# --- normalize_arguments -------------------------------------------------


def test_normalize_valid_json_is_identity():
    parsed, evidence = normalize_arguments('{"location":"Tokyo"}')
    assert parsed == {"location": "Tokyo"}
    assert evidence == "valid"


def test_normalize_strips_markdown_fences():
    raw = '```json\n{"location":"Tokyo"}\n```'
    parsed, evidence = normalize_arguments(raw)
    assert parsed == {"location": "Tokyo"}
    assert "markdown" in evidence


def test_normalize_fixes_single_quotes():
    parsed, evidence = normalize_arguments("{'location':'Tokyo'}")
    assert parsed == {"location": "Tokyo"}
    assert "single->double" in evidence


def test_normalize_drops_trailing_commas():
    parsed, evidence = normalize_arguments('{"location":"Tokyo",}')
    assert parsed == {"location": "Tokyo"}
    assert "trailing commas" in evidence


def test_normalize_combined_breakage():
    # fences + single quotes + trailing comma — the full CN-model soup
    raw = "```json\n{'attendees':['Alice','Bob'],}\n```"
    parsed, evidence = normalize_arguments(raw)
    assert parsed == {"attendees": ["Alice", "Bob"]}
    assert "markdown" in evidence
    assert "single->double" in evidence
    assert "trailing commas" in evidence


def test_normalize_returns_none_on_unrepairable():
    parsed, evidence = normalize_arguments("not even close to json ]][[")
    assert parsed is None
    assert "unrepairable" in evidence


def test_normalize_handles_empty_and_none():
    assert normalize_arguments("")[0] is None
    assert normalize_arguments(None)[0] is None


# --- extract_tool_call_from_content --------------------------------------


def test_extract_finds_tool_call_in_prose():
    content = 'Let me check. {"name":"get_weather","arguments":{"location":"Tokyo"}} done.'
    out = extract_tool_call_from_content(content)
    assert out is not None
    assert out["name"] == "get_weather"
    assert out["arguments"] == {"location": "Tokyo"}


def test_extract_returns_none_for_plain_text():
    assert extract_tool_call_from_content("I'll just answer normally.") is None
    assert extract_tool_call_from_content("") is None


def test_extract_recovers_single_quoted_args():
    content = "calling: {'name':'get_weather','arguments':{'location':'Tokyo'}}"
    out = extract_tool_call_from_content(content)
    assert out is not None
    assert out["arguments"] == {"location": "Tokyo"}


# --- augment_probe_for_reprobe (request-side) ----------------------------


def test_augment_appends_token_fix_only_to_system_message():
    suite = build_suite(GENERIC_PROFILE)
    probe = suite[0]
    augmented = augment_probe_for_reprobe(probe)
    sys_msg = next(m for m in augmented.messages if m["role"] == "system")
    user_msg = next(m for m in augmented.messages if m["role"] == "user")
    assert "tool_calls array" in sys_msg["content"]
    assert "tool_calls array" not in user_msg["content"]
    # original probe is untouched (frozen dataclass → new instance)
    original_sys = next(m for m in probe.messages if m["role"] == "system")
    assert "tool_calls array" not in original_sys["content"]


def test_augment_preserves_tools_and_expected_functions():
    suite = build_suite(GENERIC_PROFILE)
    probe = suite[2]  # nested_args
    augmented = augment_probe_for_reprobe(probe)
    assert augmented.tools == probe.tools
    assert augmented.expected_functions == probe.expected_functions
    assert augmented.name == probe.name


# --- repair_for dispatch -------------------------------------------------


def test_repair_for_template_breakage_issues_token_fix():
    suite = build_suite(GENERIC_PROFILE)
    probe = suite[0]
    repaired, actions = repair_for(probe, broke_template=True, broke_json=False)
    names = [a.name for a in actions]
    assert "template_token_fix" in names
    assert "json_normalize" not in names
    # the returned probe is the augmented one
    assert repaired is not probe


def test_repair_for_json_breakage_records_json_normalize():
    suite = build_suite(GENERIC_PROFILE)
    probe = suite[0]
    repaired, actions = repair_for(probe, broke_template=False, broke_json=True)
    names = [a.name for a in actions]
    assert "json_normalize" in names
    assert "template_token_fix" not in names
    # no template break → probe payload unchanged
    assert repaired is probe


def test_repair_for_both_breakages_runs_both_fixers():
    suite = build_suite(GENERIC_PROFILE)
    probe = suite[0]
    repaired, actions = repair_for(probe, broke_template=True, broke_json=True)
    names = {a.name for a in actions}
    assert names == {"template_token_fix", "json_normalize"}
    assert all(a.applied for a in actions)


def test_repair_for_no_breakage_is_a_noop():
    suite = build_suite(GENERIC_PROFILE)
    probe = suite[0]
    repaired, actions = repair_for(probe, broke_template=False, broke_json=False)
    assert actions == []
    assert repaired is probe
