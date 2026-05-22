"""Build HTML-facing view data for the object-level HVS catalog."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any


OBJECT_SCHEMA_VERSION = "stella.hvs_candidate_catalog.object.v1"
INDEX_JSON_FILENAME = "hvs_candidates_index.json"

OBSERVED_FIELDS = (
    "ra",
    "dec",
    "parallax",
    "proper_motion_ra",
    "proper_motion_dec",
    "radial_velocity",
)

DERIVED_FIELDS = ("total_velocity",)
PROBABILITY_FIELDS = ("unbound_probability",)

FIELD_LABELS = {
    "ra": "RA",
    "dec": "Dec",
    "parallax": "plx",
    "proper_motion_ra": "pmRA",
    "proper_motion_dec": "pmDec",
    "radial_velocity": "RV",
    "total_velocity": "total velocity",
    "unbound_probability": "P(unbound)",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def quantity_text(quantity: Any) -> str:
    """Render a compact value string for index cells, with units kept in headers."""
    if not isinstance(quantity, dict):
        return ""
    value = str(quantity.get("value") or "").strip()
    if not value:
        return ""
    text = value
    error = str(quantity.get("error") or "").strip()
    lower = str(quantity.get("lower_error") or "").strip()
    upper = str(quantity.get("upper_error") or "").strip()
    if error:
        text = f"{text} ± {error}"
    elif lower or upper:
        lower_text = lower if lower.startswith(("-", "+")) else f"-{lower or '?'}"
        upper_text = upper if upper.startswith(("-", "+")) else f"+{upper or '?'}"
        text = f"{text} {lower_text} {upper_text}"
    return text


def candidate_for_source(record: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    for candidate in record.get("candidates") or []:
        if isinstance(candidate, dict) and candidate.get("source") == source_id:
            return candidate
    return None


def source_summary(record: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Extract source-specific index quantities without merging across papers."""
    source_id = str(source.get("source") or "")
    candidate = candidate_for_source(record, source_id) or {}
    core = candidate.get("core") if isinstance(candidate.get("core"), dict) else {}
    observed = core.get("observed_phase_space") if isinstance(core.get("observed_phase_space"), dict) else {}
    derived = core.get("derived_kinematics") if isinstance(core.get("derived_kinematics"), dict) else {}
    bound_assessment = core.get("bound_assessment") if isinstance(core.get("bound_assessment"), dict) else {}
    paper = source.get("paper") if isinstance(source.get("paper"), dict) else {}
    return {
        "source": source_id,
        "record_id": str(source.get("record_id") or ""),
        "paper_candidate_id": str(source.get("paper_candidate_id") or ""),
        "gaia_source_id": str(source.get("gaia_source_id") or ""),
        "arxiv_id": str(paper.get("arxiv_id") or ""),
        "bibcode": str(paper.get("bibcode") or ""),
        "phase_space": {field: quantity_text(observed.get(field)) for field in OBSERVED_FIELDS},
        "total_velocity": quantity_text(derived.get("total_velocity")),
        "unbound_probability": quantity_text(bound_assessment.get("unbound_probability")),
    }


def build_index_row(record: dict[str, Any]) -> dict[str, Any]:
    canonical = record.get("canonical_identifier") if isinstance(record.get("canonical_identifier"), dict) else {}
    sources = [source for source in record.get("sources") or [] if isinstance(source, dict)]
    source_rows = [source_summary(record, source) for source in sources]
    bibcodes = []
    for source in source_rows:
        bibcode = source.get("bibcode") or ""
        if bibcode and bibcode not in bibcodes:
            bibcodes.append(bibcode)
    gaia_ids = []
    paper_ids = []
    for source in source_rows:
        gaia_id = source.get("gaia_source_id") or ""
        paper_id = source.get("paper_candidate_id") or ""
        if gaia_id and gaia_id not in gaia_ids:
            gaia_ids.append(gaia_id)
        if paper_id and paper_id not in paper_ids:
            paper_ids.append(paper_id)
    return {
        "object_id": str(record.get("object_id") or ""),
        "identifier": str(canonical.get("value") or record.get("object_id") or ""),
        "identifier_kind": str(canonical.get("kind") or ""),
        "gaia_source_ids": gaia_ids,
        "paper_candidate_ids": paper_ids,
        "bibcodes": bibcodes,
        "sources": source_rows,
        "source_count": len(source_rows),
        "warning_count": len((record.get("merge") or {}).get("warnings") or [])
        if isinstance(record.get("merge"), dict)
        else 0,
    }


def method_lineage(steps: list[dict[str, Any]], method_refs: list[str]) -> dict[str, list[str]]:
    """Return direct method refs, recursive ancestors, and highlighted edges."""
    by_id = {str(step.get("id") or ""): step for step in steps if isinstance(step, dict)}
    direct = [step_id for step_id in method_refs if step_id in by_id]
    ancestors: set[str] = set()
    edges: set[tuple[str, str]] = set()

    def visit(step_id: str) -> None:
        step = by_id.get(step_id)
        if not step:
            return
        for dep in step.get("depends_on") or []:
            dep_id = str(dep)
            if dep_id not in by_id:
                continue
            edges.add((dep_id, step_id))
            if dep_id not in ancestors and dep_id not in direct:
                ancestors.add(dep_id)
            visit(dep_id)

    for step_id in direct:
        visit(step_id)
    return {
        "direct": direct,
        "ancestors": sorted(ancestors),
        "edges": [f"{left}->{right}" for left, right in sorted(edges)],
    }


def load_catalog_snapshot(catalog_dir: Path) -> dict[str, Any]:
    """Load index and object JSON files into a static-site snapshot."""
    catalog_dir = catalog_dir.expanduser()
    index_path = catalog_dir / INDEX_JSON_FILENAME
    index_record = read_json(index_path) if index_path.exists() else {}

    records: list[dict[str, Any]] = []
    for path in sorted(catalog_dir.glob("*.json")):
        if path.name == INDEX_JSON_FILENAME:
            continue
        payload = read_json(path)
        if payload.get("schema_version") == OBJECT_SCHEMA_VERSION:
            records.append(payload)

    order = [
        str(item.get("object_id") or "")
        for item in index_record.get("objects") or []
        if isinstance(item, dict) and item.get("object_id")
    ]
    order_index = {object_id: index for index, object_id in enumerate(order)}
    records.sort(key=lambda record: (order_index.get(str(record.get("object_id") or ""), len(order_index)), str(record.get("object_id") or "")))

    rows = [build_index_row(record) for record in records]
    summary = index_record.get("summary") if isinstance(index_record.get("summary"), dict) else {}
    if not summary:
        summary = {
            "object_count": len(records),
            "source_count": sum(len(record.get("sources") or []) for record in records),
            "candidate_count": sum(len(record.get("candidates") or []) for record in records),
            "objects_with_gaia_count": sum(1 for row in rows if row.get("gaia_source_ids")),
            "warning_count": sum(int(row.get("warning_count") or 0) for row in rows),
            "skipped_count": 0,
        }

    return {
        "schema_version": "stella.hvs_catalog_site.snapshot.v1",
        "summary": summary,
        "index": index_record,
        "rows": rows,
        "objects": records,
        "field_labels": FIELD_LABELS,
    }


def json_script_payload(payload: dict[str, Any]) -> str:
    """Serialize JSON for direct inclusion in a script tag."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _asset_data_uri(path: Path, mime_type: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def inline_css(css_path: Path, *, hero_path: Path | None = None) -> str:
    css = css_path.read_text(encoding="utf-8")
    if hero_path is not None and hero_path.exists():
        css = css.replace("url(\"stella-hero.svg\")", f"url(\"{_asset_data_uri(hero_path, 'image/svg+xml')}\")")
    return css


def render_live_index_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stella HVS Catalog</title>
  <link rel="stylesheet" href="assets/stella.css">
</head>
<body data-catalog-root="../../catalog">
  <div id="app" class="app-shell" aria-live="polite"></div>
  <script src="assets/catalog-viewer.js"></script>
</body>
</html>
"""


def render_static_index_html(snapshot: dict[str, Any], *, css: str, js: str) -> str:
    payload = json_script_payload(snapshot)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stella HVS Catalog Snapshot</title>
  <style>
{css}
  </style>
</head>
<body>
  <div id="app" class="app-shell" aria-live="polite"></div>
  <script>
window.STELLA_CATALOG_SNAPSHOT = {payload};
  </script>
  <script>
{js}
  </script>
</body>
</html>
"""


def has_external_html_dependencies(html: str) -> bool:
    """Return True if static HTML uses external scripts, stylesheets, or remote image URLs."""
    patterns = [
        r"<script\b[^>]*\bsrc\s*=",
        r"<link\b[^>]*\bhref\s*=",
        r"<img\b[^>]*\bsrc\s*=\s*[\"']https?://",
        r"url\(\s*[\"']?https?://",
    ]
    return any(re.search(pattern, html, flags=re.IGNORECASE) for pattern in patterns)


def build_static_html(catalog_dir: Path, css_path: Path, js_path: Path, hero_path: Path | None = None) -> str:
    snapshot = load_catalog_snapshot(catalog_dir)
    css = inline_css(css_path, hero_path=hero_path)
    js = js_path.read_text(encoding="utf-8")
    return render_static_index_html(snapshot, css=css, js=js)
