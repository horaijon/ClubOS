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
exec .venv/bin/uvicorn clubos.main:app --app-dir backend --host "${CLUBOS_HOST:-127.0.0.1}" --port "${PORT:-8017}"
