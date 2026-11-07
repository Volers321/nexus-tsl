FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 NEXUS_DB_PATH=/data/nexus.db

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && useradd -m app \
 && mkdir -p /data && chown app:app /data
USER app
VOLUME ["/data"]

EXPOSE 8000
# Platformy chmurowe (Render, Railway, Fly) podają port w zmiennej PORT.
CMD ["sh", "-c", "uvicorn nexus_tsl.api:app --host 0.0.0.0 --port ${PORT}"]
