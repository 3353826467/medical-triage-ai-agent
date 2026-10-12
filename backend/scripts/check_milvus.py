"""Milvus 连通性自检脚本。

用法：
    python scripts/check_milvus.py                 # 用 .env 里的配置
    python scripts/check_milvus.py --host 127.0.0.1 --port 19530
    python scripts/check_milvus.py --keep          # 保留测试 collection 不删除

检查项（逐级递进，失败时明确告诉你是哪一步、为什么）：
    1. pymilvus 是否安装 / 版本
    2. TCP 端口是否可达（区分「Docker 没起」与「端口被占」）
    3. 服务端版本
    4. 建 collection（用项目实际 embedding 维度，验证维度一致）
    5. 插入 + 检索 + 过滤检索
    6. 走项目 MilvusVectorStore 真实链路（add / search / count / reset）

退出码：0 = 全部通过；1 = 有失败项。
"""
from __future__ import annotations

import argparse
import asyncio
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OK = "✓"
BAD = "✗"
WARN = "!"


def say(sym: str, msg: str) -> None:
    print(f"  {sym} {msg}")


def embed(emb, texts: list[str]) -> list[list[float]]:
    """项目的 Embeddings 只暴露异步接口（aembed_documents），这里包一层同步调用。"""
    return asyncio.run(emb.aembed_documents(texts))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", default=None)
    ap.add_argument("--collection", default="medical_kb_smoketest")
    ap.add_argument("--uri", default=None,
                    help="Milvus URI：http://host:port 或本地 .db 文件路径（Milvus Lite）")
    ap.add_argument("--keep", action="store_true", help="保留测试 collection（默认测完删除）")
    args = ap.parse_args()

    print("=" * 64)
    print("Milvus 自检")
    print("=" * 64)

    # ---- 1. 客户端 ------------------------------------------------------ #
    try:
        import pymilvus
    except ImportError:
        say(BAD, "pymilvus 未安装 → pip install pymilvus")
        return 1
    say(OK, f"pymilvus 版本 {pymilvus.__version__}")

    from app.config import get_settings

    s = get_settings()
    host = args.host or s.MILVUS_HOST
    port = int(args.port or s.MILVUS_PORT)

    uri = (args.uri or s.MILVUS_TARGET or "").strip()
    if not uri and args.host is None:
        uri = f"http://{host}:{port}"
    lite_mode = bool(uri) and not uri.startswith("http")

    print(f"\n[1] 配置：{'Milvus Lite（本地文件）' if lite_mode else f'{host}:{port}'}")
    print(f"    uri={uri or f'http://{host}:{port}'}")
    print(f"    database={s.MILVUS_DATABASE}  collection={args.collection}  MILVUS_ENABLED={s.MILVUS_ENABLED}")

    # ---- 2. 可达性（Lite 模式走文件检查） --------------------------------- #
    print("\n[2] 可达性")
    if lite_mode:
        p = Path(uri)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            say(OK, f"Milvus Lite 本地文件模式：{p}（目录可写）")
        except OSError as exc:
            say(BAD, f"本地文件不可写：{exc}")
            return 1
    else:
        t0 = time.time()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(3)
            try:
                sock.connect((host, port))
                say(OK, f"TCP {host}:{port} 可达（{time.time() - t0:.3f}s）")
            except OSError as exc:
                say(BAD, f"TCP {host}:{port} 不可达：{exc}")
                print("\n  排查方向：")
                print("    · Docker Desktop 是否启动")
                print("    · docker compose -f docker/docker-compose.milvus.yml ps  看容器状态")
                print("    · docker logs medical-milvus  看是否还在初始化（首次约 30-90s）")
                print("    · 19530 是否被本机其它程序占用：netstat -ano | findstr 19530")
                print("    · 不想装 Docker？用 Milvus Lite：--uri ./data/milvus.db")
                return 1

    # ---- 3. 服务端版本 --------------------------------------------------- #
    print("\n[3] 服务端")
    from pymilvus import MilvusClient

    kwargs: dict = {"uri": uri or f"http://{host}:{port}"}
    if not lite_mode:
        kwargs["db_name"] = s.MILVUS_DATABASE
        if s.MILVUS_USER:
            kwargs["token"] = f"{s.MILVUS_USER}:{s.MILVUS_PASSWORD}"
    try:
        client = MilvusClient(**kwargs)
        try:
            ver = client.get_server_version()
        except Exception:  # noqa: BLE001 - 老版本没有该 API
            ver = "(unknown)"
        say(OK, f"已连接，服务端版本 {ver}")
        say(OK, f"已有 collection：{client.list_collections() or '(空)'}")
    except Exception as exc:  # noqa: BLE001
        say(BAD, f"连接失败：{type(exc).__name__}: {exc}")
        return 1
    if isinstance(ver, str) and ver.startswith("2.4"):
        say(WARN, "服务端仍是 2.4，建议升级到 2.6.25")

    # ---- 4. 维度一致性（关键：维度错了 Milvus 会拒写） -------------------- #
    print("\n[4] Embedding 维度")
    from app.rag.embeddings import build_embeddings

    emb = build_embeddings(s)
    vec = embed(emb, ["测试文本"])[0]
    dim = len(vec)
    say(OK, f"embedding 后端 {emb.name}，维度 {dim}")
    if s.MILVUS_COLLECTION == args.collection:
        say(WARN, "测试 collection 与生产 collection 同名，已跳过写入以免污染")
        return 0

    # ---- 5. 裸客户端写入/检索 -------------------------------------------- #
    print("\n[5] 建表 / 写入 / 检索")
    if client.has_collection(args.collection):
        client.drop_collection(args.collection)
        say(WARN, f"已删除同名残留 collection {args.collection}")

    from app.rag.vectorstore import MilvusVectorStore

    # 复用项目的建表逻辑（VARCHAR 主键 + HNSW），避免自检与生产不一致
    helper = MilvusVectorStore(s, dim=dim)
    helper._create_collection(client, collection_name=args.collection)  # noqa: SLF001
    say(OK, f"已建 collection（dim={dim}, 主键 VARCHAR, 索引 HNSW/COSINE）")

    docs = [
        ("胃食管反流病", "典型表现为餐后反酸、烧心，平卧时加重。", "消化"),
        ("急性冠脉综合征", "胸骨后压榨性疼痛，可放射至左臂，伴冷汗。", "心内"),
        ("良性阵发性位置性眩晕", "起床翻身时短暂眩晕，与体位改变相关。", "耳鼻喉"),
    ]
    vecs = embed(emb, [f"{t}。{c}" for t, c, _ in docs])
    rows = [
        {
            "id": f"t{i}",
            "vector": vecs[i],
            "title": t,
            "content": c,
            "category": cat,
            "source": "smoke",
        }
        for i, (t, c, cat) in enumerate(docs)
    ]
    client.insert(collection_name=args.collection, data=rows)
    say(OK, f"插入 {len(rows)} 条")

    q = embed(emb, ["饭后反酸烧心是怎么回事"])[0]
    res = client.search(
        collection_name=args.collection,
        data=[q],
        limit=3,
        output_fields=["title", "category"],
    )
    if not res or not res[0]:
        say(BAD, "检索返回空")
        return 1
    for r in res[0]:
        say(OK, f"  {r['entity']['title']:<12} score={r['distance']:.4f}  [{r['entity']['category']}]")

    # 标量过滤
    try:
        res2 = client.search(
            collection_name=args.collection,
            data=[q],
            limit=3,
            filter='category == "心内"',
            output_fields=["title", "category"],
        )
        say(OK, f"标量过滤 category==\"心内\" 返回 {len(res2[0])} 条")
    except Exception as exc:  # noqa: BLE001
        say(WARN, f"标量过滤不可用：{type(exc).__name__}: {exc}")

    stats = client.get_collection_stats(args.collection)
    say(OK, f"collection 行数 {stats.get('row_count')}")

    # ---- 6. 项目封装层 --------------------------------------------------- #
    print("\n[6] 项目 MilvusVectorStore 链路")
    from app.rag.vectorstore import Chunk, MilvusVectorStore

    if args.uri:
        s.MILVUS_TARGET = args.uri  # 让封装层走同一 URI
    s.MILVUS_COLLECTION = args.collection  # pydantic settings 可直接改
    store = MilvusVectorStore(s, dim=dim)
    if not store._connect():  # noqa: SLF001
        say(BAD, f"项目封装层连接失败：{store._error}")  # noqa: SLF001
        return 1
    say(OK, f"封装层已连接（name={store.name}, dim={store.dim}）")

    chunks = [
        Chunk(title="偏头痛", content="单侧搏动性头痛，伴畏光恶心。", category="神经", source="smoke",
              vector=embed(emb, ["偏头痛。单侧搏动性头痛，伴畏光恶心。"])[0])
    ]
    n = asyncio.run(store.add(chunks))
    say(OK, f"store.add → {n} 条")

    hits = asyncio.run(store.search(embed(emb, ["一边头疼还恶心"])[0], 2))
    say(OK, f"store.search → {len(hits)} 条，top1={hits[0].chunk.title} ({hits[0].score:.4f})")
    say(OK, f"store.count → {asyncio.run(store.count())}")

    # ---- 清理 ------------------------------------------------------------ #
    if args.keep:
        say(WARN, f"按 --keep 保留 {args.collection}")
    else:
        asyncio.run(store.reset())
        say(OK, f"已清理测试 collection {args.collection}")

    print("\n" + "=" * 64)
    print("全部通过。接下来说后端怎么用 Milvus：见 docs/Milvus本地验证指南.md")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
