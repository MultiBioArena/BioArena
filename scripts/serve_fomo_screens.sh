#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export BIO_FOMO_SCREENS_CONFIG="${BIO_FOMO_SCREENS_CONFIG:-$PWD/.private/fomo-screens.json}"
exec .venv/bin/uvicorn bio_arena.fomo_screens:app --host "${BIO_FOMO_SCREENS_HOST:-127.0.0.1}" --port "${BIO_FOMO_SCREENS_PORT:-8144}" --no-access-log
