#!/usr/bin/env python3
"""Calculate object-level HVS dynamics and write them into catalog object JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_dyn import DEFAULT_MCMC_SAMPLES, calculate_catalog_dynamics  # noqa: E402
from high_velocity_dyn.dynamics import EXTERNAL_CACHE_MODES, parse_bool  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calculate Galactocentric HVS dynamics for catalog/candidates object JSON files."
    )
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=WORKSPACE / "catalog",
        help="Object-level catalog directory. Default: catalog/",
    )
    parser.add_argument(
        "--object-id",
        default="",
        help="Only process one catalog/candidates/<object-id>.json object. Default: all objects.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_MCMC_SAMPLES,
        help=f"MCMC posterior samples per object. Default: {DEFAULT_MCMC_SAMPLES}.",
    )
    parser.add_argument("--seed", type=int, default=None, help="Optional random seed for reproducible MCMC sampling.")
    parser.add_argument(
        "--write",
        type=parse_bool,
        default=False,
        metavar="True|False",
        help="Write dynamics into object JSON files. Default: False.",
    )
    parser.add_argument(
        "--dry-run",
        type=parse_bool,
        default=False,
        metavar="True|False",
        help="Calculate and report planned writes without modifying files. Default: False.",
    )
    parser.add_argument(
        "--fail-on-network-error",
        action="store_true",
        help="Fail immediately on Gaia DR3 query errors in refresh mode instead of recording skipped dynamics.",
    )
    parser.add_argument(
        "--external-cache-mode",
        choices=EXTERNAL_CACHE_MODES,
        default="required",
        help="Use cached external_enrichment data only (required) or force Gaia DR3 refresh queries (refresh). Default: required.",
    )
    parser.add_argument(
        "--refresh-external",
        action="store_true",
        help="Shortcut for --external-cache-mode refresh.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()
        external_cache_mode = "refresh" if args.refresh_external else args.external_cache_mode
        result = calculate_catalog_dynamics(
            args.catalog_dir.expanduser(),
            object_id=args.object_id,
            samples=args.samples,
            seed=args.seed,
            write=args.write,
            dry_run=args.dry_run,
            fail_on_network_error=args.fail_on_network_error,
            external_cache_mode=external_cache_mode,
        )
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    skipped_inputs = result.get("skipped_inputs") or []
    return 1 if skipped_inputs else 0


if __name__ == "__main__":
    raise SystemExit(main())
