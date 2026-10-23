FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home --uid 10001 app
COPY --chown=app:app . .
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/health', timeout=2)" || exit 1

# Serve only — the model is trained separately (scripts/seed_warehouse.py +
# models/train.py) against the real warehouse backend and either baked into
# the image via `models/saved_model/` or mounted in at `docker run` time.
# Required at runtime: API_KEY (auth) and CORS_ALLOW_ORIGINS (browser clients).
# Put TLS in front (reverse proxy / load balancer); do not expose 8080 directly.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
