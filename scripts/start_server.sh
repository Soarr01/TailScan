#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi
cd "$PROJECT_ROOT/server"
exec "${TAILSCAN_API_PYTHON:-$PROJECT_ROOT/.venv/bin/python}" -m uvicorn app:app --host 127.0.0.1 --port 8787
