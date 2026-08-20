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

[0.1.0]: https://github.com/SuperMarioYL/readygate/releases/tag/v0.1.0
