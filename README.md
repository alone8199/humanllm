# 请调用我

**OpenAI 兼容的 chat API，请求会进队列，由在线的人来回。**

接口和 OpenAI 一样：`/v1/models`、`/v1/chat/completions`，支持 stream，Bearer Key。  
差别在于：消息不会送给大模型，而是派到 Worker 工作台，由人看完提示和附件后手动回复，再按 OpenAI 格式（SSE / JSON）返回给你。

```
OpenAI SDK  →  POST /v1/chat/completions  →  任务队列  →  Worker 工作台
                                                         │
OpenAI SDK  ←  SSE / JSON  ←─────────────────────────────┘
```

---

## 能做什么

| 模块 | 说明 |
|------|------|
| **API** | `GET /v1/models`、`POST /v1/chat/completions`（stream SSE）、Bearer Key、OpenAI 错误格式 |
| **多模态** | 文本、图片（URL / Base64）、多图、PDF / TXT / JSON / CSV / DOCX / XLSX，有上传接口 |
| **Worker 工作台** | 登录、在线状态、自动分配 / 抢单、消息 + 附件预览、分片回复、WebSocket 推送 |
| **模型** | `human-default`、`human-fast`、`human-expert`、`human-cn`、`human-en` 等，可配定价、并发、超时、Worker 池 |
| **管理后台** | 用户、Worker、模型、API Key、任务、用量、余额、收入、日志，明暗主题 |
| **计费** | 按请求 / 字符 / 时长预扣与结算，Worker 收入 + 平台抽成，金额全用整数分 |
| **部署** | FastAPI + React；本地 SQLite 零供赖可跑，也有 Docker Compose（Postgres + Redis + MinIO） |

---

## 快速开始（本地）

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="sqlite+aiosqlite:///./humanllm.db"
export QUEUE_BACKEND=memory
export STORAGE_BACKEND=local

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

启动时会自动迁移 + 写入种子数据（模型、管理员、demo 用户 / worker / API Key）。

构建前端后由后端直接托管：

```bash
cd frontend && npm install && npm run build
```

浏览器打开 `http://localhost:8000/` 即可。

### 跑一遍完整链路

```bash
# 终端 A：启动 demo worker
cd backend
python3 scripts/demo_worker.py --base http://localhost:8000 \
  --username worker1 --password admin123

# 终端 B：用 OpenAI SDK 发请求
python3 scripts/run_e2e.py --base http://localhost:8000 \
  --api-key sk-humanllm-demo-key-0001
```

测试：

```bash
cd backend && pytest -q
```

---

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5173 |
| 后端 API | http://localhost:8000 |
| MinIO | http://localhost:9001 |

---

## 调用示例

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-humanllm-demo-key-0001",
    base_url="http://localhost:8000/v1",
)

resp = client.chat.completions.create(
    model="human-default",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "用一句话介绍一下「请调用我」。"},
    ],
)
print(resp.choices[0].message.content)

# 流式
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

## Worker 工作流程

1. 登录拿 JWT，打开工作台，保持 WebSocket 在线  
2. 请求进来后创建任务，自动分配或进抢单池  
3. Worker 看到完整消息和附件，输入回复（可分片），点完成  
4. 后端结算预扣、记 Worker 收入和平台抽成  
5. 超时或断线会退款，自动模式下会尝试重新分配

---

## Demo 账号（仅本地）

| 角色 | 值 |
|------|-----|
| API Key | `sk-humanllm-demo-key-0001` |
| Worker | `worker1` / `worker123` |
| Admin | `admin` / `admin123` |

生产请改 `.env`（参考 `.env.example`）。  
根管理员由 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 生成，标记为初始账户，不可删除。

---

## 计费

- 金额全部用**整数分**存储  
- 创建任务时按模型定价预扣（请求费 + 字符费 + 计时费）  
- 完成后按实际结算，多扣退还；Worker 按比例拿收入，平台拿抽成  
- `usage` 里的 token 数是按字符数 / 4 估的，只为兼容 OpenAI 响应结构

---

## 目录

```
请调用我/
├── backend/          # FastAPI（routers / billing / broker / dispatch…）
├── frontend/         # React + TS（工作台 + 管理后台）
├── docker-compose.yml
├── .env.example
└── API.md            # 接口详情
```

更多接口说明见 [API.md](./API.md)。

---

## Contributors


<p align="center">
  <a href="https://www.deepseek.com" title="DeepSeek"><img src="https://unpkg.com/@lobehub/icons-static-svg@latest/icons/deepseek-color.svg" width="40" height="40" alt="DeepSeek" /></a>&nbsp;&nbsp;
  <a href="https://www.stepfun.com" title="Step"><img src="https://unpkg.com/@lobehub/icons-static-svg@latest/icons/stepfun-color.svg" width="40" height="40" alt="Step" /></a>&nbsp;&nbsp;
  <a href="https://tongyi.aliyun.com" title="千问"><img src="https://unpkg.com/@lobehub/icons-static-svg@latest/icons/qwen-color.svg" width="40" height="40" alt="Qwen" /></a>&nbsp;&nbsp;
  <a href="https://x.ai" title="Grok"><img src="https://unpkg.com/@lobehub/icons-static-svg@latest/icons/grok.svg" width="40" height="40" alt="Grok" /></a>&nbsp;&nbsp;
  <a href="https://kimi.moonshot.cn" title="Kimi"><img src="https://unpkg.com/@lobehub/icons-static-svg@latest/icons/kimi-color.svg" width="40" height="40" alt="Kimi" /></a>&nbsp;&nbsp;
  <a href="https://claude.ai" title="Claude"><img src="https://unpkg.com/@lobehub/icons-static-svg@latest/icons/claude-color.svg" width="40" height="40" alt="Claude" /></a>&nbsp;&nbsp;
  <a href="https://openai.com" title="OpenAI"><img src="https://unpkg.com/@lobehub/icons-static-svg@latest/icons/openai.svg" width="40" height="40" alt="OpenAI" /></a>&nbsp;&nbsp;
  <a href="https://gemini.google.com" title="Gemini"><img src="https://unpkg.com/@lobehub/icons-static-svg@latest/icons/gemini-color.svg" width="40" height="40" alt="Gemini" /></a>&nbsp;&nbsp;
  <a href="https://www.doubao.com" title="豆包"><img src="https://unpkg.com/@lobehub/icons-static-svg@latest/icons/doubao-color.svg" width="40" height="40" alt="Doubao" /></a>&nbsp;&nbsp;
  <a href="https://chatglm.cn" title="智谱"><img src="https://unpkg.com/@lobehub/icons-static-svg@latest/icons/chatglm-color.svg" width="40" height="40" alt="ChatGLM" /></a>
</p>

<p align="center">
  <sub>
    <b>DeepSeek</b> · <b>Step</b> · <b>千问</b> · <b>Grok</b> · <b>Kimi</b> ·
    <b>Claude</b> · <b>OpenAI</b> · <b>Gemini</b> · <b>豆包</b> · <b>智谱</b>
  </sub>
</p>
