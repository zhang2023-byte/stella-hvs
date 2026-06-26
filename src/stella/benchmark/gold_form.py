"""Local browser form for benchmark expert gold annotations.

This module is part of the human annotation workflow: it writes expert-filled
YAML under benchmark/gold/ and emits the JSON twin through the same Pydantic
schema used by scripts/upgrade_gold_annotation.py. It intentionally serves a
local form only; paper reading stays outside the app, from the PDF.
"""

from __future__ import annotations

import html
import json
import os
import re
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
    GOLD_SCHEMA_VERSION,
    SCORED_QUANTITY_FIELDS,
    GoldAnnotation,
    compact_annotation_document,
    lint_annotation,
)
from stella.lit.schema_specs import LITERATURE_HVS_LIMIT_KINDS

ARXIV_ID_RE = re.compile(r"^[0-9]{4}\.[0-9]{4,5}$")
ANNOTATOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAX_REQUEST_BYTES = 2_000_000
DRAFT_SCHEMA = "stella.benchmark_gold_form_draft.v0.1"


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
    value = str(arxiv_id or "").strip()
    if not ARXIV_ID_RE.fullmatch(value):
        raise GoldFormError(f"invalid arxiv_id: {arxiv_id!r}")
    return value


def validate_annotator(annotator: str) -> str:
    value = str(annotator or "").strip()
    if not ANNOTATOR_RE.fullmatch(value):
        raise GoldFormError(f"invalid annotator: {annotator!r}")
    return value


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


def blind_manifest_papers(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in manifest_papers(manifest) if entry.get("role") == "blind"]


def ensure_blind_manifest_paper(manifest_path: Path, arxiv_id: str) -> None:
    safe_arxiv_id = validate_arxiv_id(arxiv_id)
    manifest = read_manifest(manifest_path.expanduser())
    entry = manifest_entry(manifest, safe_arxiv_id)
    if entry is None:
        raise GoldFormError(f"{safe_arxiv_id} is not in the sampling manifest")
    if entry.get("role") != "blind":
        raise GoldFormError(
            f"{safe_arxiv_id} is role={entry.get('role')!r}; "
            "this form only handles blind-role annotations"
        )


def guideline_version(workspace: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
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
        "schema_version": GOLD_SCHEMA_VERSION,
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
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "document": document,
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
    if not isinstance(document, dict):
        raise GoldFormError("validated annotation is missing")
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
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "valid": True,
        "warnings": result["warnings"],
        "yaml_path": str(yaml_path),
        "json_path": str(json_path),
        "document": document,
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
        "draft_schema": DRAFT_SCHEMA,
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
        "role": entry.get("role", ""),
        "overlap": entry.get("overlap", False),
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
        for entry in blind_manifest_papers(manifest)
    ]
    selected_arxiv_id = config.arxiv_id.strip()
    if selected_arxiv_id:
        entry = manifest_entry(manifest, selected_arxiv_id)
        if entry is None or entry.get("role") != "blind":
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
            "manifest_role": entry.get("role", "") if entry else "",
            "manifest_overlap": entry.get("overlap", False) if entry else False,
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
                    ensure_blind_manifest_paper(
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
                    ensure_blind_manifest_paper(
                        config.manifest_path,
                        str(payload.get("arxiv_id", "")),
                    )
                    saved = save_draft(payload, config.gold_dir)
                    json_response(self, HTTPStatus.OK, saved)
                    return
                if self.path == "/api/save":
                    ensure_blind_manifest_paper(
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
    <div>
      <p class="eyebrow">STELLA BENCHMARK</p>
      <h1>Gold Annotation</h1>
    </div>
    <div id="meta" class="meta-grid"></div>
  </header>
  <main class="layout">
    <section class="editor">
      <div id="paper-picker"></div>
      <div id="document-fields"></div>
      <div id="candidate-list"></div>
    </section>
    <aside class="side-panel">
      <div class="panel-title">
        <p class="eyebrow-light">CHECKPOINT</p>
        <h2>Draft or validate</h2>
      </div>
      <div class="action-row">
        <button id="save-draft" type="button" class="subtle">Save Draft</button>
        <button id="validate" type="button">Validate</button>
        <button id="save" type="button" class="primary">Save</button>
      </div>
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
"""


_PAGE_JS = r"""
const state = JSON.parse(document.getElementById("bootstrap").textContent);
let payload = structuredClone(state.payload);

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
function emptyQuantity() {
  return {
    field: firstField, value: "", error: "", lower_error: "", upper_error: "",
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
    schema_version: state.payload.schema_version,
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
function syncSelected() {
  state.selected.arxiv_id = payload.arxiv_id || "";
  state.selected.annotator = payload.annotator || "";
  const paper = state.papers.find((item) => item.arxiv_id === payload.arxiv_id);
  state.selected.manifest_role = paper ? paper.role : "";
  state.selected.manifest_overlap = paper ? paper.overlap : false;
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
    ["role", state.selected.manifest_role || "blind only"],
    ["overlap", String(Boolean(state.selected.manifest_overlap))],
    ["gold", state.selected.gold_exists ? "exists" : "none"],
    ["draft", state.selected.draft_exists ? "exists" : "none"],
    ["PDF", state.selected.pdf_path || "select a paper"]
  ];
  $("#meta").replaceChildren(...items.map(([label, value]) =>
    el("div", { class: "meta-item" }, [el("span", { text: label }), el("strong", { text: value })])
  ));
}
function goldWarning() {
  if (!state.selected.gold_exists) return null;
  const files = (state.selected.gold_files || []).join(", ");
  return el("div", {
    class: "gold-warning",
    text: `Existing gold artifacts found for this blind paper: ${files}. Saving with the same annotator will overwrite that annotator's YAML/JSON.`
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
  paperSelect.append(el("option", { value: "", text: "Select blind paper" }));
  for (const paper of state.papers) {
    const goldStatus = paper.gold_exists ? "gold exists" : "no gold";
    const draftStatus = (
      paper.draft_annotator === payload.annotator && paper.draft_exists
    ) ? "draft exists" : "no draft";
    const label = [
      paper.arxiv_id,
      "blind",
      `overlap=${Boolean(paper.overlap)}`,
      paper.legacy_status || "unknown",
      goldStatus,
      draftStatus,
    ].join(" - ");
    const opt = el("option", { value: paper.arxiv_id, text: label });
    if (paper.arxiv_id === payload.arxiv_id) opt.selected = true;
    paperSelect.append(opt);
  }
  const warning = goldWarning();
  const draft = draftNotice();
  const section = el("div", { class: "section" }, [
    el("div", { class: "section-header" }, [el("h2", { text: "Paper" })]),
      el("div", { class: "section-body" }, [
      el("label", {}, [document.createTextNode("blind paper"), paperSelect]),
      warning || el("div"),
      draft || el("div"),
      el("div", { class: "grid" }, [
        input("arxiv_id", payload.arxiv_id, (value) => { payload.arxiv_id = value; updateOnly(); }, "text", examples.arxiv_id),
      ])
    ])
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
  const section = el("div", { class: "section" }, [
    el("div", { class: "section-header" }, [el("h2", { text: "Document" }), status]),
    el("div", { class: "section-body" }, [
      el("div", { class: "grid three" }, [
        input("annotator", payload.annotator, (value) => { payload.annotator = value; updateOnly(); }, "text", examples.annotator),
        input("annotated_at", payload.annotated_at, (value) => { payload.annotated_at = value; updateOnly(); }, "text", examples.annotated_at),
        input("guideline_version", payload.guideline_version, (value) => { payload.guideline_version = value; updateOnly(); }, "text", examples.guideline_version),
      ]),
      textarea("notes", payload.notes, (value) => { payload.notes = value; updateOnly(); }, examples.document_notes)
    ])
  ]);
  $("#document-fields").replaceChildren(section);
}
function renderEvidenceList(items, onChange) {
  const rows = items.map((evidence, index) =>
    el("div", { class: "evidence-row" }, [
      input("location", evidence.location, (value) => { evidence.location = value; onChange(); }, "text", examples.evidence_location),
      input("quote", evidence.quote, (value) => { evidence.quote = value; onChange(); }, "text", examples.evidence_quote),
      el("button", { type: "button", class: "danger", text: "Remove", onclick: () => { items.splice(index, 1); onChange(true); } })
    ])
  );
  rows.push(el("button", { type: "button", class: "subtle", text: "Add Evidence", onclick: () => { items.push(emptyEvidence()); onChange(true); } }));
  return el("div", {}, rows);
}
function renderQuantity(candidate, quantity, qIndex) {
  const rangeClass = quantity.limit_kind === "range" ? "grid" : "grid hidden";
  const exactClass = quantity.limit_kind === "range" ? "grid hidden" : "grid";
  return el("div", { class: "quantity" }, [
    el("div", { class: "section-header" }, [
      el("h3", { text: `Quantity ${qIndex + 1}` }),
      el("button", { type: "button", class: "danger", text: "Delete", onclick: () => {
        candidate.quantities.splice(qIndex, 1);
        render();
      }})
    ]),
    el("div", { class: "grid" }, [
      quantitySelect(quantity),
      select("limit_kind", quantity.limit_kind, state.options.limit_kinds, (value) => { quantity.limit_kind = value; render(); })
    ]),
    el("div", { class: exactClass }, [
      input("value", quantity.value, (value) => { quantity.value = value; updateOnly(); }, "text", examples.value),
      input("unit", quantity.unit, (value) => { quantity.unit = value; updateOnly(); }, "text", examples.unit)
    ]),
    el("div", { class: rangeClass }, [
      input("range_lower", quantity.range_lower, (value) => { quantity.range_lower = value; updateOnly(); }, "text", examples.range_lower),
      input("range_upper", quantity.range_upper, (value) => { quantity.range_upper = value; updateOnly(); }, "text", examples.range_upper)
    ]),
    el("div", { class: "grid three" }, [
      input("error", quantity.error, (value) => { quantity.error = value; updateOnly(); }, "text", examples.error),
      input("lower_error", quantity.lower_error, (value) => { quantity.lower_error = value; updateOnly(); }, "text", examples.lower_error),
      input("upper_error", quantity.upper_error, (value) => { quantity.upper_error = value; updateOnly(); }, "text", examples.upper_error)
    ]),
    renderEvidenceList(quantity.evidence, (rerender) => rerender ? render() : updateOnly()),
    textarea("quantity notes", quantity.notes, (value) => { quantity.notes = value; updateOnly(); }, examples.quantity_notes)
  ]);
}
function renderCandidate(candidate, index) {
  const aliases = (candidate.aliases || []).join("\n");
  const quantities = candidate.quantities || [];
  return el("div", { class: "section" }, [
    el("div", { class: "section-header" }, [
      el("h2", { text: `Candidate ${index + 1}` }),
      el("div", {}, [
        el("button", { type: "button", class: "subtle", text: "Copy", onclick: () => {
          payload.candidates.splice(index + 1, 0, structuredClone(candidate));
          render();
        }}),
        el("button", { type: "button", class: "danger", text: "Delete", onclick: () => {
          payload.candidates.splice(index, 1);
          render();
        }})
      ])
    ]),
    el("div", { class: "section-body" }, [
      el("div", { class: "grid" }, [
        input("paper_candidate_id", candidate.paper_candidate_id, (value) => { candidate.paper_candidate_id = value; updateOnly(); }, "text", examples.paper_candidate_id),
        input("gaia_source_id", candidate.gaia_source_id, (value) => { candidate.gaia_source_id = value; updateOnly(); }, "text", examples.gaia_source_id)
      ]),
      el("div", { class: "grid" }, [
        textarea("aliases, one per line", aliases, (value) => { candidate.aliases = value.split(/\n/).map((item) => item.trim()).filter(Boolean); updateOnly(); }, examples.aliases),
        select("origin_type", candidate.origin_type, state.options.origin_types, (value) => { candidate.origin_type = value; updateOnly(); })
      ]),
      renderEvidenceList(candidate.evidence, (rerender) => rerender ? render() : updateOnly()),
      ...quantities.map((quantity, qIndex) => renderQuantity(candidate, quantity, qIndex)),
      el("button", { type: "button", class: "subtle", text: "Add Quantity", onclick: () => {
        candidate.quantities.push(emptyQuantity());
        render();
      }}),
      textarea("candidate notes", candidate.notes, (value) => { candidate.notes = value; updateOnly(); }, examples.candidate_notes)
    ])
  ]);
}
function renderCandidates() {
  const root = $("#candidate-list");
  if (payload.status === "no_candidates") {
    root.replaceChildren();
    return;
  }
  const sections = (payload.candidates || []).map(renderCandidate);
  sections.push(el("button", { type: "button", class: "primary", text: "Add Candidate", onclick: () => {
    payload.candidates.push(emptyCandidate());
    render();
  }}));
  root.replaceChildren(...sections);
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
  render();
  showMessages({
    valid: true,
    message: "Started a fresh blank form. The draft file was not changed."
  });
}
function updateOnly() {
  renderMeta();
}
function render() {
  renderMeta();
  renderPicker();
  renderDocumentFields();
  renderCandidates();
}
$("#save-draft").addEventListener("click", saveDraft);
$("#validate").addEventListener("click", () => postJson("/api/validate"));
$("#save").addEventListener("click", () => postJson("/api/save"));
render();
"""
