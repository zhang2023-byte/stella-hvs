"""Local browser form for benchmark expert gold annotations.

This module is part of the expert-led annotation workflow: it writes the
expert-filled YAML in the external private gold directory and emits the JSON
twin through the same Pydantic schema used by
scripts/upgrade_gold_annotation.py. It intentionally serves a local form only;
paper reading stays outside the app, from the PDF.
"""

from __future__ import annotations

import html
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from stella.benchmark.gold import (
    GOLD_ORIGIN_TYPES,
    SCORED_QUANTITY_FIELDS,
    GoldAnnotation,
    compact_annotation_document,
    gold_json_document,
    lint_annotation,
    validate_annotator_handle,
)
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id
from stella.lit.schema_specs import LITERATURE_HVS_LIMIT_KINDS
from stella.schema_registry import schema_ref

MAX_REQUEST_BYTES = 2_000_000


class GoldFormError(ValueError):
    """Raised when a form request cannot be safely completed."""


@dataclass(frozen=True)
class GoldFormConfig:
    workspace: Path
    manifest_path: Path
    gold_dir: Path
    arxiv_id: str = ""
    annotator: str = ""


def validate_arxiv_id(arxiv_id: str) -> str:
    try:
        return validate_unversioned_arxiv_id(arxiv_id)
    except ValueError as exc:
        raise GoldFormError(f"invalid arxiv_id: {arxiv_id!r}") from exc


def validate_annotator(annotator: str) -> str:
    try:
        return validate_annotator_handle(annotator)
    except ValueError as exc:
        raise GoldFormError(f"invalid annotator: {annotator!r}") from exc


def read_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        return {"papers": []}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def manifest_papers(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    papers = manifest.get("papers", [])
    if not isinstance(papers, list):
        return []
    return [paper for paper in papers if isinstance(paper, dict)]


def manifest_entry(manifest: dict[str, Any], arxiv_id: str) -> dict[str, Any] | None:
    for entry in manifest_papers(manifest):
        if entry.get("arxiv_id") == arxiv_id:
            return entry
    return None


def ensure_manifest_paper(manifest_path: Path, arxiv_id: str) -> None:
    safe_arxiv_id = validate_arxiv_id(arxiv_id)
    manifest = read_manifest(manifest_path.expanduser())
    entry = manifest_entry(manifest, safe_arxiv_id)
    if entry is None:
        raise GoldFormError(f"{safe_arxiv_id} is not in the sampling manifest")


def guideline_version(workspace: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h", "--", "benchmark/GUIDELINE.md"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def build_empty_payload(
    arxiv_id: str = "",
    annotator: str = "",
    guideline: str = "",
    annotated_at: str = "",
) -> dict[str, Any]:
    return {
        "schema": schema_ref("benchmark.gold_annotation"),
        "arxiv_id": arxiv_id,
        "annotator": annotator,
        "annotated_at": annotated_at or date.today().isoformat(),
        "guideline_version": guideline,
        "evidence_basis": "pdf",
        "status": "candidates_found",
        "candidates": [],
        "notes": "",
    }


def quantity_field_groups() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for field in SCORED_QUANTITY_FIELDS:
        group = field.split(".", 1)[0]
        groups.setdefault(group, []).append(field)
    return groups


def output_annotation_paths(
    gold_dir: Path,
    arxiv_id: str,
    annotator: str,
) -> tuple[Path, Path]:
    safe_arxiv_id = validate_arxiv_id(arxiv_id)
    safe_annotator = validate_annotator(annotator)
    root = gold_dir.expanduser().resolve()
    target_dir = (root / safe_arxiv_id).resolve()
    try:
        target_dir.relative_to(root)
    except ValueError as error:
        raise GoldFormError("annotation path escapes gold_dir") from error
    stem = f"annotation_{safe_annotator}"
    return target_dir / f"{stem}.yaml", target_dir / f"{stem}.json"


def output_draft_path(gold_dir: Path, arxiv_id: str, annotator: str) -> Path:
    safe_arxiv_id = validate_arxiv_id(arxiv_id)
    safe_annotator = validate_annotator(annotator)
    root = gold_dir.expanduser().resolve()
    target_dir = (root / safe_arxiv_id).resolve()
    try:
        target_dir.relative_to(root)
    except ValueError as error:
        raise GoldFormError("draft path escapes gold_dir") from error
    return target_dir / f"draft_{safe_annotator}.json"


def validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "path": [str(part) for part in item.get("loc", ())],
            "message": item.get("msg", ""),
            "type": item.get("type", ""),
        }
        for item in error.errors()
    ]


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    document: dict[str, Any] | None = None
    json_document: dict[str, Any] | None = None
    try:
        annotation = GoldAnnotation.model_validate(payload)
    except ValidationError as error:
        errors.extend(validation_errors(error))
    else:
        if annotation.status == "no_candidates" and not annotation.notes.strip():
            errors.append(
                {
                    "path": ["notes"],
                    "message": "no_candidates annotations need explanatory notes",
                    "type": "gold_form.no_candidate_notes_required",
                }
        )
        warnings = lint_annotation(annotation)
        document = compact_annotation_document(annotation)
        json_document = gold_json_document(annotation)
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "document": document,
        "json_document": json_document,
    }


def yaml_text_for_document(document: dict[str, Any]) -> str:
    return yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def save_annotation(
    payload: dict[str, Any],
    gold_dir: Path,
    expected_arxiv_id: str = "",
    expected_annotator: str = "",
) -> dict[str, Any]:
    if expected_arxiv_id and payload.get("arxiv_id") != expected_arxiv_id:
        raise GoldFormError(
            f"payload arxiv_id {payload.get('arxiv_id')!r} does not match "
            f"selected paper {expected_arxiv_id!r}"
        )
    if expected_annotator and payload.get("annotator") != expected_annotator:
        raise GoldFormError(
            f"payload annotator {payload.get('annotator')!r} does not match "
            f"selected annotator {expected_annotator!r}"
        )
    result = validate_payload(payload)
    if not result["valid"]:
        raise GoldFormError("annotation is not valid")
    document = result["document"]
    json_document = result["json_document"]
    if not isinstance(document, dict):
        raise GoldFormError("validated annotation is missing")
    if not isinstance(json_document, dict):
        raise GoldFormError("validated JSON annotation is missing")
    yaml_text = yaml_text_for_document(document)
    roundtrip = yaml.safe_load(yaml_text)
    if not isinstance(roundtrip, dict):
        raise GoldFormError("YAML roundtrip did not produce a mapping")
    roundtrip_result = validate_payload(roundtrip)
    if not roundtrip_result["valid"]:
        raise GoldFormError("YAML roundtrip failed validation")
    yaml_path, json_path = output_annotation_paths(
        gold_dir,
        document["arxiv_id"],
        document["annotator"],
    )
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(yaml_text, encoding="utf-8")
    json_path.write_text(
        json.dumps(json_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "valid": True,
        "warnings": result["warnings"],
        "yaml_path": str(yaml_path),
        "json_path": str(json_path),
        "document": document,
        "json_document": json_document,
    }


def draft_artifact_summary(gold_dir: Path, arxiv_id: str, annotator: str) -> dict[str, Any]:
    if not arxiv_id or not annotator:
        return {"exists": False, "path": ""}
    try:
        draft_path = output_draft_path(gold_dir, arxiv_id, annotator)
    except GoldFormError:
        return {"exists": False, "path": ""}
    return {"exists": draft_path.is_file(), "path": str(draft_path)}


def load_draft(gold_dir: Path, arxiv_id: str, annotator: str) -> dict[str, Any]:
    draft_path = output_draft_path(gold_dir, arxiv_id, annotator)
    if not draft_path.is_file():
        return {"exists": False, "draft_path": str(draft_path), "payload": None}
    document = json.loads(draft_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise GoldFormError("draft JSON must be an object")
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise GoldFormError("draft JSON is missing payload object")
    return {"exists": True, "draft_path": str(draft_path), "payload": payload}


def save_draft(payload: dict[str, Any], gold_dir: Path) -> dict[str, Any]:
    arxiv_id = validate_arxiv_id(str(payload.get("arxiv_id", "")))
    annotator = validate_annotator(str(payload.get("annotator", "")))
    draft_path = output_draft_path(gold_dir, arxiv_id, annotator)
    document = {
        "schema": schema_ref("benchmark.gold_form_draft"),
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "payload": payload,
    }
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "valid": True,
        "message": "Draft saved without schema validation",
        "draft_path": str(draft_path),
        "payload": payload,
    }


def gold_artifact_summary(gold_dir: Path, arxiv_id: str) -> dict[str, Any]:
    try:
        safe_arxiv_id = validate_arxiv_id(arxiv_id)
    except GoldFormError:
        return {"exists": False, "files": []}
    paper_dir = gold_dir.expanduser().resolve() / safe_arxiv_id
    if not paper_dir.is_dir():
        return {"exists": False, "files": []}
    files = sorted(
        path.name
        for path in paper_dir.iterdir()
        if path.is_file() and path.name.startswith("annotation_")
        and path.suffix in {".yaml", ".json"}
    )
    return {"exists": bool(files), "files": files}


def paper_summary(
    workspace: Path,
    gold_dir: Path,
    entry: dict[str, Any],
    annotator: str = "",
) -> dict[str, Any]:
    arxiv_id = str(entry.get("arxiv_id", ""))
    gold = gold_artifact_summary(gold_dir, arxiv_id)
    draft = draft_artifact_summary(gold_dir, arxiv_id, annotator)
    return {
        "arxiv_id": arxiv_id,
        "legacy_status": entry.get("legacy_status", ""),
        "pdf_path": str(workspace / "literature" / arxiv_id / "arxiv.pdf"),
        "gold_exists": gold["exists"],
        "gold_files": gold["files"],
        "draft_annotator": annotator,
        "draft_exists": draft["exists"],
        "draft_path": draft["path"],
    }


def bootstrap_state(config: GoldFormConfig) -> dict[str, Any]:
    workspace = config.workspace.expanduser().resolve()
    manifest = read_manifest(config.manifest_path.expanduser())
    selected_annotator = config.annotator.strip()
    papers = [
        paper_summary(workspace, config.gold_dir, entry, selected_annotator)
        for entry in manifest_papers(manifest)
    ]
    selected_arxiv_id = config.arxiv_id.strip()
    if selected_arxiv_id:
        entry = manifest_entry(manifest, selected_arxiv_id)
        if entry is None:
            selected_arxiv_id = ""
    guideline = guideline_version(workspace)
    payload = build_empty_payload(
        arxiv_id=selected_arxiv_id,
        annotator=selected_annotator,
        guideline=guideline,
    )
    entry = (
        manifest_entry(manifest, selected_arxiv_id)
        if selected_arxiv_id
        else None
    )
    selected_gold = (
        gold_artifact_summary(config.gold_dir, selected_arxiv_id)
        if selected_arxiv_id
        else {"exists": False, "files": []}
    )
    selected_draft = draft_artifact_summary(
        config.gold_dir,
        selected_arxiv_id,
        selected_annotator,
    )
    return {
        "payload": payload,
        "selected": {
            "arxiv_id": selected_arxiv_id,
            "annotator": selected_annotator,
            "legacy_status": entry.get("legacy_status", "") if entry else "",
            "gold_exists": selected_gold["exists"],
            "gold_files": selected_gold["files"],
            "draft_annotator": selected_annotator,
            "draft_exists": selected_draft["exists"],
            "draft_path": selected_draft["path"],
            "pdf_path": (
                str(workspace / "literature" / selected_arxiv_id / "arxiv.pdf")
                if selected_arxiv_id
                else ""
            ),
        },
        "papers": papers,
        "options": {
            "quantity_field_groups": quantity_field_groups(),
            "origin_types": list(GOLD_ORIGIN_TYPES),
            "limit_kinds": list(LITERATURE_HVS_LIMIT_KINDS),
            "statuses": ["candidates_found", "no_candidates"],
        },
    }


def json_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, body: Any) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def text_response(
    handler: BaseHTTPRequestHandler,
    status: HTTPStatus,
    body: str,
    content_type: str = "text/html; charset=utf-8",
) -> None:
    payload = body.encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def read_json_request(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length > MAX_REQUEST_BYTES:
        raise GoldFormError("request body is too large")
    body = handler.rfile.read(length)
    data = json.loads(body.decode("utf-8") or "{}")
    if not isinstance(data, dict):
        raise GoldFormError("request JSON must be an object")
    return data


def payload_from_request(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("payload", data)
    if not isinstance(payload, dict):
        raise GoldFormError("payload must be an object")
    return payload


def make_handler(config: GoldFormConfig) -> type[BaseHTTPRequestHandler]:
    class GoldAnnotationHandler(BaseHTTPRequestHandler):
        server_version = "StellaGoldForm/1.0"

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                state = bootstrap_state(config)
                text_response(self, HTTPStatus.OK, render_page(state))
                return
            if self.path == "/api/bootstrap":
                json_response(self, HTTPStatus.OK, bootstrap_state(config))
                return
            json_response(
                self,
                HTTPStatus.NOT_FOUND,
                {"error": f"unknown route: {self.path}"},
            )

        def do_POST(self) -> None:  # noqa: N802
            try:
                data = read_json_request(self)
                payload = payload_from_request(data)
                if self.path == "/api/validate":
                    json_response(self, HTTPStatus.OK, validate_payload(payload))
                    return
                if self.path == "/api/load-draft":
                    ensure_manifest_paper(
                        config.manifest_path,
                        str(payload.get("arxiv_id", "")),
                    )
                    draft = load_draft(
                        config.gold_dir,
                        str(payload.get("arxiv_id", "")),
                        str(payload.get("annotator", "")),
                    )
                    json_response(self, HTTPStatus.OK, {"valid": True, **draft})
                    return
                if self.path == "/api/save-draft":
                    ensure_manifest_paper(
                        config.manifest_path,
                        str(payload.get("arxiv_id", "")),
                    )
                    saved = save_draft(payload, config.gold_dir)
                    json_response(self, HTTPStatus.OK, saved)
                    return
                if self.path == "/api/save":
                    ensure_manifest_paper(
                        config.manifest_path,
                        str(payload.get("arxiv_id", "")),
                    )
                    saved = save_annotation(
                        payload,
                        config.gold_dir,
                    )
                    json_response(self, HTTPStatus.OK, saved)
                    return
                json_response(
                    self,
                    HTTPStatus.NOT_FOUND,
                    {"error": f"unknown route: {self.path}"},
                )
            except (GoldFormError, json.JSONDecodeError) as error:
                json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"valid": False, "errors": [{"message": str(error)}]},
                )

        def log_message(self, format: str, *args: Any) -> None:
            if os.environ.get("STELLA_GOLD_FORM_QUIET"):
                return
            super().log_message(format, *args)

    return GoldAnnotationHandler


def create_server(
    host: str,
    port: int,
    config: GoldFormConfig,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(config))


def render_page(state: dict[str, Any]) -> str:
    state_json = html.escape(json.dumps(state, ensure_ascii=False), quote=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stella Gold Annotation</title>
  <style>
{_PAGE_CSS}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand-lockup">
      <p class="eyebrow">STELLA BENCHMARK</p>
      <h1>Gold Annotation</h1>
    </div>
    <div id="meta" class="meta-strip"></div>
  </header>
  <main class="annotation-shell">
    <aside class="candidate-rail" aria-label="Paper and candidate navigation">
      <div id="paper-picker"></div>
      <div id="candidate-nav"></div>
    </aside>
    <section class="editor" aria-label="Candidate editor">
      <div id="document-fields"></div>
      <div id="candidate-workspace"></div>
    </section>
    <aside class="side-panel">
      <div class="action-panel">
        <div class="panel-title">
          <p class="eyebrow-light">CHECKPOINT</p>
          <h2>Review and save</h2>
        </div>
        <div class="action-row">
          <button id="save-draft" type="button" class="subtle">Save draft</button>
          <button id="validate" type="button">Validate</button>
          <button id="save" type="button" class="primary">Save formal</button>
        </div>
      </div>
      <div id="annotation-summary" class="annotation-summary"></div>
      <div id="messages" class="messages"></div>
    </aside>
  </main>
  <script type="application/json" id="bootstrap">{state_json}</script>
  <script>
{_PAGE_JS}
  </script>
</body>
</html>
"""


_PAGE_CSS = r"""
:root {
  --black: #000;
  --white: #fff;
  --soft: #f0f0fa;
  --line: #d8d8df;
  --muted: #5a5a5f;
  --bad: #a01010;
  --ok: #0a5f2d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--black);
  background: var(--white);
  font: 14px/1.45 "D-DIN", "Arial Narrow", Arial, sans-serif;
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-end;
  padding: 18px 24px;
  background: var(--black);
  color: var(--white);
  border-bottom: 1px solid #333;
}
.topbar h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.eyebrow {
  margin: 0 0 6px;
  color: #f0f0fa;
  font-size: 11px;
  letter-spacing: 1px;
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(92px, 1fr));
  gap: 8px;
  min-width: min(720px, 58vw);
}
.meta-item {
  border-left: 1px solid #555;
  padding-left: 10px;
}
.meta-item span {
  display: block;
  color: #cfcfd7;
  font-size: 10px;
  letter-spacing: .8px;
  text-transform: uppercase;
}
.meta-item strong {
  display: block;
  overflow-wrap: anywhere;
  font-weight: 700;
}
.layout {
  display: grid;
  grid-template-columns: minmax(520px, 1fr) minmax(360px, 42vw);
  min-height: calc(100vh - 73px);
}
.editor {
  padding: 18px 24px 80px;
  border-right: 1px solid var(--line);
}
.side-panel {
  position: sticky;
  top: 73px;
  height: calc(100vh - 73px);
  padding: 18px;
  background: var(--soft);
  overflow: auto;
}
.section {
  border: 1px solid var(--line);
  border-radius: 4px;
  margin: 0 0 14px;
  background: var(--white);
}
.section-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
}
.section-header h2,
.section-header h3 {
  margin: 0;
  font-size: 13px;
  letter-spacing: .7px;
  text-transform: uppercase;
}
.section-body { padding: 14px; }
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.gold-warning {
  margin-top: 12px;
  border: 1px solid #7a6510;
  border-radius: 4px;
  padding: 10px;
  color: #5f4c00;
  background: #fffdf2;
  overflow-wrap: anywhere;
}
.draft-notice {
  display: grid;
  gap: 8px;
  margin-top: 12px;
  border: 1px solid var(--black);
  border-radius: 4px;
  padding: 10px;
  background: #fafafa;
  overflow-wrap: anywhere;
}
.draft-notice strong {
  font-size: 11px;
  letter-spacing: .7px;
  text-transform: uppercase;
}
.draft-notice p {
  margin: 0;
  color: var(--muted);
}
.mini-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 11px;
  letter-spacing: .6px;
  text-transform: uppercase;
}
input, select, textarea {
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 8px 10px;
  background: var(--white);
  color: var(--black);
  font: inherit;
  letter-spacing: 0;
  text-transform: none;
}
input::placeholder,
textarea::placeholder {
  color: rgba(0, 0, 0, .38);
  font-size: 12px;
}
textarea {
  min-height: 78px;
  resize: vertical;
  text-transform: none;
}
button {
  min-height: 38px;
  border: 1px solid var(--black);
  border-radius: 32px;
  padding: 0 16px;
  background: var(--white);
  color: var(--black);
  font: 700 12px/1 "D-DIN", "Arial Narrow", Arial, sans-serif;
  letter-spacing: .8px;
  text-transform: uppercase;
  cursor: pointer;
}
button.primary {
  background: var(--black);
  color: var(--white);
}
button.subtle {
  border-color: var(--line);
  color: var(--muted);
}
button.danger {
  border-color: var(--bad);
  color: var(--bad);
}
.segmented {
  display: inline-flex;
  gap: 0;
  border: 1px solid var(--black);
  border-radius: 32px;
  overflow: hidden;
}
.segmented button {
  border: 0;
  border-radius: 0;
}
.segmented button.active {
  background: var(--black);
  color: var(--white);
}
.action-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}
.panel-title {
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 14px;
  margin-bottom: 12px;
  background: var(--white);
}
.panel-title h2 {
  margin: 0;
  font-size: 17px;
  line-height: 1.2;
  letter-spacing: .8px;
  text-transform: uppercase;
}
.eyebrow-light {
  margin: 0 0 5px;
  color: var(--muted);
  font-size: 10px;
  letter-spacing: .9px;
  text-transform: uppercase;
}
.messages {
  display: grid;
  gap: 8px;
}
.message {
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 9px 10px;
  background: var(--white);
}
.message.ok { border-color: var(--ok); color: var(--ok); }
.message.bad { border-color: var(--bad); color: var(--bad); }
.message.warn { border-color: #7a6510; color: #5f4c00; }
.quantity {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.evidence-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 10px;
  align-items: end;
  margin-top: 10px;
}
.hidden { display: none !important; }
@media (max-width: 960px) {
  .topbar { align-items: flex-start; flex-direction: column; }
  .meta-grid { min-width: 0; width: 100%; grid-template-columns: repeat(2, 1fr); }
  .layout { grid-template-columns: 1fr; }
  .side-panel { position: static; height: auto; }
}

/* Candidate-oriented annotation shell overrides. */
:root {
  --ink: #101312;
  --paper: #ffffff;
  --canvas: #f3f4f1;
  --rail: #171b19;
  --rail-muted: #b7bfbb;
  --line: #d8ddda;
  --line-strong: #aeb8b2;
  --muted: #59635e;
  --accent: #0e6a82;
  --accent-soft: #e5f0f2;
  --ok: #11633d;
  --bad: #a22c22;
  --warn: #826316;
}
body {
  min-width: 320px;
  color: var(--ink);
  background: var(--canvas);
  font-family: "D-DIN", "DIN 2014", "Aptos", sans-serif;
}
button, input, select, textarea { font: inherit; letter-spacing: 0; }
.topbar {
  z-index: 20;
  align-items: center;
  min-height: 72px;
  padding: 13px 22px;
  background: var(--ink);
  color: var(--paper);
  border-bottom-color: #363d39;
}
.topbar h1 { font-size: 22px; letter-spacing: 0; }
.eyebrow { margin-bottom: 5px; color: #c5cfca; font-size: 10px; letter-spacing: 0; text-transform: uppercase; }
.meta-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(82px, auto));
  min-width: min(620px, 58vw);
}
.meta-item { border-left-color: #49514d; padding: 0 12px; }
.meta-item span { color: #b7bfbb; letter-spacing: 0; }
.annotation-shell {
  display: grid;
  grid-template-columns: 276px minmax(560px, 1fr) 306px;
  min-height: calc(100vh - 72px);
}
.candidate-rail {
  position: sticky;
  top: 72px;
  align-self: start;
  height: calc(100vh - 72px);
  overflow: auto;
  background: var(--rail);
  color: var(--paper);
  border-right: 1px solid #303834;
}
.rail-block { padding: 18px; }
.rail-block + .rail-block { border-top: 1px solid #303834; }
.rail-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 10px; }
.rail-heading h2 { margin: 0; font-size: 13px; text-transform: uppercase; }
.rail-count { color: var(--rail-muted); font-size: 12px; }
.candidate-rail label { color: var(--rail-muted); letter-spacing: 0; }
.candidate-rail select, .candidate-rail input { border-color: #4e5853; background: #242b27; color: var(--paper); }
.candidate-rail input::placeholder { color: #aab3ae; }
.rail-notice { margin-top: 10px; border-left: 2px solid #d1ad45; padding: 8px 0 8px 10px; color: #f0db9d; font-size: 12px; }
.draft-notice { margin-top: 12px; border: 0; border-top: 1px solid #4e5853; border-radius: 0; padding: 12px 0 0; background: transparent; }
.draft-notice strong { letter-spacing: 0; }
.draft-notice p { color: var(--rail-muted); font-size: 12px; }
.mini-actions { gap: 7px; }
.candidate-nav-list { display: grid; gap: 1px; margin: 0 -18px; }
.candidate-nav-item {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 9px;
  width: 100%;
  min-height: 67px;
  border: 0;
  border-left: 3px solid transparent;
  border-radius: 0;
  padding: 11px 15px;
  background: transparent;
  color: var(--paper);
  text-align: left;
  text-transform: none;
}
.candidate-nav-item:hover { background: #212824; color: var(--paper); border-color: transparent; }
.candidate-nav-item.active { border-left-color: #8bd0db; background: #eff7f7; color: var(--ink); }
.candidate-nav-order { color: var(--rail-muted); font-size: 11px; line-height: 1.3; }
.candidate-nav-item.active .candidate-nav-order { color: var(--accent); }
.candidate-nav-name { display: block; overflow: hidden; font-size: 13px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.candidate-nav-meta { display: block; margin-top: 3px; color: var(--rail-muted); font-size: 11px; }
.candidate-nav-item.active .candidate-nav-meta { color: var(--muted); }
.candidate-add { width: 100%; margin-top: 14px; }
.editor { min-width: 0; padding: 24px 28px 84px; background: var(--paper); border-right: 0; }
.side-panel {
  top: 72px;
  align-self: start;
  height: calc(100vh - 72px);
  padding: 18px;
  background: var(--canvas);
  border-left: 1px solid var(--line);
}
.document-bar { display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 16px; border-bottom: 1px solid var(--line-strong); padding-bottom: 18px; }
.document-bar h2, .workspace-head h2, .group-heading h3, .panel-title h2 { margin: 0; line-height: 1.15; letter-spacing: 0; text-transform: uppercase; }
.document-bar h2 { font-size: 15px; }
.workspace-kicker { margin: 0 0 5px; color: var(--accent); font-size: 11px; letter-spacing: 0; text-transform: uppercase; }
.document-meta { margin-bottom: 26px; border-top: 1px solid var(--line); padding-top: 12px; }
.document-meta summary, .provenance summary { color: var(--muted); font-size: 12px; cursor: pointer; user-select: none; }
.document-meta .grid { margin-top: 14px; }
.document-meta textarea { margin-top: 12px; }
.workspace-head { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; border-bottom: 2px solid var(--ink); padding-bottom: 15px; }
.workspace-head h2 { font-size: 22px; overflow-wrap: anywhere; }
.workspace-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; }
.candidate-identity { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 18px 0; border-bottom: 1px solid var(--line); }
.candidate-identity .wide { grid-column: span 2; }
label { color: var(--muted); letter-spacing: 0; }
input, select, textarea { min-height: 36px; border-color: var(--line); border-radius: 3px; padding: 8px 9px; background: var(--paper); color: var(--ink); }
input:focus, select:focus, textarea:focus { outline: 2px solid #8bd0db; outline-offset: 1px; border-color: var(--accent); }
input::placeholder, textarea::placeholder { color: #87908b; }
textarea { min-height: 68px; }
button { min-height: 34px; border-color: var(--ink); border-radius: 3px; padding: 0 11px; background: var(--paper); color: var(--ink); font-family: "D-DIN", "DIN 2014", "Aptos", sans-serif; letter-spacing: 0; }
button:hover { border-color: var(--accent); color: var(--accent); }
button.primary { background: var(--ink); color: var(--paper); }
button.primary:hover { border-color: var(--accent); background: var(--accent); color: var(--paper); }
button.subtle { border-color: var(--line-strong); color: var(--muted); }
button.danger { border-color: var(--bad); color: var(--bad); }
.icon-button { width: 34px; min-width: 34px; padding: 0; font-size: 16px; line-height: 1; }
.segmented { border-color: var(--ink); border-radius: 3px; }
.segmented button { border-right: 1px solid var(--ink); }
.segmented button:last-child { border-right: 0; }
.segmented button.active { background: var(--ink); color: var(--paper); }
.action-panel, .annotation-summary, .messages { border-top: 1px solid var(--line-strong); padding-top: 14px; }
.action-row { flex-wrap: wrap; gap: 8px; margin: 13px 0 0; }
.panel-title { border: 0; border-radius: 0; padding: 0; margin: 0; background: transparent; }
.panel-title h2 { font-size: 17px; }
.eyebrow-light { letter-spacing: 0; }
.annotation-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; margin-top: 20px; }
.summary-item { min-height: 64px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 8px 9px; }
.summary-item:nth-child(2n) { border-right: 0; }
.summary-item span { display: block; color: var(--muted); font-size: 10px; text-transform: uppercase; }
.summary-item strong { display: block; margin-top: 4px; font-size: 17px; }
.messages { margin-top: 20px; }
.message { border-radius: 3px; background: var(--paper); overflow-wrap: anywhere; }
.message.warn { border-color: var(--warn); color: #675013; }
.quantity-group { margin-top: 24px; border-top: 1px solid var(--line-strong); }
.group-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 13px 0; border-bottom: 1px solid var(--line); }
.group-heading h3 { font-size: 13px; }
.group-heading-left { display: flex; align-items: baseline; gap: 8px; }
.group-count { color: var(--muted); font-size: 12px; }
.quantity-list { display: grid; }
.quantity-row { display: grid; grid-template-columns: 42px minmax(185px, 1.25fr) minmax(175px, 1fr) minmax(185px, 1fr) 34px; gap: 10px; align-items: start; border-bottom: 1px solid var(--line); padding: 13px 0; }
.quantity-marker { padding-top: 23px; color: var(--muted); font-size: 11px; text-align: center; }
.quantity-core, .quantity-value, .quantity-uncertainty { display: grid; gap: 9px; }
.quantity-value.range { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.quantity-uncertainty { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.quantity-row .icon-button { margin-top: 23px; }
.provenance { grid-column: 2 / -1; margin-top: 1px; border-left: 2px solid var(--line-strong); padding: 7px 0 0 10px; }
.provenance-body { display: grid; gap: 10px; margin-top: 10px; }
.evidence-row { gap: 8px; margin-top: 0; }
.empty-state { margin-top: 24px; border-left: 3px solid var(--accent); padding: 18px 0 18px 16px; }
.empty-state h2 { margin: 0; font-size: 19px; text-transform: uppercase; }
.empty-state p { max-width: 520px; margin: 8px 0 0; color: var(--muted); }
@media (max-width: 1260px) {
  .annotation-shell { grid-template-columns: 248px minmax(0, 1fr); }
  .side-panel { position: static; grid-column: 1 / -1; height: auto; border-top: 1px solid var(--line); border-left: 0; }
  .action-panel, .annotation-summary, .messages { max-width: 860px; margin-left: auto; margin-right: auto; }
}
@media (max-width: 900px) {
  .topbar { align-items: flex-start; flex-direction: column; }
  .meta-strip { width: 100%; min-width: 0; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .meta-item { padding: 0 8px; }
  .annotation-shell { grid-template-columns: 1fr; }
  .candidate-rail { position: static; height: auto; }
  .candidate-nav-list { grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; gap: 1px; }
  .candidate-nav-item { border: 1px solid #303834; }
  .candidate-nav-item.active { border-left: 3px solid #8bd0db; }
  .editor { padding: 20px; }
  .quantity-row { grid-template-columns: 34px minmax(0, 1fr) minmax(0, 1fr) 34px; }
  .quantity-uncertainty { grid-column: 2 / 4; }
  .provenance { grid-column: 2 / -1; }
}
@media (max-width: 620px) {
  .topbar { padding: 13px 16px; }
  .meta-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .meta-item:nth-child(odd) { border-left: 0; }
  .candidate-nav-list { grid-template-columns: 1fr; }
  .editor { padding: 18px 14px 52px; }
  .document-bar, .workspace-head { align-items: stretch; flex-direction: column; }
  .workspace-actions { justify-content: flex-start; }
  .candidate-identity, .grid, .grid.three { grid-template-columns: 1fr; }
  .candidate-identity .wide { grid-column: auto; }
  .quantity-row { grid-template-columns: 30px minmax(0, 1fr) 34px; }
  .quantity-value, .quantity-uncertainty { grid-column: 2; }
  .quantity-value.range, .quantity-uncertainty { grid-template-columns: 1fr; }
  .quantity-row .icon-button { grid-column: 3; grid-row: 1; }
  .provenance { grid-column: 2 / -1; }
  .evidence-row { grid-template-columns: 1fr; }
  .evidence-row .icon-button { justify-self: start; }
}
"""


_PAGE_JS = r"""
const state = JSON.parse(document.getElementById("bootstrap").textContent);
let payload = structuredClone(state.payload);
let activeCandidateIndex = 0;

const $ = (selector) => document.querySelector(selector);
const el = (tag, attrs = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
};
const groups = state.options.quantity_field_groups;
const firstField = Object.values(groups).flat()[0] || "";
const groupLabels = {
  observed_phase_space: "Observed phase space",
  derived_kinematics: "Derived kinematics",
  bound_assessment: "Bound assessment"
};
const examples = {
  arxiv_id: "1902.05061",
  annotator: "will",
  annotated_at: "2026-06-25",
  guideline_version: "80fc801",
  document_notes: "No HVS / Galactic-unbound candidates after checking Tables 1-2 and Sec. 4...",
  paper_candidate_id: "S5-HVS1",
  gaia_source_id: "Gaia DR3 1234567890123456789",
  aliases: "LAMOST J1234+5678\nHVS 7",
  candidate_notes: "Paper treats this object as possibly unbound under its fiducial potential.",
  value: "743",
  unit: "km/s",
  range_lower: "8.2",
  range_upper: "11.6",
  error: "4.1",
  lower_error: "12",
  upper_error: "15",
  evidence_location: "Table 2, row S5-HVS1, col v_GC",
  evidence_quote: "743^{+15}_{-12}",
  quantity_notes: "Use the no-Galactic-center-origin value; alternative model values skipped."
};

function emptyEvidence() { return { location: "", quote: "" }; }
function emptyQuantity(group = "") {
  const preferredField = group && groups[group] ? groups[group][0] : firstField;
  return {
    field: preferredField, value: "", error: "", lower_error: "", upper_error: "",
    unit: "", limit_kind: "", range_lower: "", range_upper: "",
    evidence: [emptyEvidence()], notes: ""
  };
}
function emptyCandidate() {
  return {
    paper_candidate_id: "", gaia_source_id: "", aliases: [],
    origin_type: "introduced_by_this_paper",
    quantities: [], evidence: [emptyEvidence()], notes: ""
  };
}
function freshPayloadForCurrent() {
  return {
    schema: state.payload.schema,
    arxiv_id: payload.arxiv_id || state.selected.arxiv_id || "",
    annotator: payload.annotator || state.selected.annotator || "",
    annotated_at: payload.annotated_at || state.payload.annotated_at,
    guideline_version: payload.guideline_version || state.payload.guideline_version,
    evidence_basis: "pdf",
    status: "candidates_found",
    candidates: [],
    notes: ""
  };
}
function candidateList() {
  if (!Array.isArray(payload.candidates)) payload.candidates = [];
  return payload.candidates;
}
function activeCandidate() {
  const candidates = candidateList();
  if (!candidates.length) return null;
  activeCandidateIndex = Math.min(Math.max(activeCandidateIndex, 0), candidates.length - 1);
  return candidates[activeCandidateIndex];
}
function groupForField(field) {
  return String(field || "").split(".", 1)[0] || "observed_phase_space";
}
function candidateName(candidate, index) {
  return candidate.paper_candidate_id || candidate.gaia_source_id || `Candidate ${index + 1}`;
}
function groupCounts(candidate) {
  const counts = Object.fromEntries(Object.keys(groups).map((group) => [group, 0]));
  for (const quantity of candidate.quantities || []) {
    const group = groupForField(quantity.field);
    counts[group] = (counts[group] || 0) + 1;
  }
  return counts;
}
function countQuantities() {
  return candidateList().reduce((count, candidate) => count + (candidate.quantities || []).length, 0);
}
function countEvidence() {
  return candidateList().reduce((count, candidate) => {
    const candidateEvidence = (candidate.evidence || []).length;
    const quantityEvidence = (candidate.quantities || []).reduce(
      (quantityCount, quantity) => quantityCount + (quantity.evidence || []).length,
      0
    );
    return count + candidateEvidence + quantityEvidence;
  }, 0);
}
function syncSelected() {
  state.selected.arxiv_id = payload.arxiv_id || "";
  state.selected.annotator = payload.annotator || "";
  const paper = state.papers.find((item) => item.arxiv_id === payload.arxiv_id);
  state.selected.legacy_status = paper ? paper.legacy_status : "";
  state.selected.gold_exists = paper ? paper.gold_exists : false;
  state.selected.gold_files = paper ? paper.gold_files : [];
  const draftMatchesAnnotator = paper && paper.draft_annotator === payload.annotator;
  state.selected.draft_exists = draftMatchesAnnotator ? paper.draft_exists : false;
  state.selected.draft_path = draftMatchesAnnotator ? paper.draft_path : "";
  state.selected.pdf_path = paper ? paper.pdf_path : "";
}
function input(label, value, oninput, type = "text", placeholder = "") {
  const field = el("input", {
    type,
    value: value || "",
    placeholder,
    oninput: (event) => oninput(event.target.value)
  });
  return el("label", {}, [document.createTextNode(label), field]);
}
function textarea(label, value, oninput, placeholder = "") {
  const field = el("textarea", {
    placeholder,
    oninput: (event) => oninput(event.target.value)
  });
  field.value = value || "";
  return el("label", {}, [document.createTextNode(label), field]);
}
function select(label, value, options, onchange) {
  const field = el("select", { onchange: (event) => onchange(event.target.value) });
  for (const option of options) {
    const opt = el("option", { value: option, text: option || "(exact)" });
    if (option === value) opt.selected = true;
    field.append(opt);
  }
  return el("label", {}, [document.createTextNode(label), field]);
}
function quantitySelect(quantity) {
  const field = el("select", { onchange: (event) => { quantity.field = event.target.value; render(); } });
  for (const [group, fields] of Object.entries(groups)) {
    const optgroup = el("optgroup", { label: group });
    for (const name of fields) {
      const opt = el("option", { value: name, text: name });
      if (name === quantity.field) opt.selected = true;
      optgroup.append(opt);
    }
    field.append(optgroup);
  }
  return el("label", {}, [document.createTextNode("field"), field]);
}
function renderMeta() {
  syncSelected();
  const items = [
    ["arXiv", payload.arxiv_id || "not selected"],
    ["basis", "PDF-only"],
    ["status", payload.status || "not set"],
    ["candidates", String(candidateList().length)],
    ["quantities", String(countQuantities())]
  ];
  $("#meta").replaceChildren(...items.map(([label, value]) =>
    el("div", { class: "meta-item" }, [el("span", { text: label }), el("strong", { text: value })])
  ));
}
function goldWarning() {
  if (!state.selected.gold_exists) return null;
  const files = (state.selected.gold_files || []).join(", ");
  return el("div", {
    class: "rail-notice",
    text: `Existing gold artifacts found for this paper: ${files}. Saving with the same annotator will overwrite only that annotator's YAML/JSON; other annotators' files are unchanged.`
  });
}
function draftNotice() {
  if (!payload.arxiv_id || !payload.annotator || !state.selected.draft_exists) return null;
  const path = state.selected.draft_path || `draft_${payload.annotator}.json`;
  return el("div", { class: "draft-notice" }, [
    el("strong", { text: "Draft found" }),
    el("p", { text: `A draft exists for this paper and annotator: ${path}` }),
    el("div", { class: "mini-actions" }, [
      el("button", { type: "button", class: "subtle", text: "Load Draft", onclick: loadDraft }),
      el("button", { type: "button", text: "Start Fresh", onclick: startFresh })
    ])
  ]);
}
function renderPicker() {
  syncSelected();
  const paperSelect = el("select", { onchange: (event) => {
    payload.arxiv_id = event.target.value;
    render();
  }});
  paperSelect.append(el("option", { value: "", text: "Select paper" }));
  for (const paper of state.papers) {
    const goldStatus = paper.gold_exists ? "gold exists" : "no gold";
    const draftStatus = (
      paper.draft_annotator === payload.annotator && paper.draft_exists
    ) ? "draft exists" : "no draft";
    const label = [paper.arxiv_id, paper.legacy_status || "unknown", goldStatus, draftStatus].join(" - ");
    const opt = el("option", { value: paper.arxiv_id, text: label });
    if (paper.arxiv_id === payload.arxiv_id) opt.selected = true;
    paperSelect.append(opt);
  }
  const warning = goldWarning();
  const draft = draftNotice();
  const section = el("div", { class: "rail-block" }, [
    el("div", { class: "rail-heading" }, [
      el("h2", { text: "Paper" }),
      el("span", { class: "rail-count", text: "PDF-only" })
    ]),
    el("label", {}, [document.createTextNode("active paper"), paperSelect]),
    warning || el("div"),
    draft || el("div")
  ]);
  $("#paper-picker").replaceChildren(section);
}
function renderDocumentFields() {
  const status = el("div", { class: "segmented" }, state.options.statuses.map((item) =>
    el("button", {
      type: "button",
      class: payload.status === item ? "active" : "",
      text: item,
      onclick: () => { payload.status = item; if (item === "no_candidates") payload.candidates = []; render(); }
    })
  ));
  const metadata = el("details", { class: "document-meta" }, [
    el("summary", { text: "Document metadata and notes" }),
    el("div", { class: "grid three" }, [
      input("annotator", payload.annotator, (value) => { payload.annotator = value; updateOnly(); }, "text", examples.annotator),
      input("annotated_at", payload.annotated_at, (value) => { payload.annotated_at = value; updateOnly(); }, "text", examples.annotated_at),
      input("guideline_version", payload.guideline_version, (value) => { payload.guideline_version = value; updateOnly(); }, "text", examples.guideline_version),
    ]),
    textarea("notes", payload.notes, (value) => { payload.notes = value; updateOnly(); }, examples.document_notes)
  ]);
  if (payload.status === "no_candidates") metadata.open = true;
  const section = el("div", { class: "document-bar" }, [
    el("div", {}, [el("p", { class: "workspace-kicker", text: "Annotation state" }), el("h2", { text: "Document" })]),
    status
  ]);
  $("#document-fields").replaceChildren(section, metadata);
}
function renderEvidenceList(items, onChange) {
  const rows = items.map((evidence, index) =>
    el("div", { class: "evidence-row" }, [
      input("location", evidence.location, (value) => { evidence.location = value; onChange(); }, "text", examples.evidence_location),
      input("quote", evidence.quote, (value) => { evidence.quote = value; onChange(); }, "text", examples.evidence_quote),
      el("button", { type: "button", class: "danger icon-button", text: "x", title: "Remove evidence", "aria-label": "Remove evidence", onclick: () => { items.splice(index, 1); onChange(true); } })
    ])
  );
  rows.push(el("button", { type: "button", class: "subtle", text: "+ Evidence", onclick: () => { items.push(emptyEvidence()); onChange(true); } }));
  return el("div", { class: "provenance-body" }, rows);
}
function renderQuantity(candidate, quantity, qIndex) {
  const isRange = quantity.limit_kind === "range";
  const valueControls = isRange
    ? el("div", { class: "quantity-value range" }, [
      input("range lower", quantity.range_lower, (value) => { quantity.range_lower = value; updateOnly(); }, "text", examples.range_lower),
      input("range upper", quantity.range_upper, (value) => { quantity.range_upper = value; updateOnly(); }, "text", examples.range_upper),
    ])
    : el("div", { class: "quantity-value" }, [
      input("value", quantity.value, (value) => { quantity.value = value; updateOnly(); }, "text", examples.value),
      input("unit", quantity.unit, (value) => { quantity.unit = value; updateOnly(); }, "text", examples.unit),
    ]);
  return el("article", { class: "quantity-row" }, [
    el("div", { class: "quantity-marker", text: String(qIndex + 1).padStart(2, "0") }),
    el("div", { class: "quantity-core" }, [
      quantitySelect(quantity),
      select("limit", quantity.limit_kind, state.options.limit_kinds, (value) => { quantity.limit_kind = value; render(); })
    ]),
    valueControls,
    el("div", { class: "quantity-uncertainty" }, [
      input("error", quantity.error, (value) => { quantity.error = value; updateOnly(); }, "text", examples.error),
      input("lower", quantity.lower_error, (value) => { quantity.lower_error = value; updateOnly(); }, "text", examples.lower_error),
      input("upper", quantity.upper_error, (value) => { quantity.upper_error = value; updateOnly(); }, "text", examples.upper_error)
    ]),
    el("button", { type: "button", class: "danger icon-button", text: "x", title: "Delete quantity", "aria-label": "Delete quantity", onclick: () => {
      candidate.quantities.splice(qIndex, 1);
      render();
    }}),
    el("details", { class: "provenance" }, [
      el("summary", { text: "Evidence and quantity notes" }),
      renderEvidenceList(quantity.evidence, (rerender) => rerender ? render() : updateOnly()),
      textarea("quantity notes", quantity.notes, (value) => { quantity.notes = value; updateOnly(); }, examples.quantity_notes)
    ])
  ]);
}
function renderQuantityGroup(candidate, group, entries) {
  return el("section", { class: "quantity-group" }, [
    el("div", { class: "group-heading" }, [
      el("div", { class: "group-heading-left" }, [
        el("h3", { text: groupLabels[group] || group }),
        el("span", { class: "group-count", text: `${entries.length} recorded` })
      ]),
      el("button", { type: "button", class: "subtle", text: "+ Quantity", onclick: () => {
        candidate.quantities.push(emptyQuantity(group));
        render();
      }})
    ]),
    el("div", { class: "quantity-list" }, entries.length
      ? entries.map(({ quantity, index }) => renderQuantity(candidate, quantity, index))
      : [el("div", { class: "empty-state" }, [
        el("h2", { text: "No quantities" }),
        el("p", { text: "Add a paper-visible value in this physical category." })
      ])]
    )
  ]);
}
function renderCandidateWorkspace() {
  const root = $("#candidate-workspace");
  if (payload.status === "no_candidates") {
    root.replaceChildren(el("div", { class: "empty-state" }, [
      el("h2", { text: "No candidate entries" }),
      el("p", { text: "Record the exclusion rationale in document metadata and save the no_candidates annotation." })
    ]));
    return;
  }
  const candidate = activeCandidate();
  if (!candidate) {
    root.replaceChildren(el("div", { class: "empty-state" }, [
      el("h2", { text: "Add the first candidate" }),
      el("p", { text: "Candidate navigation stays on the left. Add an object there, then enter its identity and paper-visible quantities here." }),
      el("button", { type: "button", class: "primary", text: "+ Candidate", onclick: addCandidate })
    ]));
    return;
  }
  const aliases = (candidate.aliases || []).join("\n");
  const quantities = candidate.quantities || [];
  const entries = Object.fromEntries(Object.keys(groups).map((group) => [group, []]));
  quantities.forEach((quantity, index) => {
    const group = groupForField(quantity.field);
    (entries[group] || (entries[group] = [])).push({ quantity, index });
  });
  root.replaceChildren(
    el("div", { class: "workspace-head" }, [
      el("div", {}, [
        el("p", { class: "workspace-kicker", text: `Candidate ${String(activeCandidateIndex + 1).padStart(2, "0")}` }),
        el("h2", { text: candidateName(candidate, activeCandidateIndex) })
      ]),
      el("div", { class: "workspace-actions" }, [
        el("button", { type: "button", class: "subtle", text: "Duplicate", onclick: () => {
          candidateList().splice(activeCandidateIndex + 1, 0, structuredClone(candidate));
          activeCandidateIndex += 1;
          render();
        }}),
        el("button", { type: "button", class: "danger", text: "Delete candidate", onclick: () => {
          candidateList().splice(activeCandidateIndex, 1);
          activeCandidateIndex = Math.max(0, activeCandidateIndex - 1);
          render();
        }})
      ])
    ]),
    el("div", { class: "candidate-identity" }, [
      input("paper candidate id", candidate.paper_candidate_id, (value) => { candidate.paper_candidate_id = value; updateOnly(); }, "text", examples.paper_candidate_id),
      input("Gaia source id", candidate.gaia_source_id, (value) => { candidate.gaia_source_id = value; updateOnly(); }, "text", examples.gaia_source_id),
      textarea("aliases, one per line", aliases, (value) => { candidate.aliases = value.split(/\n/).map((item) => item.trim()).filter(Boolean); updateOnly(); }, examples.aliases),
      select("origin type", candidate.origin_type, state.options.origin_types, (value) => { candidate.origin_type = value; updateOnly(); }),
      el("details", { class: "provenance wide" }, [
        el("summary", { text: "Candidate inclusion evidence and notes" }),
        renderEvidenceList(candidate.evidence, (rerender) => rerender ? render() : updateOnly()),
        textarea("candidate notes", candidate.notes, (value) => { candidate.notes = value; updateOnly(); }, examples.candidate_notes)
      ])
    ]),
    ...Object.keys(groups).map((group) => renderQuantityGroup(candidate, group, entries[group] || []))
  );
}
function addCandidate() {
  candidateList().push(emptyCandidate());
  activeCandidateIndex = candidateList().length - 1;
  render();
}
function renderCandidateNav() {
  const root = $("#candidate-nav");
  const candidates = candidateList();
  const list = el("div", { class: "candidate-nav-list" }, candidates.map((candidate, index) => {
    const counts = groupCounts(candidate);
    const countText = Object.keys(groups)
      .map((group) => `${counts[group] || 0} ${groupLabels[group].split(" ")[0].toLowerCase()}`)
      .join(" / ");
    return el("button", {
      type: "button",
      class: `candidate-nav-item ${index === activeCandidateIndex ? "active" : ""}`,
      "aria-current": index === activeCandidateIndex ? "true" : "false",
      onclick: () => { activeCandidateIndex = index; render(); }
    }, [
      el("span", { class: "candidate-nav-order", text: String(index + 1).padStart(2, "0") }),
      el("span", {}, [
        el("span", { class: "candidate-nav-name", text: candidateName(candidate, index) }),
        el("span", { class: "candidate-nav-meta", text: `${(candidate.quantities || []).length} quantities - ${countText}` })
      ])
    ]);
  }));
  const section = el("div", { class: "rail-block" }, [
    el("div", { class: "rail-heading" }, [
      el("h2", { text: "Candidates" }),
      el("span", { class: "rail-count", text: `${candidates.length} total` })
    ]),
    list
  ]);
  if (payload.status !== "no_candidates") {
    section.append(el("button", { type: "button", class: "candidate-add", text: "+ Candidate", onclick: addCandidate }));
  }
  root.replaceChildren(section);
}
function renderSummary() {
  const items = [
    ["candidates", String(candidateList().length)],
    ["quantities", String(countQuantities())],
    ["evidence rows", String(countEvidence())],
    ["draft", state.selected.draft_exists ? "saved" : "none"]
  ];
  $("#annotation-summary").replaceChildren(...items.map(([label, value]) =>
    el("div", { class: "summary-item" }, [el("span", { text: label }), el("strong", { text: value })])
  ));
}
function showMessages(result) {
  const box = $("#messages");
  const nodes = [];
  if (result.message) {
    nodes.push(el("div", { class: "message ok", text: result.message }));
  } else if (result.valid) {
    nodes.push(el("div", { class: "message ok", text: "Validation passed" }));
  }
  for (const warning of result.warnings || []) {
    nodes.push(el("div", { class: "message warn", text: warning }));
  }
  for (const error of result.errors || []) {
    const path = error.path ? error.path.join(".") : "";
    nodes.push(el("div", { class: "message bad", text: `${path}: ${error.message}` }));
  }
  if (result.yaml_path) nodes.push(el("div", { class: "message ok", text: `YAML: ${result.yaml_path}` }));
  if (result.json_path) nodes.push(el("div", { class: "message ok", text: `JSON: ${result.json_path}` }));
  if (result.draft_path) nodes.push(el("div", { class: "message ok", text: `Draft: ${result.draft_path}` }));
  box.replaceChildren(...nodes);
}
async function requestJson(path, requestPayload = payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload: requestPayload })
  });
  return await response.json();
}
function applyDraftState(result) {
  if (!result.draft_path) return;
  const exists = result.exists === undefined ? Boolean(result.valid) : Boolean(result.exists);
  state.selected.draft_exists = exists;
  state.selected.draft_path = result.draft_path;
  const paper = state.papers.find((item) => item.arxiv_id === payload.arxiv_id);
  if (paper) {
    paper.draft_annotator = payload.annotator;
    paper.draft_exists = exists;
    paper.draft_path = result.draft_path;
  }
}
async function postJson(path) {
  const result = await requestJson(path);
  showMessages(result);
}
async function saveDraft() {
  const result = await requestJson("/api/save-draft");
  applyDraftState(result);
  showMessages(result);
  render();
}
async function loadDraft() {
  const result = await requestJson("/api/load-draft", {
    arxiv_id: payload.arxiv_id,
    annotator: payload.annotator
  });
  applyDraftState(result);
  if (result.exists && result.payload) {
    payload = structuredClone(result.payload);
    activeCandidateIndex = 0;
    render();
    showMessages({
      valid: true,
      message: "Draft loaded",
      draft_path: result.draft_path
    });
  } else {
    render();
    showMessages({
      valid: true,
      message: "No draft found for this paper and annotator",
      draft_path: result.draft_path
    });
  }
}
function startFresh() {
  payload = freshPayloadForCurrent();
  activeCandidateIndex = 0;
  render();
  showMessages({
    valid: true,
    message: "Started a fresh blank form. The draft file was not changed."
  });
}
function updateOnly() {
  renderMeta();
  renderCandidateNav();
  renderSummary();
}
function render() {
  renderMeta();
  renderPicker();
  renderDocumentFields();
  renderCandidateNav();
  renderCandidateWorkspace();
  renderSummary();
}
$("#save-draft").addEventListener("click", saveDraft);
$("#validate").addEventListener("click", () => postJson("/api/validate"));
$("#save").addEventListener("click", () => postJson("/api/save"));
render();
"""
