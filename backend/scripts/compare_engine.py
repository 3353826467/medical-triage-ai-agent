"""对照实验：同一问题分别打「规则引擎」与「真实大模型」两个实例，输出差异。

用法（先起两个实例）：
  # 8000 = 大模型（默认配置）
  ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
  # 8001 = 强制规则引擎
  FORCE_RULE_ENGINE=true ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8001

  ../.venv/Scripts/python.exe scripts/compare_engine.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

RULE = "http://127.0.0.1:8001"
LLM = "http://127.0.0.1:8000"

CASES = [
    ("分诊", "最近一周头晕，早上起床时明显，脖子发僵，45岁男性"),
    ("症状咨询", "胃不舒服，吃完饭就胀，还反酸，怎么回事，平时要注意什么"),
    ("报告解读", "血常规：白细胞 12.3 ↑（参考 4-10），血红蛋白 105 ↓（参考 120-160），血小板 220"),
    ("FAQ", "医保报销需要什么材料"),
]


def ask(base: str, message: str) -> tuple[dict, float]:
    payload = json.dumps({"message": message}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/v1/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data, (time.perf_counter() - t0) * 1000


def main() -> None:
    for tag, msg in CASES:
        print("=" * 78)
        print(f"【{tag}】{msg}")
        print("=" * 78)
        for label, base in (("规则引擎（无模型）", RULE), ("DeepSeek（接入模型）", LLM)):
            try:
                data, ms = ask(base, msg)
            except Exception as exc:  # noqa: BLE001
                print(f"\n--- {label} ---\n请求失败：{exc}")
                continue
            print(f"\n--- {label} ---  意图={data.get('intent')}  耗时={ms:.0f}ms  "
                  f"字数={len(data.get('answer', ''))}  参考依据={len(data.get('evidence', []))}")
            print(data.get("answer", "")[:700])
        print()


if __name__ == "__main__":
    sys.exit(main())
