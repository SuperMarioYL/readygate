<div align="right"><sub><a href="./README.en.md">English</a>&nbsp;&nbsp;⇄&nbsp;&nbsp;<b>简体中文</b></sub></div>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/hero-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/hero-light.svg">
  <img src="./assets/hero-light.svg" width="880" alt="ReadyGate — 本地 CN 模型端点的起飞前 agent-readiness 闸门">
</picture>

<p align="center"><sub>起飞前 agent-readiness 闸门 · 一条命令判定本地 Qwen3 / DeepSeek / GLM / Kimi 端点是否真的 agent-ready</sub></p>

<p align="center">
  <a href="./LICENSE"><img alt="license" src="https://img.shields.io/github/license/SuperMarioYL/readygate?color=blue"></a>
  <a href="https://github.com/SuperMarioYL/readygate/releases"><img alt="release" src="https://img.shields.io/github/v/release/SuperMarioYL/readygate?label=release&color=blue"></a>
  <a href="https://github.com/SuperMarioYL/readygate/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/SuperMarioYL/readygate/ci.yml?label=CI"></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white">
</p>

**在把 Claude Code / Codex / Cursor 指向你的本地端点之前，先用一条命令知道它的 tool-calling 到底稳不稳。**

---

## 目录

- [为什么需要 ReadyGate](#为什么需要-readygate)
- [架构](#架构)
- [安装](#安装)
- [快速开始](#快速开始)
- [用法](#用法)
- [演示](#演示)
- [路线图](#路线图)
- [许可](#许可)

<h2><img src="https://api.iconify.design/tabler:bulb.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 为什么需要 ReadyGate</h2>

把一个本地国产模型（Qwen3、DeepSeek V4、GLM-5.2、Kimi K3）跑起来，和它能不能稳定地做 tool-calling，是两回事。CN 模型的 tool-call JSON 经常是坏的、chat-template 可能没配对、OpenAI 兼容端点也可能不稳——其中任何一层断了，coding agent 都会在任务中途静默崩溃。今天开发者要手动发一条 tool-call 探测、看到失败、再逐层排查是 chat-template 坏了还是 JSON 形状错了，然后手修、重测，换一次模型就把这套流程重来一遍。

ReadyGate 把这套 gauntlet 压成一条命令：用一套版本化的 CN 校准 tool-call 探针打本地端点，坏了就在**请求级别**自动修复（绝不改你的服务器配置），重验一次，最后给出一张 `agent-ready: yes/no` 证书。

<h2><img src="https://api.iconify.design/tabler:topology-star-3.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 架构</h2>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/atlas-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/atlas-light.svg">
  <img src="./assets/atlas-light.svg" width="880" alt="架构：CLI → Probe Engine → Validator → Certificate，失败经 Repairer 回流重探">
</picture>

单进程、无 server、无 daemon、无数据库。三个内部模块各司其职：**Probe Engine**（HTTP + suite 分发 + 模型族检测）、**Repairer**（规则式 chat-template / JSON 修复器，纯请求级）、**Certificate Emitter**（rich stdout + `readygate-cert.json`）。核心原语是 [AgentReadinessCertificate](./readygate/certificate.py) 与 [CNToolCallSuite](./readygate/suites.py)——前者是可证伪的 readiness 契约，后者是版本化探针集，二者共同构成防御层。

<h2><img src="https://api.iconify.design/tabler:rocket.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 安装</h2>

```bash
git clone https://github.com/SuperMarioYL/readygate.git && cd readygate
pip install -e .
```

需要 Python 3.12+。也可以不克隆，直接用 `uvx readygate ...` 跑一次。

<h2><img src="https://api.iconify.design/tabler:player-play.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 快速开始</h2>

```bash
# 1. 起一个本地 OpenAI 兼容端点（你自己的 llama.cpp / vLLM / Ollama 等）
# 2. 一条命令探测
readygate probe http://localhost:8000/v1
# 3. 看证书
cat readygate-cert.json
```

<details>
<summary>样例输出</summary>

```
readygate → http://localhost:8000/v1  model=qwen3-8b family=Qwen3
running 3-probe suite (cn-tc-v1)…
repair single_call: template_token_fix, json_normalize
repair nested_args: json_normalize

agent-ready: YES
model=qwen3-8b  endpoint=http://localhost:8000/v1

AgentReadinessCertificate
 Layer              Status    Repaired Evidence
 endpoint_stability pass      —        ok: choices[0] present
 chat_template      repaired  ✓        repaired (json_normalize, template_token_fix) → ok: 1 tool_call(s)…
 tool_call_json     repaired  ✓        repaired (json_normalize, template_token_fix) → ok: 1 call(s)…

certificate written to readygate-cert.json (suite=cn-tc-v1)
```
</details>

退出码：`agent-ready: yes` → `0`，`no` → `1`。可直接接进 shell 或 CI：

```bash
readygate probe http://localhost:8000/v1 && echo "可以放心把 agent 指过去了"
```

<h2><img src="https://api.iconify.design/tabler:terminal-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 用法</h2>

最常见的工作流：

```bash
# 自动从 /v1/models 检测模型族（Qwen / DeepSeek / GLM / Kimi）
readygate probe http://localhost:8000/v1

# 显式指定模型 id，跳过 /v1/models 检测
readygate probe http://localhost:8000/v1 --model qwen3-8b

# 把证书写到自定义路径，并按退出码分支
readygate probe http://localhost:8000/v1 -o ci-cert.json || exit 1

# 调长超时（慢速本地端点）
readygate probe http://localhost:8000/v1 --timeout 60
```

`readygate --version` 查看版本与 suite 版本。证书是 pydantic 校验过的 JSON 契约，可直接被下游脚本消费：

```json
{
  "model": "qwen3-8b",
  "endpoint": "http://localhost:8000/v1",
  "verdict": "yes",
  "layers": [
    {"name": "endpoint_stability", "status": "pass", "evidence": "…", "repaired": false},
    {"name": "chat_template", "status": "repaired", "evidence": "…", "repaired": true},
    {"name": "tool_call_json", "status": "repaired", "evidence": "…", "repaired": true}
  ],
  "suite_version": "cn-tc-v1",
  "timestamp": "2026-08-21T…+00:00"
}
```

<h2><img src="https://api.iconify.design/tabler:photo.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 演示</h2>

![demo](assets/demo.gif)

`agent-ready: NO → 修复 → 重验: YES` 就是那个值得截图的瞬间。demo 脚本见 [`docs/demo.tape`](./docs/demo.tape)，由 `.github/workflows/demo.yml` 用 vhs 渲染成 `assets/demo.gif`。

<h2><img src="https://api.iconify.design/tabler:map-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 路线图</h2>

- [x] **m1** 端点探针：单条 tool-call 探测，打印 raw pass/fail + 响应体
- [x] **m2** 3-probe CN tool-call suite + 模型族检测 + 自动修复（畸形 JSON / chat-template token 缺失），单次重验
- [x] **m3** AgentReadinessCertificate 全量输出（rich stdout + `readygate-cert.json` 逐层明细）+ 双语 README + 演示
- [ ] 未来：西方模型 profiles（Llama / Mistral）
- [ ] 未来：GitHub Action 包装，PR 检查里直接跑 readiness 闸门
- [ ] 未来：持续 / 守护监控（当前为一次性起飞前探测）
- [ ] 未来：MCP 工具连接 readiness 维度

<h2><img src="https://api.iconify.design/tabler:license.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 许可</h2>

MIT，详见 [LICENSE](./LICENSE)。欢迎在 [Issues](https://github.com/SuperMarioYL/readygate/issues) 或 PR 里反馈你本地端点的真实断裂 case——`--dump` 的复现 payload 对丰富 CN 校准 suite 最有价值。

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
