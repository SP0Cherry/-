FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code only: .env and other secrets are excluded via .dockerignore and are
# injected at runtime by Docker Compose.
COPY server.py mcp_tools.py ./

RUN useradd --create-home --uid 10002 mcpuser \
    && chown -R mcpuser:mcpuser /app

USER mcpuser
EXPOSE 8090

CMD ["gunicorn", "--bind", "0.0.0.0:8090", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "server:app"]
