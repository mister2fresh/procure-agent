# API service: FastAPI + LangGraph + Anthropic SDK, managed by uv.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

# Cache the deps layer separately from project source.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Source + assets needed at runtime.
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/
COPY data/ ./data/

# Install the project itself into the cached venv.
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD uv run --no-dev uvicorn procure_agent.api:app --host 0.0.0.0 --port ${PORT:-8000}
