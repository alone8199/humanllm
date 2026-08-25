# AGENTS.md

面向 AI Agent / 协作者的项目速查手册。读完这份文件,你应当能在 5 分钟内理解这个项目在做什么、代码在哪、改动该落在哪、怎么跑起来和部署。

> 项目对外品牌名:**请调用我**(HumanLLM)。核心理念:**没有任何 AI**——所有 `assistant` 回复都来自真人 Worker 手动输入。详见 `README.md`。

---

## 1. 这是什么

一个 **OpenAI API 兼容的真人回复服务**:

- 调用方用 OpenAI SDK 发 `POST /v1/chat/completions` → 请求进入任务队列 → 分发给在线真人 Worker → Worker 在工作台手动回复 → 以 SSE / JSON 原样返回 OpenAI 兼容格式。
- 后端 FastAPI + 前端 React(Vite),前端 `npm run build` 后由后端 `StaticFiles` **同源托管**(同一端口,无前后端分离)。
- 管理后台、登录页是前端 SPA;Worker 工作台也走同一套前端路由。

---

## 2. 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI + Uvicorn,SQLAlchemy 2(async),Pydantic v2 |
| 数据库 | SQLite(本地,默认)/ PostgreSQL(Docker,通过 `DATABASE_URL`) |
| 队列 | 内存 asyncio 队列(本地)/ Redis(Docker,`QUEUE_BACKEND`) |
| 存储 | 本地文件系统(本地)/ S3·MinIO(Docker,`STORAGE_BACKEND`) |
| 鉴权 | 密码 bcrypt + JWT(登录)、API Key(Bearer,调用 `/v1/*`)、WebSocket token |
| 前端 | React 18 + TypeScript + Vite,纯前端状态(无 Redux),`axios` 调 API,`ws` 原生 WebSocket |
| 部署 | systemd 服务(生产机)/ Docker Compose(完整栈) |

---

## 3. 目录结构(只列正式源码,忽略 `*.bak-*` / `*.live`)

```
humanllm/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口: lifespan(迁移→broker→seed)、挂载所有 router、托管前端 dist
│   │   ├── config.py          # 配置类(全部从环境变量读取,见 .env.example)
│   │   ├── models.py          # SQLAlchemy ORM + 权限模型(见 §5)
│   │   ├── schemas.py         # Pydantic 请求/响应模型
│   │   ├── security.py        # 密码哈希 / JWT / API Key 生成与校验
│   │   ├── billing.py         # 预扣 / 结算 / 退款 / 平台抽成(整数分)
│   │   ├── broker.py          # 任务通道 + 事件总线(memory/redis)
│   │   ├── dispatch.py        # 自动分配 / 抢单 / 断线重分配
│   │   ├── database.py        # AsyncSession 工厂、引擎、迁移触发
│   │   ├── deps.py            # 依赖注入: get_current_user / require_permission / require_super_admin
│   │   ├── auth_guard.py      # 登录失败计数、锁定、审计日志
│   │   ├── middleware.py      # 请求体大小限制 / 全局限流 / 安全响应头
│   │   ├── ratelimit.py       # 内存限流器
│   │   ├── openai_errors.py   # OpenAI 兼容错误格式
│   │   ├── storage.py         # 本地 / S3 存储抽象
│   │   ├── tools.py           # 工具函数
│   │   ├── migrate.py         # 幂等 SQL 迁移(读 migrations/*.sql,记录于 schema_migrations)
│   │   ├── seed.py            # 初始种子(根管理员从 .env 读取,标记为 is_initial_admin 不可删除)
│   │   └── routers/
│   │       ├── health.py      # GET /health
│   │       ├── chat.py        # POST /v1/chat/completions(OpenAI 兼容,核心入口)
│   │       ├── models.py      # GET /v1/models
│   │       ├── files.py       # POST/GET /v1/files* 文件上传与下载
│   │       ├── worker_auth.py # /auth/login、/auth/admin/login、/auth/user/apikeys
│   │       ├── worker.py      # /api/worker/* Worker REST(前缀在 main.py 加)
│   │       └── admin.py       # /api/admin/* 管理后台 API(前缀在 main.py 加)
│   │   ├── tests/             # pytest 套件(真实 uvicorn + 真实 WS)
│   │   ├── migrations/        # 0001_init.sql … 0007_initial_admin_flag.sql(幂等)
│   │   ├── scripts/           # demo_worker.py / run_e2e.py / verify_full.py / seed.py
│   │   ├── requirements.txt
│   │   ├── pytest.ini
│   │   └── Dockerfile
│   ├── .env                   # 实际环境变量(不入库,本地运行用)
│   └── humanllm.db            # SQLite 数据库文件(不入库)
├── frontend/
│   ├── src/
│   │   ├── main.tsx           # 前端入口
│   │   ├── App.tsx            # 路由(登录 / 管理后台)
│   │   ├── api.ts             # API 客户端 + ALL_PERMISSION_GROUPS + ALL_PERMISSIONS 定义
│   │   ├── ws.ts              # Worker WebSocket 客户端
│   │   ├── pages/
│   │   │   ├── AdminLogin.tsx     # 管理员登录页
│   │   │   └── AdminDashboard.tsx # 管理后台(侧边栏:概览/工作台/用户/模型/密钥/任务/用量/日志)
│   │   ├── Icon.tsx / Checkbox.tsx / ThemeToggle.tsx  # 自定义 UI 组件
│   │   └── styles.css         # 全部样式(苹果风深色/浅色主题)
│   ├── public/favicon.svg / logo.svg
│   ├── index.html / vite.config.ts / tsconfig*.json
│   ├── package.json / package-lock.json
│   ├── Dockerfile / nginx.conf.template / vercel.json
│   └── .gitignore
├── docker-compose.yml        # 完整栈:FastAPI + PostgreSQL + Redis + MinIO + React
├── start.sh                  # 生产机启动脚本(uvicorn :24444,复用 venv)
├── .env.example              # 环境变量模板(改名叫 .env 使用)
├── .gitignore
├── Dockerfile                # 根 Dockerfile(后端多阶段)
├── API.md                    # OpenAI 兼容接口详细说明
└── README.md                 # 项目说明(二次元可爱风)
```

> **忽略这些调试残留**:`*.bak-*`、`*.live`、`backend/.pytest_cache/`、`frontend/shoot*.py`、`frontend/shot_*.png`、`frontend/.vercel/`。它们不是源码,改动时不要碰。

---

## 4. 路由地图

后端在 `main.py` 挂载路由时统一加前缀:

| 模块 | 实际路径前缀 | 说明 |
|------|-------------|------|
| health | `/health` | 健康检查 |
| chat | `/v1/chat/completions` | OpenAI 兼容聊天入口 |
| models | `/v1/models` | 列出可用模型 |
| files | `/v1/files*` | 文件上传/列出/下载 |
| worker_auth | `/auth/*` | 登录(`/auth/login` 别名 `/auth/admin/login`)、`/auth/user/apikeys` |
| worker | `/api/worker/*` | Worker REST(个人资料、任务列表) |
| admin | `/api/admin/*` | 管理后台全部 API(见下) |
| WebSocket | `/ws/worker` | Worker 实时任务推送(在 `worker.ws_router`,无 `/api` 前缀) |
| 前端 | `/*` | 构建后的 SPA(`/admin` 后台、`/login` 登录),由 `main.py` 的 catch-all 兜底 |

**管理后台 `/api/admin/*` 主要端点**:
- 用户:`GET/POST /users`、`PATCH/DELETE /users/{id}`、`GET /users/{id}/earnings`
- 统计:`GET /stats`、`GET /calls-trend`
- Worker:`GET/POST /workers`
- 模型:`GET/POST /models`、`PATCH/DELETE /models/{name}`
- API Key:`GET /apikeys`、`POST /apikeys`(返回完整 key)、`DELETE /apikeys/{id}`
- 任务:`GET /tasks`、`POST /tasks/{id}/cancel`、`GET /tasks/{id}`
- 用量/日志:`GET /usage`、`GET /logs`

---

## 5. 权限模型(改动权限相关必读)

定义在 `backend/app/models.py`:

- **角色**:`UserRole.super_admin`(全权限,忽略 `permissions` 字段) / `UserRole.staff`(逐模块权限)。
- **权限字符串**:`ALL_PERMISSIONS`(后端 `models.py`)= `["overview","workbench","models","apikeys","tasks","usage","logs"]`。
- **判定**:`user_has_perm(user, perm)` —— super_admin 永远通过;staff 需 `perm in user.permissions`。
- **依赖注入**(`backend/app/deps.py`):`require_permission(perm)` 保护单个权限;`require_super_admin` 仅超管;普通接口用 `get_current_user` 拿当前用户。
- **前端权限组**:`frontend/src/api.ts` 的 `ALL_PERMISSION_GROUPS`(分组展示)与 `ALL_PERMISSIONS`(扁平列表)。前后端 key 要保持一致。
- **初始管理员**:`seed.py` 从 `.env` 的 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 创建,`is_initial_admin=True`,**不可删除**(`admin.py` 的 `delete_user` 有守卫)。

> 新增权限时:同时改 `models.py` 的 `ALL_PERMISSIONS` 与 `api.ts` 的 `ALL_PERMISSION_GROUPS`/`ALL_PERMISSIONS`,并在后端路由加 `Depends(require_permission(...))`,否则前后端会不一致。

---

## 6. 本地开发

```bash
# 后端(SQLite + 内存队列 + 本地存储,零依赖)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite+aiosqlite:///./humanllm.db"
export QUEUE_BACKEND=memory
export STORAGE_BACKEND=local
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 前端(另开终端)
cd frontend
npm install && npm run build      # 构建后由后端同源托管
npm run dev                        # 或本地开发服务器(默认 :5173)

# 验证链路:终端 A 起 demo worker,终端 B 用 OpenAI SDK 发请求
python3 scripts/demo_worker.py --base http://localhost:8000 --username worker1 --password <密码>
python3 scripts/run_e2e.py --base http://localhost:8000 --api-key <key>

# 测试
pytest -q
```

> 默认种子账号由 `.env` 的 `DEFAULT_PASSWORD` / `ADMIN_USERNAME` / `SEED_WORKER_USERNAME` 等控制。根管理员从 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 读取且不可删除。

---

## 7. 生产机部署(当前线上环境)

- **内部端口 24444**,外部映射 **23174 → 24444**(端口映射不可改)。
- 服务名 `humanllm.service`(systemd,`Restart=always`),启动脚本 `start.sh`,venv 在 `/root/humanllm/venv`。
- 工作目录 `/root/humanllm/backend`,`PYTHONPATH=/root/humanllm/backend`。
- 日志:`/root/humanllm/service.log`。
- 前端改动后流程:`cd frontend && npm run build` → 把 `dist/` + 改动的 `src/` 同步到 `/root/humanllm/frontend/` → `systemctl restart humanllm.service`。
- 后端改动后:`systemctl restart humanllm.service`(启动会自动跑迁移 + seed)。
- 访问地址:`http://<host>:23174/`。

> 历史上外部 80 端口被上游代理拦截,Let's Encrypt HTTP-01 与 DNS-01 均无法签发证书,故当前为 **HTTP 明文**。若要 HTTPS 需自签证书或套 Cloudflare。

---

## 8. 改动落点速查

| 我要做 | 改哪里 |
|--------|--------|
| 加/改 API 端点 | `backend/app/routers/*.py` |
| 改数据模型 / 权限 | `backend/app/models.py` + 必要时 `backend/migrations/*.sql` + `frontend/src/api.ts` |
| 改请求/响应结构 | `backend/app/schemas.py` |
| 改前端页面/样式 | `frontend/src/pages/*.tsx` + `frontend/src/styles.css` |
| 改鉴权逻辑 | `backend/app/security.py`、`deps.py`、`auth_guard.py` |
| 改部署/配置 | `backend/app/config.py`、`start.sh`、`.env.example`、`.env` |
| 改计费规则 | `backend/app/billing.py` + `config.py` 的 `COMMISSION_RATE` 等 |

---

## 9. 约定与坑

- **迁移幂等**:新增表/列改 `migrations/*.sql`,并在 `schema_migrations` 记录版本;`migrate.py` 启动自动跑未应用的。手动在库里 ALTER 后务必把版本写进 `schema_migrations`,否则重启会重跑报错(曾踩过 `0007_initial_admin_flag` 的坑)。
- **前端同源托管**:不要试图单独起前端 dev server 接生产后端,生产是同一端口。改完必须 `npm run build`。
- **不要碰 `*.bak-*` / `*.live`**:那是调试临时文件,不是源码。
- **API Key 完整值**:创建后在 `/api/admin/apikeys` 直接返回完整 key(`full_key` 持久化),前端列表也直接显示完整 key,不再「仅显示一次」。
- **根管理员保护**:`is_initial_admin=True` 的账户 `delete_user` 会 400 拒绝。
- **无 AI**:核心约束——任何 `assistant` 回复都来自真人,不要在这套代码里接大模型推理。
