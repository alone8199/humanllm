# 请调用我

> 你就是模型。不用 AI，真人本身就是那个「模型」。

**OpenAI 兼容 API，接口一样，对面是真人。**

用 OpenAI SDK 发 `chat/completions`，请求不会跑到任何大模型，而是进入任务队列，派给在线的真人 Worker。  
Worker 在工作台看完整 System / User 消息和附件（图片、PDF、文件…），手动敲回复，再以 SSE 或 JSON、OpenAI 格式原样返回。

```
OpenAI SDK  →  POST /v1/chat/completions  →  任务队列  →  真人 Worker
                                                         │
OpenAI SDK  ←  SSE / JSON（OpenAI 格式）  ←──────────────────┘
```

没有 LLM、没有 fallback、没有自动生成。每一条 `assistant` 消息，都来自一个真实的人。

---

## 为什么要这个？

有时候你就想要一个真人在环里 — 判断、创意、专业领域，或者简单因为「AI 说的」不够。  
请调用我把这件事变成一个可以直接插的 API，你现有的 OpenAI 客户端代码几乎不用改。

---

## 能做什么

| 模块 | 内容 |
|------|------|
| **API** | `GET /v1/models`、`POST /v1/chat/completions`（支持 stream SSE）、Bearer Key、标准 OpenAI 错误格式 |
| **多模态** | 文本、`image_url`、Base64 / Data URL 图片、多图、PDF / TXT / JSON / CSV / DOCX / XLSX，有文件上传 API |
| **Worker 工作台** | 注册/登录、在线/离线、自动分配或抢单、完整消息 + 附件预览、分片回复、WebSocket 实时推送 |
| **模型体系** | `human-default` / `human-fast` / `human-expert` / `human-cn` / `human-en` … 可配 worker 池、技能、定价、并发、超时 |
| **管理后台** | 用户、Worker、模型、API Key、任务、用量、余额、收入、日志，支持明/暗主题 |
| **计费** | 按请求 / 字符 / 时长预扣 + 结算，Worker 收入 + 平台抽成，全部用**整数分**，没浮点坑 |
| **技术栈** | FastAPI · PostgreSQL/SQLite · Redis · MinIO · React；Docker Compose 一键起，也可纯本地零供赖跑 |

---

## 快速开始（本地零供赖）

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="sqlite+aiosqlite:///./humanllm.db"
export QUEUE_BACKEND=memory
export STORAGE_BACKEND=local

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

启动时自动跑迁移 + 种子数据（模型、根管理员、demo 用户 / worker / API Key）。

先构建前端，让 FastAPI 直接托管：

```bash
cd frontend && npm install && npm run build
```

打开 `http://localhost:8000/` 就是工作台 + 管理后台。

### 一键验证完整链路

```bash
# 终端 A：模拟真人 worker
cd backend
python3 scripts/demo_worker.py --base http://localhost:8000 \
  --username worker1 --password admin123

# 终端 B：用官方 OpenAI SDK 发请求（会阻塞直到「真人」回复）
python3 scripts/run_e2e.py --base http://localhost:8000 \
  --api-key sk-humanllm-demo-key-0001
```

测试：

```bash
cd backend && pytest -q   # API / 文件 / 计费 / 流程 / 超时
```

---

## Docker Compose（完整栈）

```bash
cp .env.example .env
docker compose up --build
```

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5173 |
| 后端（OpenAI API） | http://localhost:8000 |
| MinIO 控制台 | http://localhost:9001 |

底层走 Redis + S3（MinIO）。

---

## 像调 OpenAI 一样调

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-humanllm-demo-key-0001",
    base_url="http://localhost:8000/v1",   # 指向「请调用我」，不是 OpenAI
)

# 非流式
resp = client.chat.completions.create(
    model="human-default",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "用一句话介绍一下「请调用我」。"},
    ],
)
print(resp.choices[0].message.content)

# 流式（真人逐块敲回来）
stream = client.chat.completions.create(
    model="human-default",
    messages=[{"role": "user", "content": "你好"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-humanllm-demo-key-0001" \
  -H "Content-Type: application/json" \
  -d '{"model":"human-default","messages":[{"role":"user","content":"你好"}],"stream":false}'
```

---

## 真人 Worker 怎么干活

1. Worker 登录 → 拿 JWT  
2. 打开工作台，保持 WebSocket 在线（`/ws/worker?token=…`）  
3. 调用方发请求 → 创建 Task → 自动分配（或进抢单池）  
4. Worker 看到完整消息 + 附件预览  
5. 手动输入回复，发分片（SSE 实时推给调用方），点「完成」  
6. 后端结算：释放预扣、给 Worker 记收入、平台抽成  
7. 超时 / 断线 → 退款 + （自动模式下）重新分配

---

## Demo 凭据（仅本地）

| 角色 | 值 |
|------|-----|
| API Key | `sk-humanllm-demo-key-0001` |
| Worker | `worker1` / `worker123` |
| Admin | `admin` / `admin123` |

生产环境请用环境变量覆盖（见 `.env.example`）。  
根管理员由 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 读入，标记为初始管理员，**不可删除**。

---

## 计费一眼看懂

- 全部金额用 **整数分（cents）**，没浮点坑  
- 创建任务时预扣：请求费 + 字符费 + 计时费  
- 完成后结算：多扣退还，Worker 拿 `(1 - 抽成率)`，平台拿抽成  
- `usage.tokens` ≈ `字符数 / 4`，纯类型兼容，不代表任何 AI 推理

---

## 目录结构

```
请调用我/
├── backend/                 # FastAPI
│   ├── app/
│   │   ├── main.py          # lifespan: 迁移 → broker → 种子
│   │   ├── config.py / models.py / schemas.py
│   │   ├── billing.py / broker.py / dispatch.py / storage.py
│   │   ├── routers/         # chat · models · files · worker · admin · …
│   │   └── tests/
│   ├── migrations/
│   ├── scripts/             # demo_worker · run_e2e · seed
│   └── requirements.txt
├── frontend/                # React + TS（工作台 + 管理后台）
├── docker-compose.yml
├── .env.example
└── API.md                   # 完整接口文档
```

---

## 硬规矩

> **绝对不用 AI。**  
> 请调用我不调用任何大模型、不集成任何推理服务、不包含任何自动文本生成。  
> 每一条 assistant 回复，都是真人 Worker 在工作台手动敲下去的。  
> 这是产品本体，不是临时限制。

---

<p align="center">
  <strong>召唤真人，而不是模型。</strong>
</p>
