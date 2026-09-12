#!/usr/bin/env bash
# Run against prepared local dependencies; no browser or market credentials required.
set -euo pipefail
BIO_CHECK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BIO_CHECK_PYTHON="${BIO_ARENA_PYTHON:-$BIO_CHECK_ROOT/.venv/bin/python}"
cd -- "$BIO_CHECK_ROOT"
case "${1:---offline}" in
  --offline) "$BIO_CHECK_PYTHON" -m pytest -q -m 'not requires_data' ;;
  --full) "$BIO_CHECK_PYTHON" -m pytest -q ;;
  *) echo 'Usage: bash scripts/check.sh [--offline|--full]' >&2; exit 2 ;;
esac
node scripts/check_desk_playback.mjs
node scripts/check_desk_motion.mjs
node scripts/check_candidate_screens.mjs
npm run build --prefix frontend
