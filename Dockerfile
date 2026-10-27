FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_APP=wsgi:app

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code only (tests, venv, .env and data are excluded via .dockerignore).
COPY app ./app
COPY wsgi.py ./wsgi.py
COPY docker-entrypoint.sh ./docker-entrypoint.sh

# Non-root runtime user; /data is owned by it so a fresh named volume inherits
# the ownership when Docker initializes the volume.
RUN chmod +x docker-entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

USER appuser
EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
