#!/usr/bin/env python3
"""Serve the Stella HVS catalog site (static snapshot or live data view)."""

from __future__ import annotations

import argparse
import http.server
import os
from http.server import ThreadingHTTPServer
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the Stella HVS catalog site.")
    parser.add_argument(
        "--mode",
        choices=["static", "live"],
        default="static",
        help="Which site to serve. 'static' serves catalog/html/static/. "
             "'live' serves catalog/ so the live page can reach its data. Default: static",
    )
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on. Default: 8080")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind. Default: 127.0.0.1 (localhost only). "
             "Use 0.0.0.0 to expose on the network at your own risk.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.mode == "static":
        site_dir = WORKSPACE / "catalog" / "html" / "static"
        if not site_dir.exists():
            raise FileNotFoundError(f"Static site not found: {site_dir}")
        os.chdir(site_dir)
        url = f"http://{args.host}:{args.port}/"
    else:
        live_dir = WORKSPACE / "catalog" / "html" / "live"
        if not live_dir.exists():
            raise FileNotFoundError(f"Live site not found: {live_dir}")
        # Serve only catalog/ so the live page (catalog-root="../..") can reach
        # its data without exposing the rest of the repository (.git, source, etc.).
        os.chdir(WORKSPACE / "catalog")
        url = f"http://{args.host}:{args.port}/html/live/"

    handler = http.server.SimpleHTTPRequestHandler
    with ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print(f"Serving {args.mode} site at {url}")
        print(f"Root directory: {os.getcwd()}")
        print("Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
