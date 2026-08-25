# HumanLLM

**OpenAI-compatible API. Zero AI. 100% real humans.**

Drop-in replacement for `chat/completions` — except the model on the other end is an actual person sitting at a workbench, reading your prompt (and images/PDFs), and typing the reply themselves.

```
OpenAI SDK  →  POST /v1/chat/completions  →  task queue  →  human worker
                                                              │
OpenAI SDK  ←  SSE / JSON (OpenAI format)  ←──────────────────┘
```

No LLMs. No fallbacks. No auto-generation. Every `assistant` message comes from a real human.

---

## Why?

Sometimes you want a human in the loop — for judgment, creativity, domain expertise, or just because "AI said so" isn't good enough. HumanLLM turns that into a drop-in API so your existing OpenAI client code keeps working.

---

## Features

| Area | What you get |
|------|--------------|
| **API** | `GET /v1/models`, `POST /v1/chat/completions` (streaming SSE), Bearer keys, standard OpenAI error shapes |
| **Multimodal** | Text, `image_url`, base64/data-URL images, multi-image, PDF / TXT / JSON / CSV / DOCX / XLSX + file upload API |
| **Workers** | Register/login, online/offline, auto-dispatch or grab queue, full system+user+attachments view, chunked replies over WebSocket |
| **Models** | `human-default`, `human-fast`, `human-expert`, `human-cn`, `human-en` … configurable pools, skills, pricing, concurrency, timeouts |
| **Admin** | Users, workers, models, API keys, tasks, usage, balance, revenue, logs — light/dark theme |
| **Billing** | Per-request / per-char / per-minute preauth + settle. Worker payout + platform cut. All amounts in integer cents |
| **Stack** | FastAPI · PostgreSQL/SQLite · Redis · MinIO · React. Docker Compose one-liner or pure local (no Docker needed) |

---

## Quick start (local, zero infra)

```bash
# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="sqlite+aiosqlite:///./humanllm.db"
export QUEUE_BACKEND=memory
export STORAGE_BACKEND=local

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Migrations + seed data run automatically (models, root admin, demo user/worker/API key).

Build the frontend so FastAPI can serve it:

```bash
cd frontend && npm install && npm run build
```

Open `http://localhost:8000/` → workbench + admin UI.

### One-command end-to-end check

```bash
# terminal A — fake human worker
cd backend
python3 scripts/demo_worker.py --base http://localhost:8000 \
  --username worker1 --password admin123

# terminal B — real OpenAI SDK call (blocks until the "human" replies)
python3 scripts/run_e2e.py --base http://localhost:8000 \
  --api-key sk-humanllm-demo-key-0001
```

Tests:

```bash
cd backend && pytest -q   # API, files, billing, flow, timeout
```

---

## Docker Compose (full stack)

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend (OpenAI API) | http://localhost:8000 |
| MinIO console | http://localhost:9001 |

Uses Redis + S3 (MinIO) under the hood.

---

## Call it like OpenAI

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-humanllm-demo-key-0001",
    base_url="http://localhost:8000/v1",
)

# non-streaming
resp = client.chat.completions.create(
    model="human-default",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "One sentence: what is HumanLLM?"},
    ],
)
print(resp.choices[0].message.content)

# streaming (human types chunk-by-chunk)
stream = client.chat.completions.create(
    model="human-default",
    messages=[{"role": "user", "content": "Hi"}],
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

## How a human worker actually works

1. Worker logs in → gets JWT  
2. Opens workbench, keeps WebSocket alive (`/ws/worker?token=…`)  
3. Incoming request creates a Task → auto-assigned (or grab pool)  
4. Worker sees full messages + attachment previews  
5. Types reply, sends chunks (streamed to the caller as SSE), hits **Done**  
6. Backend settles: release preauth, credit worker, take platform cut  
7. Timeout / disconnect → refund + re-dispatch (auto mode)

---

## Demo credentials (local only)

| Role | Value |
|------|--------|
| API Key | `sk-humanllm-demo-key-0001` |
| Worker | `worker1` / `worker123` |
| Admin | `admin` / `admin123` |

Override via env (see `.env.example`). The root admin from `ADMIN_USERNAME` / `ADMIN_PASSWORD` is marked initial and **cannot be deleted**.

---

## Billing in one glance

- All money is **integer cents** — no float surprises.  
- On create: preauth = request fee + char fee + time fee.  
- On finish: actual cost calculated, overage refunded, worker gets `(1 − cut)`, platform keeps the rest.  
- `usage.tokens` ≈ `chars / 4` purely for OpenAI shape compatibility.

---

## Project layout

```
humanllm/
├── backend/                 # FastAPI
│   ├── app/
│   │   ├── main.py          # lifespan: migrate → broker → seed
│   │   ├── config.py
│   │   ├── models.py / schemas.py
│   │   ├── billing.py / broker.py / dispatch.py / storage.py
│   │   ├── routers/         # chat · models · files · worker · admin · …
│   │   └── tests/
│   ├── migrations/
│   ├── scripts/             # demo_worker · run_e2e · seed
│   └── requirements.txt
├── frontend/                # React + TS (workbench + admin)
├── docker-compose.yml
├── .env.example
└── API.md                   # full endpoint reference
```

---

## The hard rule

> **No AI.**  
> HumanLLM never calls an LLM, never embeds an inference service, never generates text automatically.  
> Every assistant reply is typed by a real person on the workbench.  
> That’s the product, not a temporary limitation.

---

<p align="center">
  <strong>Summon humans, not models.</strong>
</p>
