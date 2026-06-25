#!/bin/sh
# Git-Hooks aktivieren: zeigt git auf das versionierte .githooks-Verzeichnis.
# Einmalig nach dem Klonen ausfuehren:  sh scripts/install-hooks.sh
set -e
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit .githooks/pre-push 2>/dev/null || true
echo "Hooks aktiv (core.hooksPath=.githooks). pre-commit + pre-push scannen jetzt auf PII."
