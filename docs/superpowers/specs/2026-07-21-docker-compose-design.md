# Docker Compose 部署设计

日期：2026-07-21  
状态：待实现

## 目标

将 x-growth-ai 的前端与后端打包为 Docker Compose 服务：

- 前端使用本地 `npm run build` 产出的 `frontend/dist`，容器内不构建前端
- 行情数据库与业务数据通过 volume bind mount 进入后端容器
- 对外单入口：nginx 托管静态资源并反代 `/api/`

## 架构

```text
浏览器 → localhost:8080 (frontend / nginx:alpine)
           ├─ /*        → ./frontend/dist（只读挂载）
           └─ /api/*    → http://backend:8000 (uvicorn FastAPI)

backend 工作目录 = /app（等价仓库根）
挂载：
  ./database  → /app/database
  ./data      → /app/data
  ./reports   → /app/reports
```

## 新增文件

| 路径 | 作用 |
| --- | --- |
| `docker-compose.yml` | 编排 `frontend` + `backend` |
| `backend/Dockerfile` | 构建并启动 API |
| `.dockerignore` | 排除大文件与无关目录，减小构建上下文 |
| `deploy/nginx.conf` | SPA 静态托管 + `/api` 反代 |

## 服务设计

### backend

- 基础镜像：`python:3.12-slim`
- 包管理：容器内安装 `uv`，按 `backend/pyproject.toml` / `uv.lock` 安装依赖
- 构建上下文：仓库根目录
- 工作目录：`/app`
- 代码：镜像内 `COPY backend/`（改后端代码需重建镜像）
- 环境变量：`PYTHONPATH=/app/backend/src`
- 启动命令：`uvicorn backend.api.app:app --host 0.0.0.0 --port 8000`
- 健康检查：`GET /api/health`
- 端口：仅 Docker 内网 `8000`，默认不映射到宿主机
- 卷：
  - `./database:/app/database`
  - `./data:/app/data`
  - `./reports:/app/reports`

路径约定：后端通过 `find_repo_root()` + `database/astocks_qfq.db` 定位 SQLite。  
因此容器 `cwd` 必须是仓库根语义（`/app`），而不是 `backend/` 子目录。

### frontend（nginx）

- 镜像：`nginx:alpine`（无需自建前端镜像）
- 端口：`8080:80`
- 卷：
  - `./frontend/dist:/usr/share/nginx/html:ro`
  - `./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro`
- 依赖：`depends_on` backend，并等待 backend healthcheck 通过

### nginx 行为

- `try_files $uri $uri/ /index.html` 支持前端 SPA 路由
- `/api/` reverse_proxy 到 `http://backend:8000`
- 适当加大 `proxy_read_timeout`（回测 / 筛股可能较慢）
- 浏览器同源访问 `localhost:8080`，无需修改后端 CORS 白名单

## 构建与忽略规则

`.dockerignore` 至少排除：

- `.git`
- `database/*.db`、`database/*.log`
- `data/`、`reports/`
- `frontend/node_modules/`、`frontend/dist/`
- `.skills/`、`参考资料/`、`.pnpm-store/`

避免把约 1.8GB 的 `astocks_qfq.db` 打进构建上下文。

## 使用步骤

```bash
# 1. 本地构建前端
cd frontend && npm run build && cd ..

# 2. 启动
docker compose up -d --build

# 3. 访问
open http://localhost:8080

# 4. 更新前端静态资源（无需重建镜像）
cd frontend && npm run build
# dist 已挂载；如有缓存可：docker compose restart frontend
```

数据更新仍在宿主机执行，例如：

```bash
cd database && python update_daily.py
```

## 非目标

- 不在 Docker 内构建前端
- 不容器化 `database/update_daily.py` / baostock 下载脚本
- 不把 backend 源码做成开发热挂载（后续如需可加 override）
- 不改业务逻辑；仅在启动路径必须时做最小调整

## 验收标准

1. `frontend/dist` 存在时，`docker compose up -d --build` 成功启动两个服务
2. `http://localhost:8080` 能打开前端页面
3. `http://localhost:8080/api/health` 经 nginx 反代返回后端健康状态
4. 后端能读取挂载的 `database/astocks_qfq.db`
5. 容器重建后，`database/`、`data/`、`reports/` 宿主机数据仍在
