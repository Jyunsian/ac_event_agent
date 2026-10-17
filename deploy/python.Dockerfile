FROM ghcr.io/astral-sh/uv:0.10.4 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
COPY server ./server
COPY contracts ./contracts
COPY migrations ./migrations
COPY alembic.ini ./
RUN useradd --uid 10001 --create-home app && mkdir /work && chown app:app /work
USER 10001:10001
CMD ["uvicorn", "server.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
