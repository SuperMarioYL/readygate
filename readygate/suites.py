"""CNToolCallSuite — a versioned set of tool-call probe payloads.

These three probes are calibrated to the breakage patterns endemic to CN
models served behind OpenAI-compatible ``/v1`` endpoints:

* ``single_call``   — one tool, one scalar argument (does tool-calling work at all?)
* ``parallel_calls``— two calls in one turn (does the model emit a *list* of tool_calls?)
* ``nested_args``   — a tool whose argument is a nested object (does the JSON stay valid?)

The suite version is part of the emitted certificate so a ``yes`` verdict is
falsifiable and comparable across runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from readygate.profiles import ModelProfile

# Bump when the probe payloads change — certificate consumers key off this.
SUITE_VERSION = "cn-tc-v1"


@dataclass(frozen=True)
class ToolProbe:
    """One tool-call probe in the suite."""

    name: str
    description: str
    messages: list[dict]              # OpenAI chat messages
    tools: list[dict]                  # OpenAI function-tools schema
    expected_functions: tuple[str, ...]  # function names a correct response must call

    @property
    def layer_hint(self) -> str:
        """Which readiness layer this probe most stresses."""
        return {
            "single_call": "endpoint_stability",
            "parallel_calls": "chat_template",
            "nested_args": "tool_call_json",
        }.get(self.name, "tool_call_json")


def _weather_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name, e.g. 'Tokyo'.",
                    }
                },
                "required": ["location"],
            },
        },
    }


def _schedule_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "schedule_meeting",
            "description": "Schedule a meeting with attendees and a time window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of attendees.",
                    },
                    "time": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "description": "ISO8601 start."},
                            "minutes": {"type": "integer", "description": "Duration in minutes."},
                        },
                        "required": ["start", "minutes"],
                    },
                },
                "required": ["attendees", "time"],
            },
        },
    }


def build_suite(profile: ModelProfile) -> list[ToolProbe]:
    """Return the three-probe CN tool-call suite.

    The ``profile`` selects family-specific system-prompt phrasing (some
    families emit tool_calls more reliably when told the format explicitly),
    but the tool schemas and expected functions are identical across families —
    that is what makes the certificate comparable.
    """
    format_hint = _format_hint(profile)

    single = ToolProbe(
        name="single_call",
        description="Single function call with one scalar argument.",
        messages=[
            {
                "role": "system",
                "content": format_hint,
            },
            {
                "role": "user",
                "content": "What is the weather in Tokyo right now? Use the get_weather tool.",
            },
        ],
        tools=[_weather_tool()],
        expected_functions=("get_weather",),
    )

    parallel = ToolProbe(
        name="parallel_calls",
        description="Two tool calls requested in a single turn.",
        messages=[
            {
                "role": "system",
                "content": format_hint,
            },
            {
                "role": "user",
                "content": "Compare the weather in Tokyo and Paris. Call get_weather for both cities in this one turn.",
            },
        ],
        tools=[_weather_tool()],
        expected_functions=("get_weather",),
    )

    nested = ToolProbe(
        name="nested_args",
        description="Tool call whose argument is a nested object.",
        messages=[
            {
                "role": "system",
                "content": format_hint,
            },
            {
                "role": "user",
                "content": "Schedule a 30 minute meeting with Alice and Bob starting at 2026-09-01T09:00:00+09:00. Use the schedule_meeting tool.",
            },
        ],
        tools=[_schedule_tool()],
        expected_functions=("schedule_meeting",),
    )

    return [single, parallel, nested]


def _format_hint(profile: ModelProfile) -> str:
    """Family-tuned system prompt nudging correct tool-call emission.

    This is request-level guidance sent *to the model*, not a server-config
    edit — it is how ReadyGate probes whether the chat-template speaks the
    OpenAI tool_calls field at all (mvp_plan §2, §6).
    """
    if profile.tool_call_style == "hermes":
        return (
            "You are a tool-calling assistant. When the user's request can be "
            "answered by a provided tool, respond ONLY with a structured "
            "tool_calls array using the OpenAI function-call format. Do not "
            "print tool calls as prose."
        )
    if profile.tool_call_style == "deepseek":
        return (
            "You are a tool-calling assistant. Emit tool calls in the "
            "assistant message's tool_calls field with valid JSON arguments. "
            "Never wrap tool calls in markdown fences or prose."
        )
    # glm / kimi / generic — same intent, neutral phrasing.
    return (
        "You are a tool-calling assistant. Use the provided tools by emitting "
        "structured tool_calls with valid JSON arguments."
    )
