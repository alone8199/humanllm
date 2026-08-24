# HumanLLM single-service image: builds the React frontend, then runs the
# FastAPI backend which also serves the built SPA from /frontend/dist.
# One container = frontend + API + WebSocket, no separation needed.

# ---- Stage 1: frontend static assets ----
# The SPA is built on the build host and copied in, so the image build does
# not need Node/npm. Adjust the COPY source if you build elsewhere.
FROM scratch AS frontend
COPY frontend/dist /dist

# ---- Stage 2: backend + serve the built SPA ----
FROM python:3.11-slim AS backend
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/ ./backend/
# Bring in the built frontend SPA (served by FastAPI from /frontend/dist).
COPY --from=frontend /dist ./frontend/dist

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
