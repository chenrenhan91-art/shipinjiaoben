#!/usr/bin/env bash
# 一键启动 MVP：本机服务 + 打开浏览器
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

PORT="${PORT:-8765}"
URL="http://127.0.0.1:${PORT}"

# 释放旧进程
lsof -ti:"${PORT}" | xargs kill -9 2>/dev/null || true
sleep 0.5

echo "启动服务：${URL}"
python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT}" &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT

for i in $(seq 1 30); do
  if curl -sf "${URL}/api/health" >/dev/null; then
    break
  fi
  sleep 0.3
done

echo "打开浏览器：${URL}"
if command -v open >/dev/null; then
  open "${URL}"
elif command -v xdg-open >/dev/null; then
  xdg-open "${URL}"
fi

wait $PID
