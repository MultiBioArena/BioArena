#!/usr/bin/env bash
set -euo pipefail
BIO_ARENA_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BIO_ARENA_ROOT"
mkdir -p runs
exec 9>runs/server.lock
flock -n 9 || { echo 'Bio Arena is already running.' >&2; exit 1; }
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1
export BIO_ARENA_CONFIG="${BIO_ARENA_CONFIG:-$BIO_ARENA_ROOT/configs/arena.yaml}"
exec .venv/bin/uvicorn bio_arena.api:app --host "${BIO_ARENA_HOST:-0.0.0.0}" --port "${BIO_ARENA_PORT:-8140}" --no-access-log
