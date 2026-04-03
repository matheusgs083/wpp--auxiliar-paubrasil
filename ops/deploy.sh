#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/opt/bot_api}"

cd "$PROJECT_DIR"
git pull --ff-only
docker compose up --build -d
docker compose ps
