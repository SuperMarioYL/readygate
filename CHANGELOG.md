# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-21

### Added
- `readygate probe <endpoint>` CLI: one-command pre-flight agent-readiness gate for local OpenAI-compatible `/v1` endpoints.
- CN tool-call suite (`cn-tc-v1`): three calibrated probes — single call, parallel calls, nested args.
- Model-family detection for Qwen3 / DeepSeek / GLM / Kimi from `/v1/models` (overridable with `--model`).
- Rule-based, request-level repairers: malformed tool-call JSON normalization (single quotes, trailing commas, markdown fences) and chat-template token fix via a tightened system prompt.
- Verify → repair → re-verify loop with a single re-probe pass.
- `AgentReadinessCertificate` (pydantic) with per-layer status (`endpoint_stability` / `chat_template` / `tool_call_json`), evidence, and `repaired` flags, emitted to rich stdout + `readygate-cert.json`.
- Exit code `0` for `agent-ready: yes`, `1` for `no`.
- Bilingual README (zh primary + `README.en.md`), animated dark/light hero + architecture SVGs (SMIL), Tabler-icon section headers, shields.io badges.
- CI (`ci.yml`), release (`release.yml`, opt-in PyPI trusted publishing), and demo (`demo.yml` vhs re-render) workflows.
- Reproducible demo via `examples/mock_endpoint.py` + `docs/demo.tape` → `assets/demo.gif`.

## [0.2.0] - 2026-09-13

### Fixed
- Auto-detected model id is now actually sent: `detect_model()` persists its resolution into engine state, so probes no longer ship `"model": ""` when `--model` is omitted (strict servers rejected the empty id and returned a false `agent-ready: NO`). The certificate now names the model the requests really carried.
- Malformed-but-JSON endpoint responses no longer crash the classifier with raw `AttributeError` tracebacks: a non-dict `choices[0]`, non-dict `message`, or non-dict `function` classifies into layer evidence; `arguments` emitted as an already-parsed JSON object (lax servers) is a repairable finding instead of a crash on the re-verify pass.
- Bad `--out` paths are rejected up front with a clean error (exit 2) instead of dumping `FileNotFoundError`/`IsADirectoryError` tracebacks after the whole suite ran; write-time `OSError` also surfaces as a clean exit-2 error. Exit-code contract is now explicit: 0 = yes, 1 = no, 2 = usage error.

### Added
- Fourth suite probe `no_tool` (over-eager tool-call detection): tools attached, turn needs no call — emitting one fails the chat_template layer with `over-eager` evidence and is deliberately not repairable. Suite version bumped to `cn-tc-v2` (verdicts get stricter; certificates carry the new suite id).
- `web/site.json` `meta.content_version` field; version-consistency test locking `pyproject.toml`, `readygate.__version__`, and the site metadata to the same version.

### Changed
- `examples/mock_endpoint.py` repair marker is now the repair-suffix-unique "MUST respond" phrase (the hermes family hint legitimately mentions "tool_calls array"), and the mock answers the no-tool turn in content — the demo story stays NO → repaired → YES.

[0.1.0]: https://github.com/SuperMarioYL/readygate/releases/tag/v0.1.0
[0.2.0]: https://github.com/SuperMarioYL/readygate/releases/tag/v0.2.0
