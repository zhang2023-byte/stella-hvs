#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

conda run -n stella-env python "$ROOT_DIR/scripts/fetch_high_velocity_lit.py" \
  --source deepxiv \
  --start-year 2025 \
  --start-month 1 \
  --end-year 2026 \
  --end-month 4 \
  --end-date 2026-04-17 \
  "$@"
