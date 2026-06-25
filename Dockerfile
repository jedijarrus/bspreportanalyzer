FROM python:3.13-slim

WORKDIR /app

# gosu für sauberen Privileg-Wechsel im Entrypoint
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

# Abhängigkeiten zuerst (Layer-Caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode
COPY app/ ./app/
COPY web/ ./web/
COPY docker/entrypoint.sh /entrypoint.sh

# Laufzeit-Daten liegen im Volume /data (DB, Uploads) — nie im Image
ENV BSP_DATA_DIR=/data \
    BSP_DB_PATH=/data/app.db \
    BSP_UPLOAD_DIR=/data/uploads
VOLUME ["/data"]

# Non-root-Benutzer anlegen. Der Container startet als root (für chown des
# Volumes im Entrypoint) und droppt dann via gosu auf appuser.
RUN useradd --create-home --uid 10001 appuser \
    && chmod +x /entrypoint.sh \
    && mkdir -p /data && chown -R appuser:appuser /app

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8080"]
