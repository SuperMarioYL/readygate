"""Static model-family profiles for the CN model families ReadyGate targets.

A profile captures what ReadyGate needs to know about a family to probe it:
how to recognise it from the served model id, and the chat-template
tool-call style it nominally speaks. This is *static data*, not a plugin
system — v0.1 ships qwen / deepseek / glm / kimi only (see mvp_plan §6).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    """A CN model family's probe-relevant metadata."""

    family: str            # canonical key, e.g. "qwen3"
    display_name: str      # human label, e.g. "Qwen3"
    detect_patterns: tuple[str, ...]  # lowercase substrings matched against the model id
    tool_call_style: str   # chat-template token family, used by repair hints

    def matches(self, model_id: str) -> bool:
        needle = model_id.lower()
        return any(p in needle for p in self.detect_patterns)


# Order matters: more specific patterns first so a generic "qwen" doesn't
# shadow a "qwen3" before its own pattern is tried.
PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(
        family="qwen3",
        display_name="Qwen3",
        detect_patterns=("qwen3", "qwen-3", "qwen3.8"),
        tool_call_style="hermes",
    ),
    ModelProfile(
        family="deepseek",
        display_name="DeepSeek",
        detect_patterns=("deepseek", "deep-seek"),
        tool_call_style="deepseek",
    ),
    ModelProfile(
        family="glm",
        display_name="GLM",
        detect_patterns=("glm", "chatglm"),
        tool_call_style="glm",
    ),
    ModelProfile(
        family="kimi",
        display_name="Kimi",
        detect_patterns=("kimi", "moon"),
        tool_call_style="kimi",
    ),
)

# Generic fallback when the served model matches no known CN family — the
# probe still runs, repair just has no family-specific hints.
GENERIC_PROFILE = ModelProfile(
    family="generic",
    display_name="Unknown",
    detect_patterns=(),
    tool_call_style="generic",
)


def detect_family(model_id: str) -> ModelProfile:
    """Return the profile whose patterns match ``model_id``, else the generic one."""
    if not model_id:
        return GENERIC_PROFILE
    for profile in PROFILES:
        if profile.matches(model_id):
            return profile
    return GENERIC_PROFILE
