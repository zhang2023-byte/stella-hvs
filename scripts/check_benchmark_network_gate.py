#!/usr/bin/env python3
"""Evaluate the gold-blind overnight dev10 network gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.network_gate import evaluate_network_gate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = evaluate_network_gate(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
