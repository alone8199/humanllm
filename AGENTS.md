# AGENTS.md

A quick reference guide for AI Agents and contributors. After reading this file, you should be able to understand what this project does, where the code is located, where changes should be made, how to run it, and how to deploy it within 5 minutes.

> Public project brand name: **请调用我** (HumanLLM). Core concept: **there is no AI** — every `assistant` response is manually entered by a human Worker. See `README.md` for details.

---

## 1. What Is This?

A **human-response service with an OpenAI-compatible API**:

* Callers use the OpenAI SDK to send `POST /v1/chat/completions` → the request enters a task queue → it is dispatched to an online human Worker → the Worker manually replies from the workbench → the response is returned in OpenAI-compatible SSE / JSON format.
* The backend uses FastAPI and the frontend uses React (Vite). After `npm run build`, the frontend is served by the backend through `StaticFiles` **from the same origin** (same port, no frontend/backend separation).
* The admin panel and login page are frontend SPAs. The Worker workbench also uses the same frontend routing system.

---

## 2. Technology Stack

| Layer          | Technology                                                                                                 |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| Backend        | FastAPI + Uvicorn, SQLAlchemy 2 (async), Pydantic v2                                                       |
| Database       | SQLite (local, default) / PostgreSQL (Docker, via `DATABASE_URL`)                                          |
| Queue          | In-memory asyncio queue (local) / Redis (Docker, `QUEUE_BACKEND`)                                          |
| Storage        | Local filesystem (local) / S3·MinIO (Docker, `STORAGE_BACKEND`)                                            |
| Authentication | bcrypt password hashing + JWT (login), API Key (Bearer, `/v1/*`), WebSocket token                          |
| Frontend       | React 18 + TypeScript + Vite, frontend-only state (no Redux), `axios` for API calls, native `ws` WebSocket |
| Deployment     | systemd service (production server) / Docker Compose (full stack)                                          |

---

## 3. Directory Structure

Only official source code is listed. `*.bak-*` and `*.live` files are excluded.

```text
humanllm/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI entry point: lifespan (migration → broker → seed), router mounting, frontend dist hosting
│   │   ├── config.py          # Configuration class (all values are read from environment variables; see .env.example)
│   │   ├── models.py          # SQLAlchemy ORM + permission model (see §5)
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── security.py        # Password hashing / JWT / API Key generation and validation
│   │   ├── billing.py         # Pre-authorization / settlement / refund / platform commission (integer cents)
│   │   ├── broker.py          # Task channels + event bus (memory/Redis)
│   │   ├── dispatch.py        # Automatic assignment / task claiming / reassignment after disconnects
│   │   ├── database.py        # AsyncSession factory, database engine, migration trigger
│   │   ├── deps.py            # Dependency injection: get_current_user / require_permission / require_super_admin
│   │   ├── auth_guard.py      # Login failure counting, account locking, audit logging
│   │   ├── middleware.py      # Request body size limits / global rate limiting / security response headers
│   │   ├── ratelimit.py       # In-memory rate limiter
│   │   ├── openai_errors.py   # OpenAI-compatible error format
│   │   ├── storage.py         # Local / S3 storage abstraction
│   │   ├── tools.py           # Utility functions
│   │   ├── migrate.py         # Idempotent SQL migrations (reads migrations/*.sql and records them in schema_migrations)
│   │   ├── seed.py            # Initial seed data (root admin is read from .env, marked as is_initial_admin and cannot be deleted)
│   │   └── routers/
│   │       ├── health.py      # GET /health
│   │       ├── chat.py        # POST /v1/chat/completions (OpenAI-compatible core endpoint)
│   │       ├── models.py      # GET /v1/models
│   │       ├── files.py       # POST/GET /v1/files* file upload and download
│   │       ├── worker_auth.py # /auth/login, /auth/admin/login, /auth/user/apikeys
│   │       ├── worker.py      # /api/worker/* Worker REST API (prefix added in main.py)
│   │       └── admin.py       # /api/admin/* admin API (prefix added in main.py)
│   │   ├── tests/             # pytest suite (real uvicorn + real WebSocket)
│   │   ├── migrations/        # 0001_init.sql … 0007_initial_admin_flag.sql (idempotent)
│   │   ├── scripts/           # demo_worker.py / run_e2e.py / verify_full.py / seed.py
│   │   ├── requirements.txt
│   │   ├── pytest.ini
│   │   └── Dockerfile
│   ├── .env                   # Actual environment variables (not committed; used for local execution)
│   └── humanllm.db            # SQLite database file (not committed)
├── frontend/
│   ├── src/
│   │   ├── main.tsx           # Frontend entry point
│   │   ├── App.tsx            # Routing (login / admin panel)
│   │   ├── api.ts             # API client + ALL_PERMISSION_GROUPS + ALL_PERMISSIONS definitions
│   │   ├── ws.ts              # Worker WebSocket client
│   │   ├── pages/
│   │   │   ├── AdminLogin.tsx     # Admin login page
│   │   │   └── AdminDashboard.tsx # Admin dashboard (sidebar: overview/workbench/users/models/keys/tasks/usage/logs)
│   │   ├── Icon.tsx / Checkbox.tsx / ThemeToggle.tsx  # Custom UI components
│   │   └── styles.css         # All styles (Apple-style dark/light themes)
│   ├── public/favicon.svg / logo.svg
│   ├── index.html / vite.config.ts / tsconfig*.json
│   ├── package.json / package-lock.json
│   ├── Dockerfile / nginx.conf.template / vercel.json
│   └── .gitignore
├── docker-compose.yml          # Full stack: FastAPI + PostgreSQL + Redis + MinIO + React
├── start.sh                    # Production startup script (uvicorn :24444, reuses venv)
├── .env.example                # Environment variable template (copy/rename to .env)
├── .gitignore
├── Dockerfile                  # Root Dockerfile (backend multi-stage build)
├── API.md                      # Detailed OpenAI-compatible API documentation
└── README.md                   # Project documentation (anime/cute style)
```

> **Ignore these debugging leftovers:** `*.bak-*`, `*.live`, `backend/.pytest_cache/`, `frontend/shoot*.py`, `frontend/shot_*.png`, and `frontend/.vercel/`. They are not source code and should not be modified.

---

## 4. Route Map

The backend adds prefixes when mounting routers in `main.py`:

| Module      | Actual Path Prefix     | Description                                                                                   |
| ----------- | ---------------------- | --------------------------------------------------------------------------------------------- |
| health      | `/health`              | Health check                                                                                  |
| chat        | `/v1/chat/completions` | OpenAI-compatible chat endpoint                                                               |
| models      | `/v1/models`           | List available models                                                                         |
| files       | `/v1/files*`           | File upload/list/download                                                                     |
| worker_auth | `/auth/*`              | Login (`/auth/login`, alias `/auth/admin/login`), `/auth/user/apikeys`                        |
| worker      | `/api/worker/*`        | Worker REST API (profile, task list)                                                          |
| admin       | `/api/admin/*`         | All admin APIs (see below)                                                                    |
| WebSocket   | `/ws/worker`           | Real-time Worker task delivery (defined in `worker.ws_router`, without the `/api` prefix)     |
| frontend    | `/*`                   | Built SPA (`/admin` admin panel, `/login` login), handled by the catch-all route in `main.py` |

### Main `/api/admin/*` Endpoints

* Users: `GET/POST /users`, `PATCH/DELETE /users/{id}`, `GET /users/{id}/earnings`
* Statistics: `GET /stats`, `GET /calls-trend`
* Workers: `GET/POST /workers`
* Models: `GET/POST /models`, `PATCH/DELETE /models/{name}`
* API Keys: `GET /apikeys`, `POST /apikeys` (returns the full key), `DELETE /apikeys/{id}`
* Tasks: `GET /tasks`, `POST /tasks/{id}/cancel`, `GET /tasks/{id}`
* Usage / logs: `GET /usage`, `GET /logs`

---

## 5. Permission Model

**Read this section before making permission-related changes.**

Defined in `backend/app/models.py`:

* **Roles:** `UserRole.super_admin` (full permissions and ignores the `permissions` field) / `UserRole.staff` (per-module permissions).
* **Permission strings:** `ALL_PERMISSIONS` in backend `models.py` = `["overview","workbench","models","apikeys","tasks","usage","logs"]`.
* **Permission check:** `user_has_perm(user, perm)` — `super_admin` always passes; `staff` requires `perm in user.permissions`.
* **Dependency injection** (`backend/app/deps.py`): `require_permission(perm)` protects individual permissions; `require_super_admin` is restricted to super admins; normal endpoints use `get_current_user` to obtain the current user.
* **Frontend permission groups:** `ALL_PERMISSION_GROUPS` (grouped display) and `ALL_PERMISSIONS` (flat list) are defined in `frontend/src/api.ts`. The frontend and backend keys must remain consistent.
* **Initial administrator:** `seed.py` creates the initial admin from `.env` `ADMIN_USERNAME` / `ADMIN_PASSWORD`, sets `is_initial_admin=True`, and **prevents the account from being deleted** (`admin.py` contains the deletion guard).

> When adding a permission: update `ALL_PERMISSIONS` in `models.py` and `ALL_PERMISSION_GROUPS` / `ALL_PERMISSIONS` in `api.ts`, and add `Depends(require_permission(...))` to the relevant backend routes. Otherwise, the frontend and backend permission systems will become inconsistent.

---

## 6. Local Development

```bash
# Backend (SQLite + in-memory queue + local storage; zero external dependencies)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite+aiosqlite:///./humanllm.db"
export QUEUE_BACKEND=memory
export STORAGE_BACKEND=local
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (open another terminal)
cd frontend
npm install && npm run build      # Built files are served by the backend
npm run dev                       # Or use the local development server (default :5173)

# Verify the complete request flow:
# Terminal A: start the demo worker
python3 scripts/demo_worker.py --base http://localhost:8000 --username worker1 --password <password>

# Terminal B: send a request using the OpenAI SDK
python3 scripts/run_e2e.py --base http://localhost:8000 --api-key <key>

# Tests
pytest -q
```

> Default seed accounts are controlled by `.env` variables such as `DEFAULT_PASSWORD`, `ADMIN_USERNAME`, and `SEED_WORKER_USERNAME`. The root administrator is created from `ADMIN_USERNAME` / `ADMIN_PASSWORD` and cannot be deleted.

---

## 7. Production Deployment

* **Internal port:** `24444`; **external mapping:** `23174 → 24444` (the port mapping cannot be changed).
* Service name: `humanllm.service` (systemd, `Restart=always`), startup script: `start.sh`, virtual environment: `/root/humanllm/venv`.
* Working directory: `/root/humanllm/backend`; `PYTHONPATH=/root/humanllm/backend`.
* Log file: `/root/humanllm/service.log`.
* After frontend changes: `cd frontend && npm run build` → synchronize `dist/` and the modified `src/` files to `/root/humanllm/frontend/` → `systemctl restart humanllm.service`.
* After backend changes: `systemctl restart humanllm.service` (startup automatically runs migrations + seed).
* Access URL: `http://<host>:23174/`.

> Historically, the upstream proxy blocked external port 80, preventing Let's Encrypt from issuing certificates through both HTTP-01 and DNS-01. Therefore, the current deployment uses **plain HTTP**. If HTTPS is required, use a self-signed certificate or put the service behind Cloudflare.

---

## 8. Where to Make Changes

| Task                               | Files to Modify                                                                           |
| ---------------------------------- | ----------------------------------------------------------------------------------------- |
| Add/modify API endpoints           | `backend/app/routers/*.py`                                                                |
| Modify data models / permissions   | `backend/app/models.py` + `backend/migrations/*.sql` if necessary + `frontend/src/api.ts` |
| Modify request/response structures | `backend/app/schemas.py`                                                                  |
| Modify frontend pages/styles       | `frontend/src/pages/*.tsx` + `frontend/src/styles.css`                                    |
| Modify authentication logic        | `backend/app/security.py`, `deps.py`, `auth_guard.py`                                     |
| Modify deployment/configuration    | `backend/app/config.py`, `start.sh`, `.env.example`, `.env`                               |
| Modify billing rules               | `backend/app/billing.py` + `COMMISSION_RATE` and related settings in `config.py`          |

---

## 9. Conventions and Pitfalls

* **Idempotent migrations:** add new tables/columns in `migrations/*.sql` and record each migration version in `schema_migrations`. `migrate.py` automatically applies pending migrations at startup. If you manually run `ALTER` statements in the database, make sure to record the corresponding version in `schema_migrations`; otherwise, the migration may run again after a restart and fail. The `0007_initial_admin_flag` migration previously caused this kind of issue.
* **Same-origin frontend hosting:** do not try to run a separate frontend development server against the production backend. Production serves both from the same port. After making frontend changes, `npm run build` is required.
* **Do not touch `*.bak-*` / `*.live`:** these are temporary debugging files and are not source code.
* **Full API Key value:** after creation, `/api/admin/apikeys` returns the complete API key (`full_key` is persisted), and the frontend list also displays the full key. It is no longer "shown only once".
* **Root administrator protection:** accounts with `is_initial_admin=True` are rejected with HTTP 400 when `delete_user` is called.
* **No AI:** this is a core constraint — every `assistant` response must come from a human. Do not integrate LLM inference into this codebase.
