# Dev-oriented image: the source is bind-mounted in by docker-compose, so this
# build only bakes the virtualenv (see the anonymous /app/.venv volume in
# docker-compose.yml for why the bind mount does not hide it).
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# The uv cache and the sync target sit on different filesystems here, so uv
# cannot hardlink and warns on every sync. Copying is the fallback anyway.
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY . .

# Migrate, then serve. One process owns the schema because SQLite allows one
# writer at a time (ADR-0002), so there is no separate migrate service.
# --reload-dir keeps the watcher off the rest of the bind mount: pytest drops
# 0o700 basetemp directories in there that the watcher cannot traverse.
CMD ["sh", "-c", "uv run python -m app.migrate && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app"]
