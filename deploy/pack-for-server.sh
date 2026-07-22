#!/usr/bin/env bash
# 打包服务端 docker compose 构建所需文件（不含 database）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT/deploy/export}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BUNDLE="$OUT_DIR/x-growth-ai-src-${STAMP}.tar.gz"

mkdir -p "$OUT_DIR"

if [[ ! -f "$ROOT/frontend/dist/index.html" ]]; then
  echo "==> 缺少 frontend/dist，开始本地构建..."
  (cd "$ROOT/frontend" && npm run build)
fi

echo "==> 打包到 $BUNDLE"
tar -C "$ROOT" -czf "$BUNDLE" \
  --exclude='backend/.venv' \
  --exclude='**/__pycache__' \
  --exclude='**/*.pyc' \
  --exclude='**/.DS_Store' \
  .dockerignore \
  docker-compose.yml \
  backend/Dockerfile \
  backend/pyproject.toml \
  backend/uv.lock \
  backend/src \
  backend/config \
  backend/README.md \
  frontend/dist \
  deploy/nginx.conf \
  deploy/README.server.md \
  deploy/pack-for-server.sh

ls -lh "$BUNDLE"
cat <<EOF

上传并构建:

  scp "$BUNDLE" root@server:/www/wwwroot/
  ssh root@server
  cd /www/wwwroot
  mkdir -p x-growth-ai
  tar -xzf $(basename "$BUNDLE") -C x-growth-ai
  cd x-growth-ai
  mkdir -p database data reports
  docker compose up -d --build

访问: http://<server-ip>:8080
EOF
