#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export VET_DATABASE="${VET_DATABASE:-$PWD/data/vet.db}"
export VET_AUTO_COLLECT="${VET_AUTO_COLLECT:-1}"
exec .venv/bin/python -m uvicorn vetapp.main:app --host 127.0.0.1 --port "${VET_PORT:-8000}"
