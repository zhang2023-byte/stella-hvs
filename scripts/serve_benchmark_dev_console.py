#!/usr/bin/env python3
"""Serve the local Stella benchmark development mission control."""

from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from stella.benchmark.dev_console import DEFAULT_PORT, DevConsoleController, create_server
from stella.lit.env import load_env_files


WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve Stella benchmark dev mission control.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Loopback port. Default: {DEFAULT_PORT}.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    return parser


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    controller = DevConsoleController(WORKSPACE)
    server = create_server("127.0.0.1", args.port, controller)
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"Serving Stella benchmark dev mission control at {url}")
    print("Press Ctrl-C to stop the console. Running benchmark processes are managed separately.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping console server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
