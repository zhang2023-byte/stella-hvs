"""Local HTTP controller for the one-action contribution Gold form.

The controller is the importable, GUI-free core of the local expert
form.  The loopback-only HTTP layer wraps ``GoldFormController.handle_request``,
while every scientific gate (PDF-only input, validate-before-save,
explicit expert approval, one JSON per paper and expert) is enforced
here. The unified CLI's gold_annotation workflow drives the same
underlying actions; this controller serves the interactive localhost
form session for one paper and expert.
"""

from __future__ import annotations

import json
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from stella.benchmark.hvs_contribution_gold_form import (
    ContributionGoldFormError,
    build_empty_contribution_payload,
    draft_path,
    load_draft,
    resolve_paper_pdf,
    save_expert_annotation,
    save_draft,
    validate_and_lint,
)

WORK_DIR_ENV = "STELLA_GOLD_WORK_DIR"
GOLD_DIR_ENV = "STELLA_GOLD_DIR"


class GoldFormController:
    """Route one expert's form requests for one paper.

    ``root`` is the repository/workspace root carrying the archived
    paper PDF; ``gold_dir`` is the private store root and ``work_dir``
    the annotator-scoped draft area (both default to the documented
    environment locations so tests can inject temporary roots).
    """

    def __init__(
        self,
        *,
        root: Path,
        gold_dir: Path | None = None,
        work_dir: Path | None = None,
        expert: str = "",
    ) -> None:
        import os

        self.root = Path(root)
        gold_value = gold_dir or os.environ.get(GOLD_DIR_ENV)
        if gold_value is None:
            raise ContributionGoldFormError(
                "STELLA_GOLD_DIR must identify the external private Gold root"
            )
        self.gold_dir = Path(gold_value)
        work_value = work_dir or os.environ.get(WORK_DIR_ENV)
        self.work_dir = Path(work_value) if work_value else self.gold_dir / "work"
        self.expert = expert

    def handle_request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        """Pure routing core: (status_code, payload) without any socket."""

        body = body or {}
        segments = [seg for seg in path.strip("/").split("/") if seg]
        if len(segments) < 2 or segments[0] != "papers":
            return 404, {"error": "unknown form route"}
        paper_id = segments[1]
        try:
            if method == "GET" and len(segments) == 1 + 1:
                return 200, self._form_document(paper_id)
            if method == "POST" and segments[2:] == ["draft"]:
                return 200, self._save_draft(paper_id, body)
            if method == "POST" and segments[2:] == ["validate"]:
                return 200, self._validate(paper_id)
            if method == "POST" and segments[2:] == ["save"]:
                return self._save(paper_id, body)
        except ContributionGoldFormError as error:
            return 422, {"error": str(error)}
        return 404, {"error": "unknown form route"}

    def _form_document(self, paper_id: str) -> dict[str, Any]:
        try:
            draft = load_draft(self.work_dir, paper_id, self.expert)
        except ContributionGoldFormError:
            draft = build_empty_contribution_payload(
                arxiv_id=paper_id, annotator=self.expert
            )
            save_draft(draft, self.work_dir)
        pdf = self._paper_pdf(paper_id)
        return {
            "paper_id": paper_id,
            "expert": self.expert,
            "pdf": str(pdf) if pdf else None,
            "draft": draft,
            "draft_path": str(
                draft_path(self.work_dir, paper_id, self.expert)
            ),
        }

    def _paper_pdf(self, paper_id: str) -> Path | None:
        return resolve_paper_pdf(self.root, paper_id)

    def _save_draft(
        self, paper_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        draft = body.get("draft")
        if not isinstance(draft, dict):
            raise ContributionGoldFormError("draft body must be an object")
        draft.setdefault("arxiv_id", paper_id)
        draft.setdefault("annotator", self.expert)
        return save_draft(draft, self.work_dir)

    def _validate(self, paper_id: str) -> dict[str, Any]:
        try:
            draft = load_draft(self.work_dir, paper_id, self.expert)
        except ContributionGoldFormError as error:
            return {
                "paper_id": paper_id,
                "ok": False,
                "errors": [f"draft not loadable: {error}"],
            }
        try:
            result = validate_and_lint(draft)
        except Exception as error:  # noqa: BLE001 - a blocked save is the point
            return {
                "paper_id": paper_id,
                "ok": False,
                "errors": [f"{type(error).__name__}: {error}"],
            }
        return {
            "paper_id": paper_id,
            "ok": bool(result.get("valid")),
            **result,
        }

    def _save(
        self, paper_id: str, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        draft = load_draft(self.work_dir, paper_id, self.expert)
        gate = self._validate(paper_id)
        if not gate.get("ok"):
            return 422, {
                "error": "validate-before-save gate failed",
                "gate": gate,
            }
        if not body.get("expert_approved"):
            return 422, {
                "error": "final save requires explicit expert approval",
            }
        summary = save_expert_annotation(
            draft,
            self.gold_dir,
            work_dir=self.work_dir,
            expected_arxiv_id=paper_id,
            expected_annotator=self.expert,
            expert_approved=True,
        )
        return 200, summary


def render_form_http_response(status: int, payload: dict[str, Any]) -> str:
    """Render one controller response as an HTTP body (text, no socket)."""

    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _render_html_form(document: dict[str, Any]) -> str:
    paper_id = html.escape(str(document["paper_id"]))
    expert = html.escape(str(document["expert"]))
    draft = html.escape(
        json.dumps(document["draft"], ensure_ascii=False, indent=2)
    )
    pdf_url = f"/papers/{paper_id}/pdf"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stella contribution Gold - {paper_id}</title>
<style>
body{{font:14px system-ui;margin:0;display:grid;grid-template-columns:48% 52%;height:100vh}}
iframe{{width:100%;height:100%;border:0}} main{{padding:18px;overflow:auto}}
textarea{{width:100%;height:65vh;font:12px ui-monospace,monospace}}
button{{margin:8px 8px 0 0;padding:8px 12px}} pre{{white-space:pre-wrap}}
</style></head><body>
<iframe src="{pdf_url}" title="paper PDF"></iframe><main>
<h1>Stella contribution Gold</h1><p>Paper: {paper_id} · Expert: {expert}</p>
<textarea id="draft">{draft}</textarea><br>
<button onclick="saveDraft()">Save draft</button>
<button onclick="act('validate')">Validate draft</button>
<button onclick="act('save', true)">Approve and save final</button>
<pre id="result"></pre>
<script>
const api='/api/papers/{paper_id}';
async function request(path, body){{const r=await fetch(api+path,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body||{{}})}});document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2)}}
function saveDraft(){{request('/draft',{{draft:JSON.parse(document.getElementById('draft').value)}})}}
function act(name, approved=false){{request('/'+name,{{expert_approved:approved}})}}
</script></main></body></html>"""


def create_gold_form_server(
    controller: GoldFormController,
    *,
    paper_id: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Create a loopback form server; the caller owns its lifecycle."""

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ContributionGoldFormError(
            "the private Gold form may bind only to the loopback interface"
        )
    expected_paper = paper_id

    class Handler(BaseHTTPRequestHandler):
        server_version = "StellaGoldForm/1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(
                status,
                render_form_http_response(status, payload).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                self.send_response(302)
                self.send_header("Location", f"/papers/{expected_paper}")
                self.end_headers()
                return
            if path == f"/papers/{expected_paper}":
                status, document = controller.handle_request(
                    "GET", f"/papers/{expected_paper}"
                )
                if status != 200:
                    self._json(status, document)
                    return
                self._send(
                    200,
                    _render_html_form(document).encode("utf-8"),
                    "text/html; charset=utf-8",
                )
                return
            if path == f"/api/papers/{expected_paper}":
                status, document = controller.handle_request(
                    "GET", f"/papers/{expected_paper}"
                )
                self._json(status, document)
                return
            if path == f"/papers/{expected_paper}/pdf":
                pdf = controller._paper_pdf(expected_paper)
                if pdf is None:
                    self._json(404, {"error": "paper PDF is missing"})
                    return
                self._send(200, pdf.read_bytes(), "application/pdf")
                return
            self._json(404, {"error": "unknown form route"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            prefix = f"/api/papers/{expected_paper}/"
            if not path.startswith(prefix):
                self._json(404, {"error": "unknown form route"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 4 * 1024 * 1024:
                    raise ValueError("request body is too large")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {"error": str(error)})
                return
            action = path[len(prefix) :]
            status, response = controller.handle_request(
                "POST", f"/papers/{expected_paper}/{action}", body
            )
            self._json(status, response)

    return ThreadingHTTPServer((host, port), Handler)


def serve_gold_form(
    *,
    root: Path,
    paper_id: str,
    expert: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Serve one private expert session until interrupted."""

    controller = GoldFormController(root=root, expert=expert)
    server = create_gold_form_server(
        controller, paper_id=paper_id, host=host, port=port
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
