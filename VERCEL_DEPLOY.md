# 请调用我 部署指南

## 架构：前后端不分离（单服务）

请调用我 现在是**单服务**架构：FastAPI 后端同时托管前端静态页面（`frontend/dist`）和所有 API / WebSocket。因此：

- **前端的 IP / 域名本身就是 API 端点**
- 不需要 CORS（同域）、不需要反代、不需要单独的前端部署平台
- 浏览器访问 `http://你的服务器:8000/` 就能看到工作台
- 调用方访问 `http://你的服务器:8000/v1/chat/completions`
- 真人 Worker 工作台连接 `ws://你的服务器:8000/ws/worker`

> **为什么不用 Vercel / Cloudflare 单独托管前端？**
> 因为它们跑不了 FastAPI + WebSocket（Serverless 不支持常驻长连接）。
> 既然前后端必须同域，那就把整套打成一个服务，部署到**支持 WebSocket 的平台**：
> 你的自有服务器 / Railway / Render / Fly.io。

## 部署到支持 WebSocket 的平台

### 方式 1：Docker（Railway / Render / Fly.io / 自有服务器通用）

仓库根目录已有：
- `backend/Dockerfile` — 构建后端镜像（含 pip 依赖）
- `frontend/` — 前端源码

但单服务需要**先 build 前端，再让后端托管 dist**。推荐用一个合并的 Dockerfile，或在 CI 里先 `npm run build` 再打包。

最简做法（自有服务器 / 任意 Docker 环境）：

```bash
# 1. 构建前端
cd frontend && npm install && npm run build && cd ..

# 2. 构建并运行后端（会自动托管 frontend/dist）
cd backend
docker build -t humanllm .
docker run -d -p 8000:8000 \
  -e DATABASE_URL="postgresql+asyncpg://user:pass@host/db" \
  -e REDIS_URL="redis://host:6379/0" \
  -e STORAGE_BACKEND=s3 -e S3_ENDPOINT=... \
  -e JWT_SECRET="你的密钥" \
  -e DEFAULT_PASSWORD="你的默认密码" \
  -e AUTO_ASSIGN=true \
  humanllm
```

> 本地零依赖开发：`DATABASE_URL="sqlite+aiosqlite:///./h.db" QUEUE_BACKEND=memory STORAGE_BACKEND=local uvicorn app.main:app --port 8000`

### 方式 2：Railway / Render（无 Docker 也行）

1. 连 GitHub 仓库
2. 启动命令设为：
   ```bash
   cd frontend && npm install && npm run build && cd ../backend && pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
3. 设环境变量（见 `.env.example`）：`DATABASE_URL`、`REDIS_URL`、`JWT_SECRET`、`DEFAULT_PASSWORD` 等
4. 启用 WebSocket（Railway 默认支持；Render 用 Web Service 默认支持）

## 默认密码（单密码）

所有种子账号共用一个默认密码，由环境变量 `DEFAULT_PASSWORD` 控制（默认 `admin123`）：

- Admin 登录：`admin` / `DEFAULT_PASSWORD`
- Worker 登录：`worker1` / `DEFAULT_PASSWORD`
- 调用方 API Key：`sk-humanllm-demo-key-0001`（环境变量 `SEED_API_KEY` 可改）

生产务必通过环境变量覆盖 `DEFAULT_PASSWORD` 和 `JWT_SECRET`。

## API 路径约定

- OpenAI 兼容：`/v1/models`、`/v1/chat/completions`、`/v1/files`
- 内部/管理/Worker REST（前端用）：统一前缀 `/api`
  - `/api/auth/worker/login`、`/api/auth/admin/login`、`/api/auth/worker/register`
  - `/api/worker/me`、`/api/worker/tasks`
  - `/api/admin/stats`、`/api/admin/models`、`/api/admin/workers`、`/api/admin/apikeys`、`/api/admin/tasks`、`/api/admin/usage`、`/api/admin/logs`
- WebSocket（worker 工作台）：`/ws/worker?token=<jwt>`（**不带** `/api` 前缀）
- 健康检查：`/health`

## 验证

部署后访问 `http://你的服务器:8000/`：
1. `/worker/login` 用 `worker1` / 你的默认密码登录 → 工作台显示 `connected`
2. `/admin/login` 用 `admin` / 你的默认密码登录 → 后台显示统计
3. 用 OpenAI SDK 发请求（base_url 指向你的服务器 `/v1`），真人 Worker 在工作台收到任务并回复
