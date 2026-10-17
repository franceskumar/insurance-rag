#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet -r requirements.txt
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8011}"
