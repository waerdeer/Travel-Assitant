#!/usr/bin/env bash
set -euo pipefail

task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
task_python="$task_root/.venv/bin/python"
if [[ ! -x "$task_python" || ! -d "$task_root/Frontend/node_modules" ]]; then
  echo "请先按 README 安装 Python 和前端依赖。" >&2
  exit 1
fi
if [[ ! -f "$task_root/Backend/.env" ]]; then
  echo "请先将 .env.example 复制为 Backend/.env 并填写 API Key。" >&2
  exit 1
fi

task_backend_pid=""
task_frontend_pid=""
cleanup() {
  [[ -z "$task_backend_pid" ]] || kill "$task_backend_pid" 2>/dev/null || true
  [[ -z "$task_frontend_pid" ]] || kill "$task_frontend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$task_python" -m uvicorn app.main:app --app-dir "$task_root/Backend" \
  --host 127.0.0.1 --port 8000 --reload --reload-dir "$task_root/Backend" &
task_backend_pid=$!
(
  cd "$task_root/Frontend"
  exec node node_modules/vite/bin/vite.js --config vite.config.ts --host 127.0.0.1 --port 5173 --strictPort
) &
task_frontend_pid=$!

echo "旅行工作台：http://127.0.0.1:5173"
echo "API 文档：http://127.0.0.1:8000/docs"
while kill -0 "$task_backend_pid" 2>/dev/null && kill -0 "$task_frontend_pid" 2>/dev/null; do
  sleep 1
done
exit 1
