#!/usr/bin/env python3
"""Serve the local contribution gold migration review form."""

from __future__ import annotations

import argparse
import html
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from stella.benchmark.hvs_contribution_gold_form import (
    CONTRIBUTION_GOLD_NOTICE,
    ContributionGoldFormError,
    build_empty_contribution_payload,
    load_draft,
    save_expert_annotation,
    save_draft,
    validate_and_lint,
)
from stella.benchmark.gold_form import guideline_version
from stella.benchmark.paths import require_external_path

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_WORK_DIR = Path("/tmp/stella-contribution-gold-migration")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve the contribution gold migration review form.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--arxiv-id", required=True)
    parser.add_argument("--annotator", required=True)
    parser.add_argument(
        "--allow-drafts",
        action="store_true",
        help="Permit temporary draft saving into --work-dir.",
    )
    parser.add_argument(
        "--allow-final-save",
        action="store_true",
        help="Permit an explicitly expert-approved final YAML/JSON save.",
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=None,
        help="External private gold root for final approved annotations.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help="Temporary migration work root. Approved paper artifacts are deleted.",
    )
    return parser


def render_form_page(
    workspace: Path,
    *,
    payload: dict | None = None,
    final_save_enabled: bool = False,
) -> str:
    del workspace
    initial = json.dumps(payload or {}, ensure_ascii=False, indent=2)
    final_disabled = "" if final_save_enabled else " disabled"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Contribution gold review</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;max-width:80rem}}textarea{{width:100%;height:65vh;font-family:ui-monospace,monospace}}button{{margin:.75rem .5rem .75rem 0;padding:.55rem .9rem}}#result{{white-space:pre-wrap}}</style></head>
<body><h1>Contribution gold migration review</h1>
<p><strong>{html.escape(CONTRIBUTION_GOLD_NOTICE)}</strong></p>
<p>The expert reviews the complete paper-level draft. Final save means the expert approves the annotation as a whole; it does not claim item-by-item manual extraction.</p>
<textarea id="payload">{html.escape(initial)}</textarea><br>
<button onclick="submitAction('validate')">Validate</button>
<button onclick="submitAction('save_draft')">Save temporary draft</button>
<button{final_disabled} onclick="submitAction('save_annotation', true)">Approve paper and save final gold</button>
<div id="result"></div>
<script>
async function submitAction(action, approved=false) {{
  const result = document.getElementById('result');
  try {{
    const payload = JSON.parse(document.getElementById('payload').value);
    const response = await fetch('/', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{action, payload, expert_approved:approved}})}});
    const body = await response.json();
    result.textContent = JSON.stringify(body, null, 2);
  }} catch (error) {{ result.textContent = String(error); }}
}}
</script></body></html>"""


def handle_post(
    body: dict,
    *,
    allow_drafts: bool,
    allow_final_save: bool,
    gold_dir: Path | None,
    work_dir: Path,
    expected_arxiv_id: str = "",
    expected_annotator: str = "",
) -> tuple[int, dict]:
    action = body.get("action")
    if action == "save_annotation":
        if not allow_final_save or gold_dir is None:
            return 403, {"error": "final saving requires --allow-final-save and --gold-dir"}
        try:
            return 200, save_expert_annotation(
                body.get("payload") or {},
                gold_dir,
                work_dir=work_dir,
                expected_arxiv_id=expected_arxiv_id,
                expected_annotator=expected_annotator,
                expert_approved=body.get("expert_approved") is True,
            )
        except Exception as exc:
            return 400, {"error": str(exc)}
    if action == "save_draft":
        if not allow_drafts:
            return 403, {"error": "draft saving requires --allow-drafts"}
        try:
            result = save_draft(body.get("payload") or {}, work_dir)
        except ContributionGoldFormError as exc:
            return 400, {"error": str(exc)}
        return 200, result
    if action == "validate":
        try:
            return 200, validate_and_lint(body.get("payload") or {})
        except Exception as exc:
            return 400, {"error": str(exc)}
    return 400, {"error": f"unknown action {action!r}"}


def build_handler(
    workspace: Path,
    *,
    allow_drafts: bool,
    allow_final_save: bool,
    gold_dir: Path | None,
    work_dir: Path,
    arxiv_id: str,
    annotator: str,
    initial_payload: dict,
):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            page = render_form_page(
                workspace,
                payload=initial_payload,
                final_save_enabled=allow_final_save and gold_dir is not None,
            )
            self.send_header("Content-Length", str(len(page.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8")
            body = json.loads(raw) if raw else {}
            status, payload = handle_post(
                body,
                allow_drafts=allow_drafts,
                allow_final_save=allow_final_save,
                gold_dir=gold_dir,
                work_dir=work_dir,
                expected_arxiv_id=arxiv_id,
                expected_annotator=annotator,
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
    if args.allow_final_save and args.gold_dir is None:
        print("--allow-final-save requires --gold-dir", file=sys.stderr)
        return 2
    args.work_dir = require_external_path(
        args.work_dir, workspace=WORKSPACE, label="migration work directory"
    )
    if args.gold_dir is not None:
        args.gold_dir = require_external_path(
            args.gold_dir, workspace=WORKSPACE, label="gold directory"
        )
    try:
        initial_payload = load_draft(args.work_dir, args.arxiv_id, args.annotator)
    except ContributionGoldFormError:
        initial_payload = build_empty_contribution_payload(
            arxiv_id=args.arxiv_id,
            annotator=args.annotator,
            guideline_version=guideline_version(WORKSPACE),
        )
    handler = build_handler(
        WORKSPACE,
        allow_drafts=args.allow_drafts,
        allow_final_save=args.allow_final_save,
        gold_dir=args.gold_dir,
        work_dir=args.work_dir,
        arxiv_id=args.arxiv_id,
        annotator=args.annotator,
        initial_payload=initial_payload,
    )
    server = HTTPServer(("127.0.0.1", args.port), handler)
    print(f"serving contribution gold review form on 127.0.0.1:{args.port}")
    print(CONTRIBUTION_GOLD_NOTICE)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
