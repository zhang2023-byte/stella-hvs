#!/usr/bin/env python3
"""Repair ADS API metadata and paper-level HVS bibcodes for archived literature."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import requests

WORKSPACE = Path(__file__).resolve().parents[1]

from stella.lit.ads_repair import repair_ads_metadata  # noqa: E402
from stella.lit.env import env_value, load_env_files  # noqa: E402
from stella.lit.literature_assets import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT  # noqa: E402


ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected True or False")


def parse_arxiv_ids(value: str) -> list[str]:
    ids: list[str] = []
    for item in (part.strip() for part in value.split(",")):
        if not item:
            continue
        if not ARXIV_ID_RE.fullmatch(item):
            raise argparse.ArgumentTypeError(
                f"--arxiv-id values must look like 2401.10635 or 2401.10635v1; got {item!r}"
            )
        ids.append(item)
    if not ids:
        raise argparse.ArgumentTypeError("--arxiv-id cannot be empty")
    return ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Retry ADS API metadata and fill paper.bibcode in literature_hvs_candidates.json."
    )
    parser.add_argument("--arxiv-id", type=parse_arxiv_ids, default=None, metavar="ID[,ID...]", help="Select specific archived arXiv IDs.")
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature", help="Archived literature root. Default: literature")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Single request timeout in seconds. Default: 60")
    parser.add_argument("--dry-run", type=parse_bool, default=False, metavar="True|False", help="Report actions without writing files. Default: False")
    parser.add_argument("--force", type=parse_bool, default=False, metavar="True|False", help="Refresh ADS API metadata even when current files look complete. Default: False")
    parser.add_argument("--ads-token", default=None, help="ADS API token. Defaults to ADS_API_TOKEN or ADS_TOKEN from env files.")
    return parser


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
    return session


def main() -> int:
    args = build_parser().parse_args()
    if args.timeout < 1:
        raise SystemExit("--timeout must be at least 1")
    load_env_files(WORKSPACE)
    literature_dir = args.literature_dir.expanduser()
    ads_token = args.ads_token if args.ads_token is not None else env_value("ADS_API_TOKEN", "ADS_TOKEN")
    payload = repair_ads_metadata(
        literature_dir=literature_dir,
        session=build_session(),
        timeout=args.timeout,
        arxiv_ids=args.arxiv_id,
        dry_run=args.dry_run,
        ads_token=ads_token,
        force=args.force,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
