# Docker Compose 部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Docker Compose 单入口部署前端静态资源 + FastAPI 后端，数据库与业务数据通过 bind mount 注入。

**Architecture:** `frontend` 使用 `nginx:alpine` 挂载本地 `frontend/dist` 并反代 `/api/`；`backend` 自建镜像运行 uvicorn；`./database`、`./data`、`./reports` bind mount 到容器 `/app` 下对应路径。

**Tech Stack:** Docker Compose、nginx:alpine、python:3.12-slim、uv、uvicorn、FastAPI

## Global Constraints

- 前端不在 Docker 内构建，只挂载本地 `frontend/dist`
- 对外单入口：`localhost:8080`
- 后端工作目录必须是仓库根语义 `/app`（`find_repo_root()` 依赖 cwd）
- 不容器化 database 更新脚本
- 不改业务逻辑（除非路径启动必须）
- 未经用户明确要求不创建 git commit

---

## File Map

| 文件 | 职责 |
| --- | --- |
| `.dockerignore` | 缩小构建上下文，排除 db / node_modules / data 等 |
| `backend/Dockerfile` | 安装依赖并启动 API |
| `deploy/nginx.conf` | SPA + `/api` 反代 |
| `docker-compose.yml` | 编排两服务与 volume / healthcheck |

---

### Task 1: `.dockerignore` + `backend/Dockerfile`

**Files:**
- Create: `.dockerignore`
- Create: `backend/Dockerfile`

**Interfaces:**
- Consumes: `backend/pyproject.toml`、`backend/uv.lock`、`backend/src/`、`backend/config/`
- Produces: 可构建镜像；容器内 `WORKDIR=/app`，`PYTHONPATH=/app/backend/src`，监听 `8000`

- [x] **Step 1: 创建根目录 `.dockerignore`**

```gitignore
.git
.pnpm-store
.skills
参考资料
doc
docs
miaoxiang
data
reports
database/*.db
database/*.log
frontend/node_modules
frontend/dist
frontend/.umi
backend/.venv
backend/**/__pycache__
**/__pycache__
**/*.pyc
.DS_Store
```

- [x] **Step 2: 创建 `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libfreetype6 \
        libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./backend/
WORKDIR /app/backend
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/backend/.venv/bin:$PATH"
ENV PYTHONPATH=/app/backend/src
WORKDIR /app

EXPOSE 8000
CMD ["uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

说明：
- `find_repo_root()` 在 cwd=`/app` 时返回 `/app`，从而定位 `/app/database/astocks_qfq.db`
- `backend/config/` 随 `COPY backend/` 进入镜像（策略/自选股配置需要）
- matplotlib 运行时依赖 `libfreetype6` / `libpng16-16`

- [x] **Step 3: 验证 Dockerfile 语法可读且路径正确**

Run: `test -f backend/Dockerfile && test -f .dockerignore && grep -q 'WORKDIR /app' backend/Dockerfile`
Expected: exit code 0

---

### Task 2: `deploy/nginx.conf` + `docker-compose.yml`

**Files:**
- Create: `deploy/nginx.conf`
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: Task 1 的 `backend/Dockerfile`；本地 `frontend/dist`；`deploy/nginx.conf`
- Produces: `docker compose up` 可启动；宿主机 `8080` → nginx；`/api/` → `backend:8000`

- [x] **Step 1: 创建 `deploy/nginx.conf`**

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    client_max_body_size 20m;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [x] **Step 2: 创建 `docker-compose.yml`**

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    working_dir: /app
    volumes:
      - ./database:/app/database
      - ./data:/app/data
      - ./reports:/app/reports
    expose:
      - "8000"
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)",
        ]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 30s
    restart: unless-stopped

  frontend:
    image: nginx:alpine
    ports:
      - "8080:80"
    volumes:
      - ./frontend/dist:/usr/share/nginx/html:ro
      - ./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      backend:
        condition: service_healthy
    restart: unless-stopped
```

- [x] **Step 3: 校验 compose 配置**

Run: `docker compose config`
Expected: 打印解析后的配置，无 error；包含 `backend`、`frontend`，端口 `8080:80`

---

### Task 3: 端到端验证

**Files:**
- 无新增（验证既有产物）

**Interfaces:**
- Consumes: Task 1–2 全部文件；本地需有 `frontend/dist` 与 `database/astocks_qfq.db`
- Produces: 验收标准全部通过

- [x] **Step 1: 确保前端 dist 存在**

Run: `test -d frontend/dist || (cd frontend && npm run build)`
Expected: `frontend/dist/index.html` 存在

- [x] **Step 2: 构建并启动**

Run: `docker compose up -d --build`
Expected: 两个服务 `running` / `healthy`

- [x] **Step 3: 检查后端健康（经 nginx）**

Run: `curl -sS http://localhost:8080/api/health`
Expected: JSON，包含健康状态字段（非 502/连接失败）

- [x] **Step 4: 检查前端首页**

Run: `curl -sS -o /dev/null -w "%{http_code}" http://localhost:8080/`
Expected: `200`

- [x] **Step 5: 确认 volume 映射生效**

Run: `docker compose exec backend python -c "from pathlib import Path; p=Path('/app/database/astocks_qfq.db'); print(p.exists(), p.stat().st_size if p.exists() else 0)"`
Expected: `True` 且 size > 0（若宿主机已有 db）

---

## Spec Coverage Checklist

| Spec 要求 | Task |
| --- | --- |
| 单入口 nginx + `/api` 反代 | Task 2 |
| 本地 dist 挂载、容器不构建前端 | Task 2 |
| database/data/reports volume | Task 2 |
| backend Dockerfile + uv | Task 1 |
| .dockerignore 排除大文件 | Task 1 |
| 健康检查 + depends_on | Task 2 |
| 验收：health / 首页 / db 可读 | Task 3 |
