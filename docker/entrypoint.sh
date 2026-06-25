#!/bin/sh
set -e

# Das Volume /data wird zur Laufzeit gemountet und gehört bei Bind-Mounts
# zunächst root. Eigentümer auf den App-Benutzer setzen, damit der non-root
# Prozess Datenbank, Uploads und secret.key schreiben kann.
mkdir -p "${BSP_UPLOAD_DIR:-/data/uploads}"
chown -R appuser:appuser /data 2>/dev/null || true

# Privilegien ablegen: der Server läuft als non-root appuser.
exec gosu appuser "$@"
