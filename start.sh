#!/usr/bin/env bash
set -e
cd /root/humanllm/backend
source /root/humanllm/venv/bin/activate
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 24444 --no-server-header
