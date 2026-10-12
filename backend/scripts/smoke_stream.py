"""SSE 流式接口冒烟测试。

用法（后端已启动）：
    python scripts/smoke_stream.py
"""
from __future__ import annotations

import json
import sys

import requests

BASE = "http://127.0.0.1:8000/api/v1"
PAYLOAD = {
    "message": "最近一周胃胀、反酸，饭后明显，需要做什么检查？",
    "profile": {"age": 42, "gender": "女", "duration": "1周"},
    "stream": True,
    "with_evidence": True,
}


def main() -> int:
    print("=" * 80)
    print("SSE 流式对话测试")
    print("=" * 80)

    chunks: list[str] = []
    meta: dict = {}
    done: dict = {}

    with requests.post(f"{BASE}/chat/stream", json=PAYLOAD, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        event = "message"
        data_lines: list[str] = []
        for raw in resp.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            if raw == "":
                if not data_lines:
                    continue
                text = "\n".join(data_lines)
                data_lines = []
                if event == "delta":
                    chunks.append(text)
                    print(text, end="", flush=True)
                else:
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        payload = text
                    if event == "meta":
                        meta = payload
                    elif event == "done":
                        done = payload
                event = "message"
                continue
            if raw.startswith("event:"):
                event = raw[6:].strip()
            elif raw.startswith("data:"):
                data_lines.append(raw[5:].lstrip())

    print("\n" + "-" * 80)
    print(f"meta: intent={meta.get('intent')} engine={meta.get('engine')} "
          f"evidence={len(meta.get('evidence', []))}")
    print(f"done: latency={done.get('latency_ms')}ms "
          f"triage={bool(done.get('triage'))}")
    print(f"共收到 {len(chunks)} 个文本片段，合计 {sum(len(c) for c in chunks)} 字符")

    if not chunks:
        print("✗ 未收到任何流式片段")
        return 1
    print("✓ 流式返回正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
