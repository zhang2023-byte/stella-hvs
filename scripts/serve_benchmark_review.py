#!/usr/bin/env python3
"""Serve the benchmark review site and persist expert verdicts via POST.

GET serves files under benchmark/ only (review site, alignment, adjudication).
POST /api/verdicts/<arxiv_id> atomically rewrites the adjudication JSON,
stamping the expert identity and per-item decision timestamps server-side.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pydantic import ValidationError  # noqa: E402

from stella_benchmark.adjudication import atomic_save_adjudication, load_adjudication  # noqa: E402
from stella_benchmark.models import (  # noqa: E402
    BENCHMARK_ADJUDICATION_SCHEMA_VERSION,
    AdjudicationItem,
    AdjudicationRecord,
    ExpertIdentity,
    PaperStatusVerdict,
)
from stella_benchmark.paths import adjudication_path, alignment_path, benchmark_root  # noqa: E402

MAX_BODY_BYTES = 16 * 1024 * 1024


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stamp_decided_at(
    items: list[dict], previous: AdjudicationRecord | None
) -> list[AdjudicationItem]:
    """Keep decided_at for unchanged items; stamp changed/new items with now."""
    previous_items = {item.item_id: item for item in previous.items} if previous else {}
    stamped: list[AdjudicationItem] = []
    for raw in items:
        payload = dict(raw)
        payload.pop("decided_at", None)
        item = AdjudicationItem.model_validate({**payload, "decided_at": ""})
        earlier = previous_items.get(item.item_id)
        if earlier is not None and earlier.model_dump(exclude={"decided_at"}) == item.model_dump(
            exclude={"decided_at"}
        ):
            item = item.model_copy(update={"decided_at": earlier.decided_at})
        else:
            item = item.model_copy(update={"decided_at": _now()})
        stamped.append(item)
    stamped.sort(key=lambda entry: entry.item_id)
    return stamped


def build_adjudication(
    arxiv_id: str,
    body: dict,
    *,
    expert: ExpertIdentity,
    alignment_digest: str,
    previous: AdjudicationRecord | None,
) -> AdjudicationRecord:
    status_verdict = None
    raw_status = body.get("paper_status_verdict")
    if raw_status is not None:
        payload = dict(raw_status)
        payload.pop("decided_at", None)
        status_verdict = PaperStatusVerdict.model_validate({**payload, "decided_at": ""})
        earlier = previous.paper_status_verdict if previous else None
        if earlier is not None and earlier.model_dump(exclude={"decided_at"}) == status_verdict.model_dump(
            exclude={"decided_at"}
        ):
            status_verdict = status_verdict.model_copy(update={"decided_at": earlier.decided_at})
        else:
            status_verdict = status_verdict.model_copy(update={"decided_at": _now()})
    return AdjudicationRecord(
        schema_version=BENCHMARK_ADJUDICATION_SCHEMA_VERSION,
        arxiv_id=arxiv_id,
        alignment_digest=alignment_digest,
        expert=expert,
        updated_at=_now(),
        paper_status_verdict=status_verdict,
        items=_stamp_decided_at(body.get("items") or [], previous),
    )


class ReviewHandler(SimpleHTTPRequestHandler):
    """Static files from benchmark/ plus the verdict API."""

    def __init__(self, *args, root: Path, expert: ExpertIdentity, **kwargs) -> None:
        self.root = root
        self.expert = expert
        super().__init__(*args, directory=str(root), **kwargs)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/review/index.html")
            self.end_headers()
            return
        if self.path == "/api/session":
            self._send_json(200, {"expert": json.loads(self.expert.model_dump_json())})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        prefix = "/api/verdicts/"
        if not self.path.startswith(prefix):
            self._send_json(404, {"error": "unknown endpoint"})
            return
        arxiv_id = self.path[len(prefix) :].strip("/")
        if not arxiv_id or "/" in arxiv_id or arxiv_id.startswith("."):
            self._send_json(400, {"error": "invalid arxiv id"})
            return

        align_file = alignment_path(self.root, arxiv_id)
        if not align_file.exists():
            self._send_json(404, {"error": f"no alignment for {arxiv_id}"})
            return
        on_disk_digest = str(
            json.loads(align_file.read_text(encoding="utf-8")).get("alignment_digest") or ""
        )

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(400, {"error": "missing or oversized request body"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": f"invalid JSON body: {exc}"})
            return

        client_digest = str(body.get("alignment_digest") or "")
        if client_digest != on_disk_digest:
            self._send_json(
                409,
                {
                    "error": "alignment digest mismatch; rebuild the review site and reload",
                    "on_disk": on_disk_digest,
                },
            )
            return

        target = adjudication_path(self.root, arxiv_id)
        try:
            record = build_adjudication(
                arxiv_id,
                body,
                expert=self.expert,
                alignment_digest=on_disk_digest,
                previous=load_adjudication(target),
            )
        except (ValidationError, ValueError) as exc:
            self._send_json(400, {"error": f"invalid verdicts: {exc}"})
            return
        atomic_save_adjudication(target, record)
        self._send_json(
            200,
            {
                "saved": True,
                "path": str(target.relative_to(self.root)),
                "items": len(record.items),
            },
        )

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - http.server API
        sys.stderr.write(f"{self.address_string()} - {format % args}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the benchmark review site.")
    parser.add_argument("--expert-id", required=True, help="Expert identifier stamped on verdicts.")
    parser.add_argument("--expert-name", default="", help="Optional display name.")
    parser.add_argument("--benchmark-root", type=Path, default=benchmark_root(WORKSPACE))
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind. Default: 127.0.0.1 (localhost only).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.benchmark_root.expanduser().resolve()
    if not (root / "review" / "index.html").exists():
        raise SystemExit(
            f"review site not built under {root}; run scripts/build_benchmark_review.py first"
        )
    expert = ExpertIdentity(id=args.expert_id, name=args.expert_name)
    handler = partial(ReviewHandler, root=root, expert=expert)
    with ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print(f"Serving benchmark review at http://{args.host}:{args.port}/review/index.html")
        print(f"Verdicts are saved as expert {expert.id!r} under {root / 'adjudication'}")
        print("Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
