#!/usr/bin/env bash
# Start the Sasquatch Story Studio web application.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtualenv…"
  python3 -m venv .venv
  .venv/bin/pip install --disable-pip-version-check -q -r requirements.txt
fi

exec .venv/bin/uvicorn studio.server:app --host "${STUDIO_HOST:-0.0.0.0}" --port "${STUDIO_PORT:-8000}"
