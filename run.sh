#!/usr/bin/env bash
# ========================================================
#  JobPilot v2: Multi-Source Application Assistant
#  Local-first server & background scheduler runner
# ========================================================

set -e

if [ ! -f "venv/bin/python" ]; then
    echo "[ERROR] Virtual environment not found in ./venv. Please create one with: python3 -m venv venv"
    exit 1
fi

echo "[JobPilot v2] Starting FastAPI server on http://127.0.0.1:8000 ..."
./venv/bin/python -m jobpilot run --host 127.0.0.1 --port 8000

