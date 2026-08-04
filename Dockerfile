FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml README.md ./

# Dependencies install in their own layer, keyed only on pyproject.toml, so a
# backend code change doesn't trigger a full pandas/numpy/anthropic rebuild.
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/reqs.txt \
    && pip install --no-cache-dir --prefix=/install -r /tmp/reqs.txt

COPY backend ./backend
RUN pip install --no-cache-dir --prefix=/install --no-deps .

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

COPY --from=builder /install /usr/local

RUN useradd --no-create-home --uid 1000 appuser \
    && chown -R appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request, os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8080\")}/v1/health')" || exit 1

# Cloud Run injects PORT; shell form lets the env var expand.
CMD exec uvicorn volatility_explainer.api.app:app --host 0.0.0.0 --port "$PORT"
