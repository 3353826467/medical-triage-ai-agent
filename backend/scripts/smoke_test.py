"""全链路冒烟测试：直接对本机 FastAPI 服务发起真实请求。

用法：
    python -m uvicorn app.main:app --port 8000   # 另开一个终端
    python scripts/smoke_test.py                 # 执行本脚本
"""
from __future__ import annotations

import json
import sys
import time

import requests

BASE = "http://127.0.0.1:8000/api/v1"

CASES: list[tuple[str, dict]] = [
    (
        "① 智能分诊：咳嗽黄痰",
        {
            "message": "最近三天咳嗽，有黄痰，晚上比较严重，该挂什么科？",
            "profile": {"age": 35, "gender": "男", "duration": "3天"},
        },
    ),
    (
        "② 安全护栏：疑似脑卒中",
        {
            "message": "我妈刚才突然一侧手脚没力气，说话也说不清楚了",
            "profile": {"age": 68, "gender": "女", "duration": "10分钟"},
        },
    ),
    (
        "③ 报告解读：血常规异常项",
        {
            "message": "帮我看看这个血常规：白细胞 12.3 ×10^9/L ↑，血红蛋白 105 g/L ↓，血小板 210",
            "intent": "report",
        },
    ),
    (
        "④ 常见问题：医保报销",
        {"message": "医保报销比例是多少？需要准备什么材料？", "intent": "faq"},
    ),
    (
        "⑤ 症状咨询：头晕",
        {"message": "最近经常头晕，是什么原因，需要注意什么？"},
    ),
    (
        "⑥ 寒暄",
        {"message": "你好"},
    ),
]


def pretty(text: str, width: int = 78) -> str:
    return "\n".join(text.splitlines())


def main() -> int:
    failed = 0
    print("=" * 80)
    print("智能问诊 AI 客服系统 —— 冒烟测试")
    print("=" * 80)

    try:
        health = requests.get(f"{BASE}/health", timeout=10).json()
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 无法连接服务：{exc}")
        print("请先启动：python -m uvicorn app.main:app --port 8000")
        return 1

    print(f"服务状态：{health['status']} | LLM 引擎：{health['llm_engine']} "
          f"| 向量库：{health['vector_backend']} | 知识切片：{health['knowledge_docs']}\n")

    session_id = ""
    for title, payload in CASES:
        body = dict(payload)
        body["session_id"] = session_id
        print("-" * 80)
        print(title)
        print("-" * 80)
        try:
            resp = requests.post(f"{BASE}/chat", json=body, timeout=90)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            print(f"✗ 请求失败：{exc}")
            failed += 1
            continue

        session_id = data.get("session_id", session_id)
        print(f"[意图] {data['intent']}  [引擎] {data['engine']}  [耗时] {data['latency_ms']}ms")
        if data.get("triage"):
            t = data["triage"]
            print(f"[分诊] {t['department']} / {t['urgency']}")
        if data.get("evidence"):
            print(f"[引用] {len(data['evidence'])} 条")
            for e in data["evidence"][:3]:
                print(f"   - 《{e['title']}》 {e['score']}")
        print()
        print(pretty(data["answer"]))
        print()

    print("=" * 80)
    if failed:
        print(f"✗ {failed} 个用例失败")
        return 1
    print("✓ 全部用例通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
