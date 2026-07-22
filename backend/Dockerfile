FROM python:3.12-slim-bookworm

# 国内构建加速：腾讯云 Debian apt + PyPI（避免拉取 ghcr.io/astral-sh/uv）
RUN sed -i 's/deb.debian.org/mirrors.cloud.tencent.com/g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's/security.debian.org/mirrors.cloud.tencent.com/g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libfreetype6 \
        libpng16-16 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        -i https://mirrors.cloud.tencent.com/pypi/simple/ \
        --trusted-host mirrors.cloud.tencent.com \
        uv

# uv sync 走腾讯云 PyPI
ENV UV_DEFAULT_INDEX=https://mirrors.cloud.tencent.com/pypi/simple/
ENV UV_NATIVE_TLS=1

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
