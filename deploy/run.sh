#!/usr/bin/env bash
# 启动网页服务(对外可访问)。读取项目根目录 .env 中的密钥/端口。
set -euo pipefail
cd "$(dirname "$0")/.."

# 加载 .env(若存在)
if [ -f .env ]; then set -a; . ./.env; set +a; fi

exec .venv/bin/streamlit run web/app.py \
  --server.address 0.0.0.0 \
  --server.port "${PORT:-8501}" \
  --server.headless true \
  --browser.gatherUsageStats false
