"""Contribution-aware scientific web view over the contribution catalog.

Renders per-object pages from ``hvs_contribution_catalog.object`` records:
identity and identifiers, the chronological contribution timeline,
candidates_found versus follow_up, per-paper boundness, every grouped
quantity value with condition, source, preference, and evidence, and the
contribution summary. A "latest reported status" line is derived at render
time and clearly labeled as the latest paper report — never as a canonical,
authoritative, or current physical state. Conditions are never collapsed,
no value is chosen across papers, and bound reassessments stay visible.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LATEST_REPORT_DISCLAIMER = (
    "Latest reported status is the most recent paper report for this object, "
    "not a Stella truth, canonical state, or current physical state."
)

_STATUS_LABELS = {
    "unbound": "unbound (paper report)",
    "possibly_unbound": "possibly unbound (paper report)",
    "bound": "bound (paper report)",
    "no_overall_conclusion": "no overall conclusion (paper report)",
    "not_assessed": "not assessed (paper report)",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def latest_reported_status(record: dict[str, Any]) -> dict[str, Any] | None:
    """Derive the latest paper report at render time; never persist it."""

    timeline = record.get("timeline") or []
    for entry in reversed(timeline):
        boundness = entry.get("paper_boundness") or {}
        status = boundness.get("status")
        if status:
            return {"status": status, "arxiv_id": entry.get("arxiv_id")}
    return None


def _value_line(value: dict[str, Any]) -> str:
    parts: list[str] = []
    quantity = value.get("value")
    if quantity:
        text = _escape(quantity)
        error = value.get("error")
        if error:
            text += f" &plusmn; {_escape(error)}"
        parts.append(text)
    for key in ("range_lower", "range_upper"):
        if value.get(key):
            parts.append(_escape(value[key]))
    unit = value.get("unit")
    if unit:
        parts.append(f"{_escape(unit)}")
    limit = value.get("limit_kind")
    if limit and limit != "none":
        parts.append(f"[{_escape(limit)}]")
    preferred = value.get("paper_preferred")
    if preferred is True:
        parts.append("paper-preferred: yes (explicit)")
    elif preferred is False:
        parts.append("paper-preferred: no (explicit)")
    else:
        parts.append("paper-preferred: not stated")
    parts.append(f"source: {_escape(value.get('source') or '?')}")
    condition = value.get("condition")
    parts.append(f"condition: {_escape(condition) if condition else '(none stated)'}")
    source_note = value.get("source_note")
    if source_note:
        parts.append(f"source detail: {_escape(source_note)}")
    evidence_count = len(value.get("direct_evidence") or [])
    parts.append(f"direct evidence locators: {evidence_count}")
    return "; ".join(parts)


def _timeline_html(entry: dict[str, Any]) -> str:
    boundness = entry.get("paper_boundness") or {}
    status = boundness.get("status") or ""
    rows = [
        "<article class='timeline-entry'>",
        f"<h3>{_escape(entry.get('arxiv_id'))} &mdash; {_escape(entry.get('display_name') or entry.get('record_id'))}</h3>",
        f"<p><span class='type-badge type-{_escape(entry.get('contribution_type'))}'>{_escape(entry.get('contribution_type'))}</span> "
        f"<span class='status-badge status-{_escape(status)}'>{_escape(_STATUS_LABELS.get(status, status))}</span></p>",
        f"<p class='note'>{_escape(entry.get('contribution_summary') or '')}</p>",
    ]
    evidence = entry.get("contribution_evidence") or []
    rows.append(f"<p class='evidence'>contribution evidence locators: {len(evidence)}</p>")
    quantities = entry.get("quantities") or []
    if entry.get("quantity_extraction_status") == "failed":
        rows.append(
            "<p class='failure'>quantity delivery failed; no trustworthy "
            "values were delivered for this contribution</p>"
        )
    elif quantities:
        rows.append("<details open><summary>All reported values</summary><ul class='values'>")
        for group in quantities:
            rows.append(
                f"<li><strong>{_escape(group.get('quantity'))}</strong><ul>"
            )
            for value in group.get("values") or []:
                rows.append(f"<li>{_value_line(value)}</li>")
            rows.append("</ul></li>")
        rows.append("</ul></details>")
    else:
        rows.append(
            "<p class='empty-values'>no structured values reported for this "
            "contribution</p>"
        )
    rows.append("</article>")
    return "\n".join(rows)


def render_object_page(record: dict[str, Any]) -> str:
    latest = latest_reported_status(record)
    lines = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{_escape(record.get('display_name'))} — HVS contribution timeline</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:2rem;max-width:60rem}",
        ".timeline-entry{border:1px solid #ccc;border-radius:8px;padding:1rem;margin:1rem 0}",
        ".type-badge,.status-badge{display:inline-block;padding:0.15rem 0.6rem;border-radius:999px;font-size:0.85rem;margin-right:0.5rem}",
        ".type-candidates_found{background:#e8f0fe}.type-follow_up{background:#fef7e0}",
        ".status-bound{background:#fce8e6}.status-unbound{background:#e6f4ea}.status-possibly_unbound{background:#fef7e0}",
        ".note{font-style:italic}.latest{border-left:4px solid #999;padding-left:1rem}",
        "ul.values{list-style:square}li ul{list-style:circle}",
        "</style></head><body>",
        f"<h1>{_escape(record.get('display_name'))}</h1>",
        f"<p>object id: <code>{_escape(record.get('object_id'))}</code></p>",
        f"<p>identifiers: {_escape(', '.join(record.get('identifiers') or []) or '—')}</p>",
    ]
    if latest:
        lines.append(
            "<div class='latest'><strong>Latest reported status:</strong> "
            f"{_escape(_STATUS_LABELS.get(latest['status'], latest['status']))} "
            f"(reported by {_escape(latest['arxiv_id'])}). "
            f"{_escape(LATEST_REPORT_DISCLAIMER)}</div>"
        )
    lines.append("<h2>Contribution timeline (chronological by paper)</h2>")
    for entry in record.get("timeline") or []:
        lines.append(_timeline_html(entry))
    lines.append("<footer><p>" + _escape(LATEST_REPORT_DISCLAIMER) + "</p></footer>")
    lines.append("</body></html>")
    return "\n".join(lines)


def render_index(records: list[dict[str, Any]]) -> str:
    lines = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>HVS contribution timeline catalog</title>",
        "<style>body{font-family:system-ui,sans-serif;margin:2rem}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:0.4rem 0.8rem}</style>",
        "</head><body>",
        "<h1>HVS contribution timeline catalog</h1>",
        "<p>Pre-gold contribution-first view. Every object shows its complete "
        "paper-object contribution timeline; no authoritative global boundness "
        "state exists in this catalog.</p>",
        "<table><tr><th>Object</th><th>Identifiers</th><th>Contributions</th><th>Latest reported status</th></tr>",
    ]
    for record in records:
        latest = latest_reported_status(record)
        latest_text = (
            f"{latest['status']} (by {latest['arxiv_id']}) — paper report only"
            if latest
            else "—"
        )
        lines.append(
            f"<tr><td><a href='objects/{_escape(record['object_id'])}.html'>{_escape(record.get('display_name'))}</a></td>"
            f"<td>{_escape(', '.join(record.get('identifiers') or []) or '—')}</td>"
            f"<td>{len(record.get('timeline') or [])}</td>"
            f"<td>{_escape(latest_text)}</td></tr>"
        )
    lines.append("</table></body></html>")
    return "\n".join(lines)


def build_contribution_catalog_site(
    catalog_dir: Path,
    *,
    web_dir: Path,
) -> dict[str, Any]:
    """Render the index and one page per contribution-catalog object."""

    catalog_dir = Path(catalog_dir)
    web_dir = Path(web_dir)
    objects_dir = web_dir / "objects"
    objects_dir.mkdir(parents=True, exist_ok=True)
    index_record = json.loads((catalog_dir / "index.json").read_text(encoding="utf-8"))
    object_ids = [
        str(item.get("object_id") or "")
        for item in index_record.get("objects") or []
        if str(item.get("object_id") or "").startswith("hvc-")
        and Path(str(item.get("object_id") or "")).name
        == str(item.get("object_id") or "")
    ]
    records = []
    for object_id in object_ids:
        path = catalog_dir / f"{object_id}.json"
        if not path.is_file():
            raise ValueError(f"catalog index references a missing object: {object_id}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if (record.get("schema") or {}).get("name") != "hvs_contribution_catalog.object":
            continue
        records.append(record)
    records.sort(key=lambda item: str(item.get("object_id") or ""))
    written = []
    for record in records:
        page = render_object_page(record)
        path = objects_dir / f"{record['object_id']}.html"
        path.write_text(page, encoding="utf-8")
        written.append(str(path))
    current_pages = {f"{record['object_id']}.html" for record in records}
    for path in sorted(objects_dir.glob("hvc-*.html")):
        if path.name not in current_pages:
            path.unlink()
    index_path = web_dir / "index.html"
    index_path.write_text(render_index(records), encoding="utf-8")
    written.append(str(index_path))
    return {
        "object_count": len(records),
        "written": written,
        "generated_at": _utc_now(),
    }


def build_contribution_site(
    payload: dict, *, root: Path, paper_id: str | None = None
) -> dict:
    """web.build_contribution_site adapter.

    Reads only the contribution catalog (timelines), the contributions
    index, and optional validated dynamics results; writes the site into
    the requested output directory (tests use a temporary directory).
    """

    root = Path(root)
    literature = root / "literature"
    catalog_dir = literature / "hvs_contribution_catalog"
    if not (catalog_dir / "index.json").is_file():
        return {
            "status": "failed",
            "reason": "contribution catalog timelines are required before the site",
        }
    output_dir = Path(payload.get("site_output_dir") or (root / "pages" / "contributions"))
    result = build_contribution_catalog_site(catalog_dir, web_dir=output_dir)
    dynamics_dir = literature / "hvs_dynamics_results"
    result["dynamics_included"] = dynamics_dir.is_dir()
    result["output_dir"] = str(output_dir)
    result["status"] = "complete"
    return result
