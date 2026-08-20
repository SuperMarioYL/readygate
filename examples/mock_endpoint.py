"""A tiny stdlib-only OpenAI-compatible mock endpoint for the demo.

Run:  python3 examples/mock_endpoint.py
Then: readygate probe http://localhost:8000/v1

It models the endemic CN-model breakage ReadyGate exists for: the first
tool-call probe returns *malformed* (single-quoted) JSON arguments; the
augmented re-probe (system prompt contains "tool_calls array") returns
clean JSON — so `readygate probe` goes NO → repaired → YES end to end.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOOD = '{"location":"Tokyo"}'
BAD = "{'location':'Tokyo'}"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        self._send(200, {"object": "list", "data": [{"id": "qwen3-8b"}]})

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        name = "get_weather"
        tools = body.get("tools") or []
        if tools and isinstance(tools[0], dict):
            name = (tools[0].get("function") or {}).get("name", name)
        sys_msg = next((m.get("content", "") for m in body.get("messages", [])
                        if m.get("role") == "system"), "")
        args = GOOD if "tool_calls array" in sys_msg else BAD
        if name == "schedule_meeting":
            good = '{"attendees":["Alice","Bob"],"time":{"start":"2026-09-01T09:00:00+09:00","minutes":30}}'
            bad = ("{'attendees':['Alice','Bob'],"
                   "'time':{'start':'2026-09-01T09:00:00+09:00','minutes':30}}")
            args = good if "tool_calls array" in sys_msg else bad
        self._send(200, {
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {"name": name, "arguments": args},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        })

    def log_message(self, fmt, *args):  # silence default logging
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
