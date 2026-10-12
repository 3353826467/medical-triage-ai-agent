# Milvus 本地验证指南

面向本仓库（`backend/app/rag/vectorstore.py`）。目标是**真正把向量库从本地 JSON 索引切到 Milvus**，并确认检索链路可用。

> 当前线上/默认跑的是 `local-json` 降级路径。本文所有命令都在本机实测过（Python 3.14 + pymilvus 3.0.2）。

---

## 一、三条路径怎么选

| 方案 | 需要 Docker | 适用场景 | 备注 |
|---|---|---|---|
| **Milvus Lite**（推荐先试） | ❌ | 本机验证、开发、演示 | `pip install milvus_lite`，数据落在单个 `.db` 文件 |
| **Docker standalone 2.6.25** | ✅ | 生产 / 准生产 | 2.6 线仍是部署最广的稳定版本 |
| **Docker standalone 3.0.2** | ✅ | 尝鲜新特性 | lake-native / StructList / SINDI；GA 于 2026-07-29 |

**客户端与服务端版本对应**：

| 服务端 | 建议 pymilvus | 说明 |
|---|---|---|
| 3.0.x | 3.0.2（本仓库已装） | 版本严格对齐 |
| 2.6.x | 2.6.9，或用 3.0.2 | 服务端向后兼容，新客户端一般可连；遇异常再降级 |

---

## 二、方案 A：Milvus Lite（免 Docker，推荐）

### 1. 装依赖

```bash
.venv/Scripts/python.exe -m pip install milvus_lite
```

会连带装 `faiss-cpu` + `pyarrow`（约 30MB）。

### 2. 配置

在 `backend/.env` 加两行：

```env
MILVUS_ENABLED=true
MILVUS_TARGET=./data/milvus.db
```

> ⚠️ **字段名必须是 `MILVUS_TARGET`，不能叫 `MILVUS_URI`。**
> pymilvus 在 `import pymilvus` 时会读取环境变量 `MILVUS_URI` 并当作 gRPC 地址解析，
> 填本地路径会直接抛 `Illegal uri: [...] expected form 'http[s]://...'`，且发生在导入阶段、
> 项目代码还没执行，极难排查。这个坑已经踩过了。

### 3. 启动

```bash
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

首次启动会把 `data/knowledge/*.md` 的 68 个切片灌进去，日志出现：

```
INFO | milvus_lite.server_manager | MilvusLite server started for ...\data\milvus.db on port 2222
INFO | medical-agent | 知识库就绪：68 个文档 / 向量后端 milvus
```

### 4. 内存不够时

Milvus Lite 内部用 faiss + OpenBLAS，内存紧张时会报：

```
OpenBLAS error: Memory allocation still failed after 10 retries, giving up.
```

解决：启动时限制 BLAS 线程数，并先停掉其它大内存程序（模拟器、多余浏览器）：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 ../.venv/Scripts/python.exe -m uvicorn app.main:app ...
```

---

## 三、方案 B：Docker standalone（2.6.25）

### 1. 启动

```bash
docker compose -f docker/docker-compose.milvus.yml up -d
```

四个容器：`medical-etcd` / `medical-minio` / `medical-milvus` / `medical-attu`。

```bash
docker compose -f docker/docker-compose.milvus.yml ps     # 看状态
docker logs -f medical-milvus                              # 首次初始化约 30-90s
```

- Milvus gRPC：`localhost:19530`（后端连这个）
- Health：`localhost:9091/healthz`
- MinIO 控制台：`localhost:9001`（minioadmin / minioadmin）
- Attu 管理界面：`localhost:3001`

### 2. 配置

```env
MILVUS_ENABLED=true
MILVUS_TARGET=http://127.0.0.1:19530     # 或者直接留空，用 HOST/PORT 拼
```

留空时按 `MILVUS_HOST` + `MILVUS_PORT` 拼成 `http://host:port`。

### 3. 想试 3.0

```bash
docker compose -f docker/docker-compose.milvus-3.yml up -d
```

部署形态与 2.6 完全一致（官方 3.0 的 standalone compose 仍是 etcd + MinIO + standalone 三容器），只是镜像换成 `milvusdb/milvus:v3.0.2`。数据目录用 `docker/volumes3/`，与 2.6 互不干扰。

### 4. 停止 / 清空

```bash
docker compose -f docker/docker-compose.milvus.yml down       # 停，数据保留
docker compose -f docker/docker-compose.milvus.yml down -v    # 停并删数据卷
```

---

## 四、验证是否真的切过去了

### 1. 看运行时状态

```bash
curl -s http://127.0.0.1:8000/api/v1/runtime
```

关键字段：

```json
{ "vector_backend": "milvus", "dimension": 384, "milvus_enabled": true }
```

- `vector_backend: "local-json"` → **没连上，已降级**。这一步最常见的失败原因见第六节。
- `vector_backend: "milvus"` → 成功。

### 2. 看知识库条数

```bash
curl -s http://127.0.0.1:8000/api/v1/health
# {"knowledge_docs": 68, "vector_backend": "milvus", ...}
```

重启后再查一次，应该还是 68 且日志不再重新入库——说明索引被复用而非每次重建。

### 3. 检索调试

```bash
curl -s "http://127.0.0.1:8000/api/v1/knowledge/search?q=饭后反酸烧心&limit=3"
```

### 4. 跑自检脚本（推荐，一次查全套）

```bash
cd backend

# Lite
../.venv/Scripts/python.exe scripts/check_milvus.py --uri ./data/milvus.db

# Docker
../.venv/Scripts/python.exe scripts/check_milvus.py
```

脚本逐级检查并明确告诉你卡在哪一步：

```
[1] 配置：Milvus Lite（本地文件）
[2] 可达性              → TCP 不通会列出 Docker 未启动 / 端口占用等排查方向
[3] 服务端              → 打印服务端版本 + 已有 collection
[4] Embedding 维度      → 与建表维度必须一致
[5] 建表 / 写入 / 检索   → 建表、插 3 条、语义检索、标量过滤
[6] 项目封装层链路       → 走 MilvusVectorStore 的 add/search/count/reset
```

退出码 0 = 全通过。测试用的 collection 叫 `medical_kb_smoketest`，默认跑完自动删除（`--keep` 可保留）。

---

## 五、重建索引

换 embedding 模型（维度变了）、改了知识库 markdown、或想把本地索引迁到 Milvus 时：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/knowledge/ingest \
  -H "Content-Type: application/json" \
  -d '{"rebuild": true}'
```

返回 `{"backend": "milvus", "inserted": 68, ...}`。

也可以追加自定义文档（不覆盖已有）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/knowledge/ingest \
  -H "Content-Type: application/json" \
  -d '{"docs": [{"title": "妊娠期用药", "content": "……", "category": "用药"}]}'
```

---

## 六、踩过的坑（按遇到概率排序）

### 1. 主键类型不匹配 —— 曾经是必现 bug

`Chunk.id` 是 `uuid4().hex` 字符串，而 `create_collection(dimension=...)` 简单模式建出来的主键是 **int64**，一写入就崩：

```
DataNotMatchException: {id} field should be a int64, but got a {<class 'str'>}
```

**已修**：`MilvusVectorStore._create_collection()` 现在显式建 schema（`id` = VARCHAR(64) 主键），并顺带把索引显式指定为 HNSW/COSINE（默认 AUTOINDEX 在小数据量下会退化成暴力扫描）。

代码还加了 `_schema_compatible()` 兜底：已存在的旧表主键不是 VARCHAR 或维度不匹配时，打 warning 后自动 drop 重建（知识库内容来自 `data/knowledge/*.md`，可安全重建）。

### 2. 环境变量名撞车（见第二节）

`MILVUS_URI` 是 pymilvus 自己的环境变量。项目字段叫 `MILVUS_TARGET`。

### 3. `add_field` 的参数名

pymilvus 3.x 是 `datatype=`，不是 `dtype=`：

```python
schema.add_field("id", datatype=DataType.VARCHAR, max_length=64, is_primary=True)
```

写 `dtype=` 会报 `missing 1 required positional argument: 'datatype'`。

### 4. Embedding 维度必须和 collection 维度一致

`index()` 里 collection 维度由**实际 embedding 的 dim** 决定，不再靠 `llm_ready` 猜 1536/384。
配了 DeepSeek 这类"只有对话接口、没有 /embeddings"的模型时，embedding 会自动降级成本地 384 维——这没问题，但**换 embedding 后必须 `rebuild: true` 重建索引**，否则维度对不上会被 Milvus 拒写。

### 5. 降级是静默的

`build_vectorstore()` 连不上 Milvus 时直接返回 `LocalVectorStore()`，服务照常启动。**所以一定要看 `/api/v1/runtime` 的 `vector_backend` 确认**，别以为起来了就是用的 Milvus。

### 6. 端口冲突

19530 / 9091 / 9000 / 9001 / 3001 任一被占都会失败：

```powershell
netstat -ano | findstr 19530
```

MinIO 的 9000/9001 最容易和本机其它服务撞，改 compose 的左侧端口即可（`"19000:9000"`）。

### 7. 内存

Milvus standalone 建议空闲 4–8GB。16GB 机器在提交内存接近打满时，Lite 也会因 OpenBLAS 分配失败起不来——按第二节第 4 点限线程 + 先关掉大内存程序。

---

## 七、什么时候才真的需要 Milvus

说句实在话：**68 条切片用 Milvus 是杀鸡用牛刀**，它的价值要到百万级才体现，本地 JSON 索引在这个量级反而更快（纯内存余弦，无网络往返）。

当前真正限制检索质量的**不是向量库**，是 **embedding**：DeepSeek 不提供 `/embeddings`，本地哈希向量理解不了"反酸"≈"胃食管反流"。换什么向量库都救不了。

优先级应该是：

1. 接一个真正的 Embedding 模型（OpenAI `text-embedding-3-small`，或国内支持 `/embeddings` 的端点）→ 检索质量立刻上一个台阶
2. 知识库涨到几万条以上
3. 再开 Milvus + 重排（rerank）
