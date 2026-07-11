#!/usr/bin/env python3
"""Serve the local expert gold-annotation form."""

from __future__ import annotations

import argparse
import os
import webbrowser
from pathlib import Path

from stella.benchmark.gold_form import GoldFormConfig, create_server
from stella.benchmark.paths import campaign_paths
from stella.lit.env import load_env_files

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = campaign_paths(WORKSPACE).sampling_manifest
GOLD_DIR_ENV = "STELLA_GOLD_DIR"


def default_annotator() -> str:
    return os.environ.get("USER", "").strip()


def default_gold_dir() -> Path | None:
    value = os.environ.get(GOLD_DIR_ENV, "").strip()
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve a local browser form for expert gold annotations."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host. Default: 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Bind port. Default: 8765.",
    )
    parser.add_argument(
        "--arxiv-id",
        default="",
        help="Optional paper to preselect, e.g. 1902.05061.",
    )
    parser.add_argument(
        "--annotator",
        default=default_annotator(),
        help="Annotator handle. Default: current USER.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Sampling manifest path.",
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=default_gold_dir(),
        help=f"External private gold annotation root. Default: ${GOLD_DIR_ENV}.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the browser automatically.",
    )
    return parser


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    if args.gold_dir is None:
        # The parser default was evaluated before .env loading when the module
        # was imported by tests; re-resolve from the freshly loaded env.
        args.gold_dir = default_gold_dir()
    if args.gold_dir is None:
        raise SystemExit(
            f"Set {GOLD_DIR_ENV} or pass --gold-dir to the external private "
            "gold annotation root."
        )
    config = GoldFormConfig(
        workspace=WORKSPACE,
        manifest_path=args.manifest,
        gold_dir=args.gold_dir,
        arxiv_id=args.arxiv_id,
        annotator=args.annotator,
    )
    server = create_server(args.host, args.port, config)
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"Serving Stella gold annotation form at {url}")
    print("Press Ctrl-C to stop.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
