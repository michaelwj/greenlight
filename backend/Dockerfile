# Build context is the repo root (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp uses deno as its JavaScript runtime for YouTube extraction.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

WORKDIR /app

COPY backend/pyproject.toml backend/README.md /app/
COPY backend/app /app/app
COPY backend/tests /app/tests
COPY backend/alembic /app/alembic
COPY backend/alembic.ini /app/alembic.ini
COPY backend/scripts /app/scripts
COPY kid-web /app/web/kid
COPY parent-web /app/web/parent

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .[dev]

ENV KID_WEB_DIR=/app/web/kid
ENV PARENT_WEB_DIR=/app/web/parent

EXPOSE 8000

# Migrations run before the API starts so a fresh database is always usable;
# the retry loop covers postgres still booting on first compose up.
CMD ["sh", "-c", "until alembic upgrade head; do echo 'migration failed (db booting?), retrying in 3s'; sleep 3; done && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
