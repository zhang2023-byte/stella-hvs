#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

conda run -n stella-env python "$ROOT_DIR/scripts/fetch_high_velocity_lit.py" \
  --from 2025 \
  --to 2026 \
  "$@"
