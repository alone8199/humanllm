# HumanLLM

> **Human is the Model. 完全不使用任何 AI —— 真人本身就是模型。**

HumanLLM 是一个 **OpenAI API 兼容的真人回复服务**。当调用方用 OpenAI SDK 发起一次 `chat/completions` 请求时，请求不会送到任何大模型，而是进入一个**任务队列**，被分发给在线的**真人 Worker**；Worker 在工作台看到完整的 System/User 消息和所有附件（图片、文件、PDF 等），手动输入回复，回复以 **Server-Sent Events (SSE)** 或普通 JSON 的形式，原样以 OpenAI 兼容格式返回给调用方。

```
OpenAI SDK  ──►  POST /v1/chat/completions  ──►  任务队列  ──►  真人 Worker 工作台
                                                                      │
OpenAI SDK  ◄──  OpenAI 兼容响应 (SSE/JSON)     ◄──────────────────┘
```

**这个项目里没有任何 AI 模型、没有任何 AI fallback、没有任何自动生成。** 每一个回复都来自一个真实的人。

---

## 特性

- **OpenAI 兼容 API**：`GET /v1/models`、`POST /v1/chat/completions`（`stream: true` SSE 支持）、Bearer API Key 鉴权、标准 OpenAI 错误格式。
- **多模态接入**：文本、`image_url`、Base64/Data URL 图片、多图、PDF、TXT/JSON/CSV/DOCX/XLSX 文件，文件上传 API，工作台附件预览。
- **真人 Worker 工作台**：注册/登录、在线/离线状态、任务队列、自动分配或抢单（grab）、查看完整 System Prompt / User Message / 附件、输入回复、实时发送、WebSocket 推送、超时/取消/重分配。
- **模型体系**：`human-default` / `human-fast` / `human-expert` / `human-cn` / `human-en` 等，每个模型有 worker 池、技能、定价、并发上限。
- **管理员后台**：用户、Worker、模型、API Key、任务、用量、余额、收入、日志。
- **计费**：按请求/字符/计时计费，记录 worker 收入 + 平台抽成（整数分，无浮点误差）。
- **可部署**：FastAPI + PostgreSQL + Redis + MinIO + React，提供 Docker Compose 一键启动。

---

## 目录结构

```
humanllm/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── main.py          # 应用入口（lifespan: 迁移 → 启动 broker → 种子数据）
│   │   ├── config.py        # 配置（数据库/队列/存储/JWT/计费）
│   │   ├── models.py        # SQLAlchemy ORM
│   │   ├── schemas.py       # Pydantic 请求/响应
│   │   ├── security.py      # 密码哈希 / JWT / API Key
│   │   ├── billing.py       # 预扣/结算/退款/抽成
│   │   ├── broker.py        # 任务通道 + 事件总线（memory/redis）
│   │   ├── dispatch.py      # 自动分配 / 抢单 / 断线重分配
│   │   ├── storage.py       # 本地 / S3(MinIO) 存储抽象
│   │   ├── openai_errors.py # OpenAI 兼容错误
│   │   ├── routers/         # chat / models / files / worker / worker_auth / admin / health
│   │   ├── migrate.py       # 幂等 SQL 迁移
│   │   ├── seed.py          # 初始种子数据
│   │   └── tests/           # pytest 套件（真实 uvicorn + 真实 WS）
│   ├── migrations/0001_init.sql
│   ├── scripts/             # demo_worker.py / run_e2e.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                # React + TypeScript 工作台 & 管理后台
│   ├── src/pages/WorkerWorkbench.tsx
│   ├── src/pages/AdminDashboard.tsx
│   └── ...
├── docker-compose.yml
├── .env.example
└── README.md / API.md
```

---

## 快速开始（本地零依赖开发）

无需 Docker。使用 SQLite + 本地存储 + 内存队列即可完整运行：

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="sqlite+aiosqlite:///./humanllm.db"
export QUEUE_BACKEND=memory
export STORAGE_BACKEND=local

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

启动后自动执行迁移 + 种子数据（5 个模型、1 个管理员、1 个 demo 用户、1 个 demo worker、1 个 demo API Key）。
**前端构建后由 FastAPI 自动托管**：先 `cd frontend && npm install && npm run build`，再启动后端，浏览器访问 `http://localhost:8000/` 即工作台页面。

> 默认账号密码统一为 `admin123`（由环境变量 `DEFAULT_PASSWORD` 控制）：Admin `admin`、Worker `worker1`。调用方 API Key 为 `sk-humanllm-demo-key-0001`。

### 一键验证完整链路（OpenAI SDK → 真人 → 响应）

另开终端，启动一个**真人 Worker 模拟器**，然后用官方 OpenAI SDK 发起请求：

```bash
# 终端 A：启动 demo 真人 worker（连接到工作台 WebSocket）
cd backend
python3 scripts/demo_worker.py --base http://localhost:8000 --username worker1 --password admin123

# 终端 B：用 OpenAI SDK 发起请求（会阻塞直到真人回复）
cd backend
python3 scripts/run_e2e.py --base http://localhost:8000 --api-key sk-humanllm-demo-key-0001
```

`run_e2e.py` 会依次验证：非流式回复、流式 SSE 回复、带图片附件的回复。**所有回复都来自 demo worker（真人模拟），全程无任何 AI 调用。**

### 运行测试

```bash
cd backend
pytest -q          # 15 个测试：API/文件/计费/流程/超时，全部绿色
```

---

## 使用 Docker Compose（完整栈）

```bash
cp .env.example .env
docker compose up --build
# 前端:  http://localhost:5173
# 后端:  http://localhost:8000   (OpenAI 兼容 API)
# MinIO 控制台: http://localhost:9001
```

后端通过 `QUEUE_BACKEND=redis`、`STORAGE_BACKEND=s3` 接入 Redis 与 MinIO；前端经 nginx 代理 `/api` 与 `/ws` 到后端。

---

## 调用示例（OpenAI SDK）

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-humanllm-demo-key-0001",     # 你的 HumanLLM API Key
    base_url="http://localhost:8000/v1",       # 指向 HumanLLM，而非 OpenAI
)

# 非流式
resp = client.chat.completions.create(
    model="human-default",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user",   "content": "用一句话介绍 HumanLLM。"},
    ],
    stream=False,
)
print(resp.choices[0].message.content)

# 流式（真人逐块回复，SSE）
stream = client.chat.completions.create(
    model="human-default",
    messages=[{"role": "user", "content": "你好"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### curl

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-humanllm-demo-key-0001" \
  -H "Content-Type: application/json" \
  -d '{"model":"human-default","messages":[{"role":"user","content":"你好"}],"stream":false}'
```

---

## 真人 Worker 怎么工作

1. Worker 在 `/worker/login` 登录，拿到 JWT。
2. Worker 打开工作台页面（`/worker`），通过 `ws://host/ws/worker?token=...` 建立 WebSocket 并保持在线。
3. 调用方发来请求 → 后端创建 Task → 自动分配给最闲的在线 Worker（或进入抢单池）。
4. Worker 的 WebSocket 收到 `task_assigned`，工作台展示完整消息 + 附件预览。
5. Worker 手动输入回复，点「发送片段」逐块回传（SSE 实时推给调用方），点「完成」提交最终回复。
6. 后端结算：释放预扣、给 Worker 记收入、给平台记抽成，返回 OpenAI 兼容响应。
7. 若超时/Worker 断线，任务自动退款并（在自动分配模式下）重分配给其他在线 Worker。

---

## 默认凭据（仅 demo / 本地）

| 角色 | 用户名 | 密码 / Key |
|------|--------|------------|
| API Key | — | `sk-humanllm-demo-key-0001` |
| Worker | `worker1` | `worker123` |
| Admin | `admin` | `admin123` |

生产环境请通过环境变量覆盖这些种子值（见 `.env.example`）。

---

## 计费说明

- 所有金额以**整数分（cents）**存储，避免浮点误差。
- 创建任务时按模型定价**预扣（preauth hold）**：`请求费 + 字符费 + 计时费`。
- 完成后**结算**：实际费用 = `min(回复字符, 上限)` 计费；多扣部分**退还**用户；Worker 获得 `实际费用 × (1 - 抽成率)`；平台获得抽成。
- `usage` 对象里的 token 数为 `字符数 / 4` 的估算（仅为兼容 OpenAI 格式，不代表任何 AI 推理）。

---

## 绝对无 AI 声明

HumanLLM 不调用任何大语言模型、不集成任何 AI 推理服务、不包含任何自动文本生成逻辑。所有 `assistant` 角色的回复内容，100% 来自真人 Worker 通过工作台手动输入并提交的文本。这是本项目的核心设计约束，而非缺省行为。
