[简体中文](./README.md) · [Website](https://readygate.lei6393.com) · [GitHub](https://github.com/SuperMarioYL/readygate)

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/hero-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/hero-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/hero-dark.svg">
  <img src="./assets/presentation/hero-light.svg" width="960" alt="Hero diagram">
</picture>

# readygate

**Check the tool-call path before connecting an agent.**

ReadyGate runs a small tool-call probe suite against a configured endpoint and records endpoint, structured-call and argument-JSON results.

## Why use it

An HTTP response alone does not show that the endpoint emits usable tool calls. Separate layers make it easier to locate a broken response format before a longer agent task begins.

- **Layered results** — Separate response availability, call structure and argument JSON.
- **One retry path** — Supported request repairs are visible in the result.
- **Save a report** — JSON output carries suite and layer evidence.

## Architecture

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/architecture-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/architecture-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/architecture-dark.svg">
  <img src="./assets/presentation/architecture-light.svg" width="960" alt="Architecture diagram">
</picture>

ProbeEngine selects the model profile and sends the suite. Strict validation records initial failures; repair_for modifies supported request hints and a single retry is validated with supported argument normalization. The certificate emitter summarizes the initial and final layer results.

| Component | Responsibility |
| --- | --- |
| `Probe suite` | readygate/suites.py |
| `HTTP engine` | readygate/probe.py |
| `Request repair` | readygate/repair.py |
| `Result certificate` | readygate/certificate.py |

## Install and quickstart

Build with the version declared in the repository manifest. Run the example from the repository root.

```bash
git clone https://github.com/SuperMarioYL/readygate.git
cd readygate
uv venv .venv
uv pip install --python .venv/bin/python -e .
source .venv/bin/activate
```

Pass an explicit single-quoted arguments fixture through strict and repaired validation.

```bash
.venv/bin/python examples/presentation-demo.py
```

## Recorded demo

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/process-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/process-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/process-dark.svg">
  <img src="./assets/presentation/process-light.svg" width="960" alt="Process diagram">
</picture>

The malformed JSON fixture fails strict validation and passes the supported normalization path.

```text
{
  "input_arguments": "{'location':'Tokyo'}",
  "strict_layers": {
    "endpoint_stability": true,
    "chat_template": true,
    "tool_call_json": false
  },
  "repaired_layers": {
    "endpoint_stability": true,
    "chat_template": true,
    "tool_call_json": true
  },
  "strict_pass": false,
  "repaired_pass": true
}
```

The complete command and output are recorded in [docs/demo-results.json](./docs/demo-results.json). Inputs and reproduction code are included in the repository.

![Existing terminal recording](./assets/demo.gif)

The existing recording is retained for context; the text example above documents the reproducible scenario.

## Usage

The CLI exposes the following operations. Commands after the example use your own paths or identifiers.

```bash
readygate probe http://localhost:8000/v1 --model your-model -o readygate-cert.json
readygate probe http://localhost:8000/v1 --timeout 60
```

## Configuration

probe accepts an endpoint, optional --model, --out/-o certificate destination and --timeout/-t. Without --model, the engine queries /models. Online probing makes real requests to the supplied endpoint; the included offline script only calls pure validators.

## Integrations and responsibilities

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/integrations-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/integrations-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/integrations-dark.svg">
  <img src="./assets/presentation/integrations-light.svg" width="960" alt="Integrations diagram">
</picture>

The following routes are implemented in the source. Choose the input that matches your task and keep the resulting artifact with your project.

| Route | Implemented role |
| --- | --- |
| OpenAI-compatible endpoint | Models and chat-completions routes |
| Tool-call suite | Single, parallel and nested probes |
| JSON report | Per-layer pass / repaired / fail |
| Exit status | One-shot gate result |

## Limits and next steps

- A passing suite is bounded to those probes. It does not prove general agent readiness, full argument-schema conformance or long-term endpoint stability.
- Repair applies to this probe workflow and does not persistently fix the server or configure another harness.
- The recorded offline example exercises the validator on a fixture and does not certify a live endpoint.

Broader suites, additional model profiles and MCP connection checks are future work. Treat the report as reproducible probe evidence.

## License and contributions

See [LICENSE](./LICENSE). When reporting an issue, include a minimal input, the command, and the observed output.
