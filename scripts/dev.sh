#!/usr/bin/env bash

set -euo pipefail

api_pid=""
web_pid=""

cleanup() {
  [[ -n "$api_pid" ]] && kill "$api_pid" 2>/dev/null || true
  [[ -n "$web_pid" ]] && kill "$web_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

.venv/bin/uvicorn backend.main:app \
  --reload \
  --reload-dir backend \
  --reload-dir src \
  --host 127.0.0.1 \
  --port 8000 &
api_pid=$!

npm --prefix frontend run dev \
  -- \
  --host 127.0.0.1 \
  --port 5173 &
web_pid=$!

wait "$api_pid" "$web_pid"
