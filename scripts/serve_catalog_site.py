#!/usr/bin/env python3
"""Serve the Stella HVS catalog site (static snapshot or live data view)."""

from __future__ import annotations

import argparse
import http.server
import os
import socketserver
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Stella HVS catalog site.")
    parser.add_argument(
        "--mode",
        choices=["static", "live"],
        default="static",
        help="Which site to serve. 'static' serves catalog/html/static/. "
             "'live' serves from the repo root so catalog data is reachable. Default: static",
    )
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on. Default: 8080")
    args = parser.parse_args()

    if args.mode == "static":
        site_dir = WORKSPACE / "catalog" / "html" / "static"
        if not site_dir.exists():
            raise FileNotFoundError(f"Static site not found: {site_dir}")
        os.chdir(site_dir)
        url = f"http://localhost:{args.port}/"
    else:
        live_dir = WORKSPACE / "catalog" / "html" / "live"
        if not live_dir.exists():
            raise FileNotFoundError(f"Live site not found: {live_dir}")
        os.chdir(WORKSPACE)
        url = f"http://localhost:{args.port}/catalog/html/live/"

    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", args.port), handler) as httpd:
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
