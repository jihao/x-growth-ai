# 服务端部署（在服务器上构建镜像）

## 1. 上传并解压

```bash
cd /www/wwwroot
mkdir -p x-growth-ai
tar -xzf x-growth-ai-src-XXXX.tar.gz -C x-growth-ai
cd x-growth-ai
mkdir -p database data reports
```

## 2. （可选）同步行情库

库文件不在源码包内，需单独上传：

```bash
# 本地执行
rsync -avP database/astocks_qfq.db user@server:/www/wwwroot/x-growth-ai/database/
```

没有库也能启动，但行情相关接口会不可用。

## 3. 构建并启动

```bash
docker compose up -d --build
docker compose ps
curl -sS http://127.0.0.1:8080/api/health
```

## 4. 更新

改后端代码后重新打包上传，或在服务器上替换 `backend/` 后：

```bash
docker compose up -d --build backend
```

只更新前端静态资源时，替换 `frontend/dist` 后：

```bash
docker compose restart frontend
```

## 包内包含

- `docker-compose.yml` / `.dockerignore`
- `backend/`（Dockerfile、源码、uv.lock、config）
- `frontend/dist/`（本地已 build 的静态文件）
- `deploy/nginx.conf`

不含：`database/*.db`、`node_modules`、`.venv`、源码前端工程文件
