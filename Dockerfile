FROM python:3.13-slim

WORKDIR /app

# Abhängigkeiten zuerst (Layer-Caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode
COPY app/ ./app/
COPY web/ ./web/

# Laufzeit-Daten liegen im Volume /data (DB, Uploads) — nie im Image
ENV BSP_DATA_DIR=/data \
    BSP_DB_PATH=/data/app.db \
    BSP_UPLOAD_DIR=/data/uploads
VOLUME ["/data"]

# Non-root: eigener Benutzer, dem /data und /app gehören
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data && chown -R appuser:appuser /data /app
USER appuser

EXPOSE 8080
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8080"]
