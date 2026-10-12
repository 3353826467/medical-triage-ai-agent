"""公网部署入口：单端口同时提供前端页面与后端 API。

监听 $PORT、绑定 0.0.0.0（发布沙箱的要求）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 让 `app` 包可被导入（backend/ 下的源码目录）
sys.path.insert(0, str(HERE / "backend"))

import uvicorn  # noqa: E402


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
