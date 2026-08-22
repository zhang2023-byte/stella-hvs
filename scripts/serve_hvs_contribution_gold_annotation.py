#!/usr/bin/env python3
"""Serve the pre-activation contribution gold annotation form.

The page renders the blank template and the disabled-save banner. Formal
annotation stays disabled until the expert session approves the contribution
guideline version and binds a benchmark campaign. With --allow-drafts and an
explicit --gold-dir, draft saving is possible against that directory;
drafts are annotator work state, never a formal scoring input.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from stella.benchmark.hvs_contribution_gold_form import (
    PRE_ACTIVATION_BANNER,
    ContributionGoldFormError,
    build_empty_contribution_payload,
    save_draft,
    validate_and_lint,
)

WORKSPACE = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = Path("benchmark/templates/hvs_contribution_annotation_template.yaml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve the pre-activation contribution gold annotation form.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--allow-drafts",
        action="store_true",
        help="Permit draft saving into the explicit --gold-dir (work state only).",
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=None,
        help="Explicit directory for drafts; never inferred from the environment.",
    )
    return parser


def render_form_page(workspace: Path) -> str:
    template = (workspace / TEMPLATE_PATH).read_text(encoding="utf-8")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Contribution gold annotation (pre-activation)</title></head>"
        "<body><h1>Contribution gold annotation</h1>"
        f"<p><strong>{PRE_ACTIVATION_BANNER}</strong></p>"
        "<pre>"
        + template.replace("&", "&amp;").replace("<", "&lt;")
        + "</pre></body></html>"
    )


def handle_post(body: dict, *, allow_drafts: bool, gold_dir: Path | None) -> tuple[int, dict]:
    action = body.get("action")
    if action == "save_annotation":
        return 403, {"error": PRE_ACTIVATION_BANNER}
    if action == "save_draft":
        if not allow_drafts or gold_dir is None:
            return 403, {"error": "draft saving requires --allow-drafts and --gold-dir"}
        try:
            result = save_draft(body.get("payload") or {}, gold_dir)
        except ContributionGoldFormError as exc:
            return 400, {"error": str(exc)}
        return 200, result
    if action == "validate":
        try:
            return 200, validate_and_lint(body.get("payload") or {})
        except Exception as exc:
            return 400, {"error": str(exc)}
    return 400, {"error": f"unknown action {action!r}"}


def build_handler(workspace: Path, *, allow_drafts: bool, gold_dir: Path | None):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            page = render_form_page(workspace)
            self.send_header("Content-Length", str(len(page.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8")
            body = json.loads(raw) if raw else {}
            status, payload = handle_post(
                body, allow_drafts=allow_drafts, gold_dir=gold_dir
            )
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args) -> None:
            pass

    return _Handler


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.allow_drafts and args.gold_dir is None:
        print("--allow-drafts requires --gold-dir", file=sys.stderr)
        return 2
    handler = build_handler(
        WORKSPACE, allow_drafts=args.allow_drafts, gold_dir=args.gold_dir
    )
    server = HTTPServer(("127.0.0.1", args.port), handler)
    print(f"serving pre-activation contribution form on 127.0.0.1:{args.port}")
    print(PRE_ACTIVATION_BANNER)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
