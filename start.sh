#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/uvicorn ]; then
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -r backend/requirements.txt
fi
if [ ! -f frontend/dist/index.html ]; then
  (
    cd frontend
    if command -v pnpm >/dev/null; then
      pnpm install --frozen-lockfile
      pnpm run build
    elif [ -x node_modules/.bin/vite ]; then
      node_modules/.bin/tsc --noEmit && node_modules/.bin/vite build
    else
      npm install && npm run build
    fi
  )
fi
# Copilot's local model runs as its own server. Start it when .env names one and its port is free.
setting() {
  .venv/bin/python -c 'import os,sys; from dotenv import dotenv_values; k=sys.argv[1]; print(os.environ.get(k) or dotenv_values(".env").get(k) or "")' "$1"
}
MODEL=$(setting CLUBOS_LOCAL_COPILOT_MODEL)
if [ -n "$MODEL" ]; then
  MODEL_PORT=$(setting CLUBOS_LOCAL_COPILOT_PORT)
  MODEL_PORT=${MODEL_PORT:-8031}
  if .venv/bin/python -c 'import socket,sys; sys.exit(socket.socket().connect_ex(("127.0.0.1",int(sys.argv[1])))==0)' "$MODEL_PORT"; then
    if [ "$(uname -sm)" = "Darwin arm64" ] && command -v uvx >/dev/null; then
      mkdir -p backend/data
      echo "Starting the local Copilot model on port $MODEL_PORT (log: backend/data/local-model.log)."
      nohup uvx --python 3.12 --from mlx-lm mlx_lm.server --model "$MODEL" --host 127.0.0.1 --port "$MODEL_PORT" >backend/data/local-model.log 2>&1 &
    else
      echo "Copilot's local model is not running on port $MODEL_PORT. Start your model server separately."
    fi
  fi
fi
# Keep the local listener and its OAuth callback on the configured port.
if [ -z "${PORT:-}" ]; then
  PORT=$(.venv/bin/python -c 'from dotenv import dotenv_values; print(dotenv_values(".env").get("PORT") or 8018)')
fi
exec .venv/bin/uvicorn clubos.main:app --app-dir backend --host "${CLUBOS_HOST:-127.0.0.1}" --port "${PORT:-8018}"
