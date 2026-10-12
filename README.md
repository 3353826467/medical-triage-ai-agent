# 智能问诊 AI 客服系统

面向医疗行业的智能问诊与客服系统，提供**症状咨询、智能分诊、报告解读、常见问题解答**四类核心能力。
基于 LangChain 编排、OpenAI 兼容协议、Milvus 向量检索、FastAPI 服务端与 Vue3 前端。

> ⚠️ 本系统输出的是健康参考信息，**不构成医疗诊断**，不能替代执业医师的面诊、检查与诊断。
> 出现危急情况请立即拨打 120。

---

## 一、核心功能

| 能力 | 说明 | 入口 |
|---|---|---|
| 🩺 **症状咨询** | 症状成因科普、居家护理要点、"什么情况必须去医院"的警示信号 | `POST /api/v1/chat` |
| 🚦 **智能分诊** | 输出推荐首诊科室 + 紧急程度分级 + 可能情况 + 可执行建议 | `POST /api/v1/triage` |
| 📄 **报告解读** | 检验 / 影像 / 病理报告翻译成大白话，逐项标注偏高偏低 | `POST /api/v1/report/interpret` |
| 🏥 **就医服务 FAQ** | 挂号、医保、缴费、检查准备、票据、转诊等 | `GET /api/v1/faq` |

**其他特性**

- 多轮会话（带患者画像：年龄 / 性别 / 病程 / 既往史 / 过敏史）
- **医疗安全护栏**：命中红旗症状（胸痛、卒中 FAST、呼吸困难、大出血、过敏性休克、自杀倾向等）时，
  跳过模型自由发挥，直接给出急诊/120 指引
- RAG 检索增强，答案附带"参考依据"（来源 + 相关度）
- SSE 流式输出（打字机效果）
- **全链路降级**：没有 OpenAI Key、没有 Milvus，服务照样能启动并给出合理答复

---

## 二、技术栈

| 层 | 选型 |
|---|---|
| 前端 | Vue 3（`<script setup>`）+ Vite 5 + marked |
| 后端 | FastAPI + Pydantic v2 + Uvicorn |
| LLM 编排 | LangChain（`ChatOpenAI` / `ChatPromptTemplate` / Runnable） |
| 大模型 | 任意 **OpenAI 兼容**端点：OpenAI / DeepSeek / 通义千问 / 智谱 / Moonshot / vLLM / Ollama |
| 向量库 | **Milvus 2.6 / 3.0**（pymilvus 3.0.2）；Milvus Lite 或本地 JSON 索引（降级） |
| 结构化输出 | JSON mode（`response_format=json_object`），失败自动回退正则提取 |

---

## 三、目录结构

```
.
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 应用入口
│   │   ├── config.py               # 全局配置（环境变量）
│   │   ├── schemas.py              # Pydantic 数据模型
│   │   ├── chains/                 # LangChain 能力链路
│   │   │   ├── router.py           #   意图路由（关键词快判 + 模型兜底）
│   │   │   ├── triage.py           #   智能分诊（JSON 结构化输出）
│   │   │   ├── symptom.py          #   症状咨询
│   │   │   ├── report.py           #   报告解读
│   │   │   ├── faq.py              #   常见问题
│   │   │   ├── rules.py            #   规则分诊知识表（降级引擎）
│   │   │   ├── prompts.py          #   提示词集中管理
│   │   │   └── fallback.py         #   无模型时的兜底渲染
│   │   ├── llm/provider.py         # LLM 后端抽象（LangChain / 规则引擎）
│   │   ├── rag/
│   │   │   ├── embeddings.py       # OpenAI Embedding / 本地哈希向量
│   │   │   ├── vectorstore.py      # Milvus / 本地索引统一接口
│   │   │   ├── knowledge.py        # markdown 知识库加载
│   │   │   └── pipeline.py         # 检索流水线（含混合重排）
│   │   ├── safety/guard.py         # 医疗安全护栏（红旗症状）
│   │   ├── services/               # 会话管理 / 对话编排
│   │   ├── routers/                # API 路由
│   │   └── utils/                  # 文本处理 / 文件解析
│   ├── scripts/                    # 冒烟测试脚本
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.vue                 # 主界面
│   │   ├── api/index.js            # 接口封装（含 SSE 解析）
│   │   ├── components/             # 聊天 / 分诊卡片 / 报告面板等
│   │   └── style.css
│   ├── package.json
│   └── vite.config.js
├── data/knowledge/                 # 内置知识库（markdown）
├── docker/
│   ├── docker-compose.milvus.yml   # Milvus 2.6.25 standalone
│   └── docker-compose.milvus-3.yml # Milvus 3.0.2 standalone
└── start-dev.bat                   # Windows 一键启动
```

---

## 四、快速开始

### 方式 A：Windows 一键启动

双击 `start-dev.bat`，会自动建虚拟环境、装依赖、分别弹出后端与前端窗口。

### 方式 B：手动启动

```bash
# 1) 后端
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt   # Windows
# source .venv/bin/activate && pip install -r backend/requirements.txt   # Linux/macOS

cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2) 前端（另开终端）
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev
```

访问：

| 地址 | 内容 |
|---|---|
| http://127.0.0.1:5173 | 问诊界面 |
| http://127.0.0.1:8000/docs | Swagger API 文档 |
| http://127.0.0.1:8000/api/v1/runtime | 当前生效引擎自检 |

### 无 Key 也能跑

不配置 `OPENAI_API_KEY` 时自动进入**本地规则引擎**：基于 `chains/rules.py` 的
症状→科室映射表 + 知识库检索给出分诊和建议，适合演示、压测与离线环境。

### 两种模式的实际差异

同一问题两个实例对照（`scripts/compare_engine.py`，端口 8000 = 模型 / 8001 = 强制规则引擎）：

| 维度 | 未接入模型（规则引擎） | 接入模型（DeepSeek） |
|---|---|---|
| 响应速度 | 7 ~ 93 ms | 6.7 ~ 7.6 s（推理模型含 reasoning） |
| 分诊依据 | 关键词命中规则表，主诉稍有偏移就错配 | 结合年龄、病程、伴随症状推理 |
| 症状咨询 | 直接拼接检索片段，**检索偏了也照搬** | 能识别"知识库未覆盖该症状"并主动声明 |
| 报告解读 | 只列数值 + 模板化建议 | 给出临床含义与复查建议 |
| 多轮追问 | 规则里写死的固定问题 | 针对本轮信息缺口动态生成 |
| 意图路由 | 关键词快判（只有完全不命中时才走模型） | 关键词 + 模型兜底 |
| 安全护栏 | **完全相同**，命中红旗即短路，两种模式都不调模型 | 同左 |
| RAG 检索 | **完全相同**（本地哈希向量 / Milvus） | 同左 |
| 依赖与成本 | 0 成本、纯离线 | 需 Key、联网、按 token 计费 |

**实测对照（同一问题）**

- 分诊「头晕 + 脖子发僵，45岁男性」
  - 规则：神经内科 🟢门诊择期，给出"紧张型头痛 / 偏头痛"（关键词错配到头痛规则）
  - 模型：神经内科 🟠24h内就诊，给出"颈源性头晕 / 后循环缺血 / BPPV / 脑膜刺激征"，并提示"勿自行按摩正骨"
- 症状咨询「饭后胀、反酸」
  - 规则：检索到《发热》《退热镇痛药》《头痛》《腹泻》——**全不相关**，但仍原样输出
  - 模型：明确声明"本次检索片段均未覆盖该症状，以下内容仅作一般科普"，再给成因与护理要点

> ⚠️ 上例暴露了一个真实短板：**本地哈希向量的检索质量有限**（字符 n-gram 无法理解
> "反酸"与"胃食管反流"的语义关联）。模型模式能识别并声明检索不相关，规则模式做不到。
> 生产环境建议接入真正的 Embedding 模型（或 Milvus + 重排）来根治这个问题。

配置后自动切换到 LangChain + 大模型：

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 OPENAI_API_KEY
```

切换国内模型只需改两行：

```env
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

---

### 公网部署

项目已支持**单端口部署**：后端在根路径托管前端构建产物，一个端口同时提供页面和 API。

```bash
# 1) 构建前端
cd frontend && npm run build

# 2) 组装部署包（只含运行必需文件，不含 .venv / node_modules）
mkdir -p deploy/backend deploy/webroot deploy/data/knowledge
cp -r backend/app deploy/backend/
cp -r frontend/dist/* deploy/webroot/
cp data/knowledge/*.md deploy/data/knowledge/
# requirements.txt 与 run.py 见 deploy/ 目录

# 3) 单端口启动（监听 $PORT、绑定 0.0.0.0）
cd deploy && PORT=8000 python run.py
```

静态目录优先级：`STATIC_DIR` 环境变量 → `<根>/webroot` → `<根>/frontend/dist`。

---

## 五、API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/runtime` | 引擎自检（是否降级） |
| POST | `/api/v1/chat` | 对话（一次性返回） |
| POST | `/api/v1/chat/stream` | 对话（SSE 流式） |
| POST | `/api/v1/triage` | 智能分诊（仅结构化结果） |
| POST | `/api/v1/report/interpret` | 报告解读（文本） |
| POST | `/api/v1/report/upload` | 报告解读（文件） |
| GET | `/api/v1/faq` | 常见问题列表（支持 `q` 过滤） |
| POST | `/api/v1/knowledge/ingest` | 知识库导入 / 重建索引 |
| GET | `/api/v1/knowledge/search` | 检索调试 |
| GET/DELETE | `/api/v1/sessions/{id}` | 会话历史 / 清空 |

**请求示例**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "最近三天咳嗽有黄痰，该挂什么科？",
    "profile": {"age": 35, "gender": "男", "duration": "3天"}
  }'
```

**分诊返回示例**

```json
{
  "department": "呼吸内科",
  "urgency": "routine",
  "possible_conditions": [
    {"name": "急性支气管炎", "probability": "high", "reason": "咳嗽伴咳痰，常继发于上呼吸道感染"}
  ],
  "advice": ["多饮温水，避免油烟与冷空气刺激", "发热超过 3 天或脓痰、胸痛、咯血需拍胸片"],
  "followup_questions": ["咳嗽多久了？干咳还是有痰、什么颜色？"]
}
```

紧急程度：`emergency`（立即 120）→ `urgent`（24h 内）→ `routine`（门诊择期）→ `self_care`（居家观察）。

---

## 六、安全护栏设计

护栏是系统中**优先级最高**的模块，位于 `app/safety/guard.py`。

处理顺序：

1. **红旗扫描**：对用户文本做规则匹配（ACS、卒中 FAST、呼吸窘迫、意识障碍、大出血、
   妊娠急症、婴幼儿高热、心理危机、过敏性休克、急腹症）
2. 命中 → 直接返回 `urgency=emergency` 的急诊指引，**不再调用大模型**
3. 未命中 → 正常走「意图路由 → RAG → 能力链路」

两条经验规则（都是踩过坑后加的）：

- 护栏**只扫描患者侧文本**。助手的历史回复里包含免责声明，其中有"胸痛/呼吸困难"等词，
  扫进去会造成连环误报。
- 只有在意图属于延续性问诊（`triage` / `symptom`）时才回溯历史。
  报告解读、就医服务咨询是新话题，不该被上一轮的症状描述持续拦截。

---

## 七、二次开发

### 加知识

往 `data/knowledge/` 丢 markdown 即可，格式：

```markdown
---
category: 症状自检
source: 院内科普手册 v1.2
---

# 主题

## 小节标题
正文内容…
```

然后重建索引：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/knowledge/ingest \
  -H "Content-Type: application/json" -d '{"rebuild": true}'
```

也可通过接口动态入库：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/knowledge/ingest \
  -H "Content-Type: application/json" \
  -d '{"docs": [{"title": "术后护理", "content": "…", "category": "就医服务", "source": "护理部"}]}'
```

### 加分诊规则（离线模式生效）

编辑 `backend/app/chains/rules.py` 的 `RULES`，新增一条 `TriageRule`：

```python
TriageRule(
    department="风湿免疫科",
    aliases=("风湿科",),
    patterns=(r"关节.*晨僵", r"手指关节.*肿痛"),
    urgency=Urgency.ROUTINE,
    conditions=(PossibleCondition(name="类风湿关节炎", probability="medium",
                                  reason="对称性小关节肿痛伴晨僵"),),
    advice=("记录晨僵持续时间", "建议查类风湿因子与抗 CCP 抗体"),
    questions=("晨僵持续多久？",),
)
```

### 接入 Milvus

`MILVUS_ENABLED=true` 时服务启动会自动探测：连得上就用 Milvus，连不上自动降级，
**不会导致启动失败**。可通过 `/api/v1/runtime` 的 `vector_backend` 确认实际后端。

两种接法（`MILVUS_TARGET` 一个字段控制）：

```env
# 1) Milvus Lite，免 Docker：pip install milvus_lite
MILVUS_TARGET=./data/milvus.db

# 2) Docker standalone（v2.6.25；v3.0.2 用 docker-compose.milvus-3.yml）
MILVUS_TARGET=http://127.0.0.1:19530
```

Docker 方式：

```bash
docker compose -f docker/docker-compose.milvus.yml up -d
```

完整步骤、自检脚本与踩坑清单见 **[docs/Milvus本地验证指南.md](docs/Milvus本地验证指南.md)**：

```bash
../.venv/Scripts/python.exe scripts/check_milvus.py --uri ./data/milvus.db   # 逐级自检
```

> 提示：Milvus 的 collection 维度要与 embedding 维度一致。切换 embedding 模型后，
> 需调用 `/api/v1/knowledge/ingest` 并带 `rebuild: true` 重建。

---

## 八、验证

```bash
cd backend
../.venv/Scripts/python.exe scripts/smoke_test.py      # 六大场景端到端
../.venv/Scripts/python.exe scripts/smoke_stream.py    # SSE 流式
```

冒烟用例覆盖：智能分诊、疑似卒中触发护栏、血常规报告解读、医保 FAQ、症状咨询、寒暄。

---

## 九、合规提示

- 本系统定位为**就医前信息咨询与分诊辅助**，不得用于替代医生诊断或开具处方。
- `ALLOW_MEDICATION_ADVICE` 默认关闭，避免输出具体用药剂量建议。
- 生产环境接入真实患者信息时，需额外满足：数据加密传输与存储、访问控制与审计日志、
  个人信息脱敏（见 `utils/text.py: mask_sensitive`）、医疗数据合规留存要求。
