#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
# One worker owns boundary collection and the SQLite ledger. Never start the trading engine here.
exec .venv/bin/uvicorn bio_arena.audience:app --host "${BIO_AUDIENCE_HOST:-127.0.0.1}" --port "${BIO_AUDIENCE_PORT:-8143}" --workers 1 --no-proxy-headers --no-access-log
