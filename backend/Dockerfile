FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY pyproject.toml ./
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY app ./app

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && mkdir -p /app/uploads \
    && chown -R appuser:appuser /app

USER appuser

ENV PORT=8080
EXPOSE 8080

# Cloud Run supplies PORT. Override this command for a long-running worker
# runtime with the queue list documented in docs/deployment.md.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
