#!/usr/bin/env python3
"""Show Stella release, active benchmark campaign, and artifact schemas."""

from __future__ import annotations

import argparse
import json

from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, STELLA_RELEASE, list_schema_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = {
        "stella_release": STELLA_RELEASE,
        "active_benchmark_campaign": ACTIVE_BENCHMARK_CAMPAIGN,
        "schemas": list_schema_status(),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Stella {STELLA_RELEASE}")
        print(f"Active benchmark campaign: {ACTIVE_BENCHMARK_CAMPAIGN}")
        for schema in payload["schemas"]:
            readable = ",".join(str(item) for item in schema["readable_versions"])
            print(f"- {schema['name']}: current={schema['current_version']} readable={readable} [{schema['lifecycle']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
