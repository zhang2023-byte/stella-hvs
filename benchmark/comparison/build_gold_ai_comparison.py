#!/usr/bin/env python3
"""Build the expert-vs-AI benchmark comparison page.

This post-gold diagnostic reads expert annotations plus existing AI extraction
artifacts, then writes static HTML under benchmark/comparison/. It never writes
benchmark/gold/ or benchmark/runs/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GOLD_DIR = ROOT / "benchmark" / "gold"
RUNS_DIR = ROOT / "benchmark" / "runs"
LITERATURE_DIR = ROOT / "literature"
MANIFEST_PATH = ROOT / "benchmark" / "manifest" / "sampling_manifest.json"
DEFAULT_OUTPUT = ROOT / "benchmark" / "comparison" / "index.html"

SCORED_FIELDS = {
    "observed_phase_space.ra",
    "observed_phase_space.dec",
    "observed_phase_space.distance",
    "observed_phase_space.parallax",
    "observed_phase_space.proper_motion_ra",
    "observed_phase_space.proper_motion_dec",
    "observed_phase_space.radial_velocity",
    "derived_kinematics.galactocentric_x",
    "derived_kinematics.galactocentric_y",
    "derived_kinematics.galactocentric_z",
    "derived_kinematics.galactocentric_radius",
    "derived_kinematics.galactocentric_vx",
    "derived_kinematics.galactocentric_vy",
    "derived_kinematics.galactocentric_vz",
    "derived_kinematics.tangential_velocity",
    "derived_kinematics.galactocentric_tangential_velocity",
    "derived_kinematics.galactic_rest_frame_velocity",
    "bound_assessment.escape_velocity",
    "bound_assessment.escape_velocity_ratio",
    "bound_assessment.escape_margin",
    "bound_assessment.bound_probability",
    "bound_assessment.unbound_probability",
    "bound_assessment.bound_status_metric",
}

DASH_TRANSLATION = str.maketrans(
    {
        "\u2212": "-",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\ufe63": "-",
        "\uff0d": "-",
    }
)
GAIA_RE = re.compile(r"(?:GAIA\s+)?(?:(E?DR[0-9])\s+)?([0-9]{12,})", re.I)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def repo_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def normalize_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s\-_]+", "", value.translate(DASH_TRANSLATION).strip().upper())


def parse_gaia(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = GAIA_RE.search(value.translate(DASH_TRANSLATION).upper())
    if not match:
        return None
    return (match.group(1) or "", match.group(2))


def display_gold_candidate(candidate: dict[str, Any]) -> str:
    return (
        candidate.get("paper_candidate_id")
        or candidate.get("gaia_source_id")
        or next(iter(candidate.get("aliases") or []), "")
        or "(unnamed gold candidate)"
    )


def ai_identity_values(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    identifiers = candidate.get("identifiers") or {}
    identity = candidate.get("identity") or {}
    for mapping in (identifiers, identity):
        for key in ("paper_candidate_id", "gaia_source_id", "name"):
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value)
        aliases = mapping.get("aliases")
        if isinstance(aliases, list):
            values.extend(str(item) for item in aliases if str(item).strip())
    for entry in identifiers.get("all") or []:
        if isinstance(entry, dict) and entry.get("value"):
            values.append(str(entry["value"]))
    for key in ("record_id", "id", "name"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    return values


def display_ai_candidate(candidate: dict[str, Any], index: int) -> str:
    return next(iter(ai_identity_values(candidate)), "") or f"AI candidate {index + 1}"


def identity_record(values: list[str]) -> dict[str, Any]:
    return {
        "names": {normalize_name(value) for value in values if normalize_name(value) and not parse_gaia(value)},
        "gaias": [gaia for gaia in (parse_gaia(value) for value in values) if gaia],
    }


def gold_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    values = [
        candidate.get("paper_candidate_id", ""),
        candidate.get("gaia_source_id", ""),
        *(candidate.get("aliases") or []),
    ]
    return identity_record([str(value) for value in values if str(value).strip()])


def ai_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    return identity_record(ai_identity_values(candidate))


def gaia_compatible(left: tuple[str, str], right: tuple[str, str]) -> bool:
    return left[1] == right[1] and (not left[0] or not right[0] or left[0] == right[0])


def match_candidates(gold_candidates: list[dict[str, Any]], ai_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    gold_ids = [gold_identity(candidate) for candidate in gold_candidates]
    ai_ids = [ai_identity(candidate) for candidate in ai_candidates]
    unmatched_gold = set(range(len(gold_candidates)))
    unmatched_ai = set(range(len(ai_candidates)))
    pairs: list[dict[str, Any]] = []

    def take(gold_index: int, ai_index: int, method: str, detail: str) -> None:
        unmatched_gold.discard(gold_index)
        unmatched_ai.discard(ai_index)
        pairs.append(
            {
                "gold_index": gold_index,
                "ai_index": ai_index,
                "gold_id": display_gold_candidate(gold_candidates[gold_index]),
                "ai_id": display_ai_candidate(ai_candidates[ai_index], ai_index),
                "method": method,
                "detail": detail,
            }
        )

    for gold_index in list(sorted(unmatched_gold)):
        for ai_index in list(sorted(unmatched_ai)):
            for gold_gaia in gold_ids[gold_index]["gaias"]:
                for ai_gaia in ai_ids[ai_index]["gaias"]:
                    if gaia_compatible(gold_gaia, ai_gaia):
                        take(gold_index, ai_index, "gaia_id", gold_gaia[1])
                        break
                if gold_index not in unmatched_gold:
                    break
            if gold_index not in unmatched_gold:
                break

    for gold_index in list(sorted(unmatched_gold)):
        for ai_index in list(sorted(unmatched_ai)):
            shared = gold_ids[gold_index]["names"] & ai_ids[ai_index]["names"]
            if shared:
                take(gold_index, ai_index, "alias", sorted(shared)[0])
                break

    return {
        "pairs": pairs,
        "unmatched_gold": [
            {"index": index, "display_id": display_gold_candidate(gold_candidates[index])}
            for index in sorted(unmatched_gold)
        ],
        "unmatched_ai": [
            {"index": index, "display_id": display_ai_candidate(ai_candidates[index], index)}
            for index in sorted(unmatched_ai)
        ],
    }


def quantity_has_value(quantity: Any) -> bool:
    if not isinstance(quantity, dict):
        return False
    for key in ("value", "raw_value", "range_lower", "range_upper"):
        value = quantity.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def flatten_gold_quantities(candidate: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    fields: dict[str, list[dict[str, Any]]] = {}
    for quantity in candidate.get("quantities") or []:
        field = quantity.get("field")
        if field in SCORED_FIELDS:
            fields.setdefault(field, []).append(quantity)
    return fields


def flatten_ai_quantities(candidate: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    fields: dict[str, list[dict[str, Any]]] = {}
    core = candidate.get("core") or {}
    for group in ("observed_phase_space", "derived_kinematics", "bound_assessment"):
        values = core.get(group) or {}
        if not isinstance(values, dict):
            continue
        for name, record in values.items():
            if isinstance(record, dict) and quantity_has_value(record):
                field = f"{group}.{name}"
                fields.setdefault(field, []).append(record)
    return fields


def quantity_value(quantity: dict[str, Any]) -> str:
    if quantity.get("limit_kind") == "range":
        value = f"{quantity.get('range_lower', '')} to {quantity.get('range_upper', '')}".strip()
    else:
        value = str(quantity.get("value") or "").strip()
    error = str(quantity.get("error") or "").strip()
    lower = str(quantity.get("lower_error") or "").strip()
    upper = str(quantity.get("upper_error") or "").strip()
    unit = str(quantity.get("unit") or "").strip()
    parts = [value] if value else []
    if error:
        parts.append(f"+/- {error}")
    elif lower or upper:
        parts.append(f"-{lower or '?'} +{upper or '?'}")
    if unit:
        parts.append(unit)
    return " ".join(parts) if parts else "(empty)"


def compare_candidate_quantities(gold_candidate: dict[str, Any], ai_candidate: dict[str, Any]) -> dict[str, Any]:
    gold_fields = flatten_gold_quantities(gold_candidate)
    ai_fields = flatten_ai_quantities(ai_candidate)
    rows: list[dict[str, Any]] = []
    ai_only: list[dict[str, Any]] = []
    missing = 0
    mismatch = 0

    for field in sorted(gold_fields):
        gold_values = gold_fields[field]
        ai_values = ai_fields.get(field) or []
        for index, gold_quantity in enumerate(gold_values):
            ai_quantity = ai_values[index] if index < len(ai_values) else None
            if ai_quantity is None:
                status = "AI 缺失"
                ai_value = "未提取"
                missing += 1
            else:
                gold_value = quantity_value(gold_quantity)
                ai_value = quantity_value(ai_quantity)
                status = "一致" if gold_value == ai_value else "待复核"
                if status != "一致":
                    mismatch += 1
            rows.append(
                {
                    "field": field,
                    "gold": quantity_value(gold_quantity),
                    "ai": ai_value,
                    "status": status,
                }
            )

    for field, quantities in sorted(ai_fields.items()):
        extra = quantities[len(gold_fields.get(field, [])) :]
        for quantity in extra:
            ai_only.append({"field": field, "value": quantity_value(quantity)})

    return {"rows": rows, "ai_only": ai_only, "missing": missing, "mismatch": mismatch}


def load_manifest() -> dict[str, dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return {}
    payload = read_json(MANIFEST_PATH)
    return {item.get("arxiv_id", ""): item for item in payload.get("papers") or []}


def iter_gold_sources() -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(GOLD_DIR.glob("*/annotation_*.json")):
        payload = read_json(path)
        key = (str(payload.get("arxiv_id") or path.parent.name), str(payload.get("annotator") or ""))
        seen.add(key)
        sources.append({"path": path, "payload": payload, "kind": "final_annotation"})
    for path in sorted(GOLD_DIR.glob("*/draft_*.json")):
        payload = read_json(path).get("payload") or {}
        key = (str(payload.get("arxiv_id") or path.parent.name), str(payload.get("annotator") or ""))
        if key in seen:
            continue
        sources.append({"path": path, "payload": payload, "kind": "draft_checkpoint"})
    return sources


def ai_sources_for(arxiv_id: str) -> list[dict[str, Any]]:
    sources = []
    for path in sorted(RUNS_DIR.glob(f"*/{arxiv_id}/literature_hvs_candidates.json")):
        run_id = path.parents[1].name
        sources.append({"label": f"benchmark run: {run_id}", "path": path})
    literature_path = LITERATURE_DIR / arxiv_id / "literature_hvs_candidates.json"
    if literature_path.exists():
        sources.append({"label": "literature current extraction", "path": literature_path})
    return sources


def build_comparison(source: dict[str, Any], manifest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    gold = source["payload"]
    arxiv_id = gold.get("arxiv_id") or source["path"].parent.name
    ai_source = next(iter(ai_sources_for(arxiv_id)), None)
    ai = read_json(ai_source["path"]) if ai_source else {}
    gold_candidates = gold.get("candidates") or []
    ai_candidates = ai.get("candidates") or []
    matches = match_candidates(gold_candidates, ai_candidates)
    matched_candidates = []
    missing_values = 0
    mismatches = 0
    ai_only_values = 0
    for pair in matches["pairs"]:
        quantity_comparison = compare_candidate_quantities(
            gold_candidates[pair["gold_index"]],
            ai_candidates[pair["ai_index"]],
        )
        missing_values += quantity_comparison["missing"]
        mismatches += quantity_comparison["mismatch"]
        ai_only_values += len(quantity_comparison["ai_only"])
        matched_candidates.append({**pair, "quantity_comparison": quantity_comparison})

    ai_status = (ai.get("extraction") or {}).get("status") or ai.get("status") or "unknown"
    status_match = gold.get("status") == ai_status
    entry = manifest.get(arxiv_id, {})
    return {
        "arxiv_id": arxiv_id,
        "title": (ai.get("paper") or {}).get("title") or "",
        "gold_path": repo_path(source["path"]),
        "gold_kind": source["kind"],
        "ai_source_label": ai_source["label"] if ai_source else "missing",
        "ai_source_path": repo_path(ai_source["path"]) if ai_source else "",
        "manifest": entry,
        "gold_status": gold.get("status"),
        "ai_status": ai_status,
        "status_match": status_match,
        "gold_notes": gold.get("notes") or "",
        "ai_summary": (ai.get("extraction") or {}).get("summary") or "",
        "ai_candidate_groups": ai.get("candidate_groups_considered") or [],
        "gold_candidates": gold_candidates,
        "ai_candidates": ai_candidates,
        "candidate_match": matches,
        "matched_candidates": matched_candidates,
        "summary": {
            "gold_candidates": len(gold_candidates),
            "ai_candidates": len(ai_candidates),
            "matched_candidates": len(matches["pairs"]),
            "gold_missing_in_ai": len(matches["unmatched_gold"]),
            "ai_extra_candidates": len(matches["unmatched_ai"]),
            "quantity_missing": missing_values,
            "quantity_mismatch": mismatches,
            "ai_only_quantities": ai_only_values,
            "status_mismatch": 0 if status_match else 1,
        },
    }


def build_data() -> dict[str, Any]:
    manifest = load_manifest()
    comparisons = [build_comparison(source, manifest) for source in iter_gold_sources()]
    comparisons.sort(key=lambda item: item["arxiv_id"])
    totals = {
        "papers": len({item["arxiv_id"] for item in comparisons}),
        "comparisons": len(comparisons),
        "gold_candidates": sum(item["summary"]["gold_candidates"] for item in comparisons),
        "ai_candidates": sum(item["summary"]["ai_candidates"] for item in comparisons),
        "matched_candidates": sum(item["summary"]["matched_candidates"] for item in comparisons),
        "gold_missing_in_ai": sum(item["summary"]["gold_missing_in_ai"] for item in comparisons),
        "ai_extra_candidates": sum(item["summary"]["ai_extra_candidates"] for item in comparisons),
        "quantity_mismatch": sum(item["summary"]["quantity_mismatch"] for item in comparisons),
        "quantity_missing": sum(item["summary"]["quantity_missing"] for item in comparisons),
        "ai_only_quantities": sum(item["summary"]["ai_only_quantities"] for item in comparisons),
        "status_mismatch": sum(item["summary"]["status_mismatch"] for item in comparisons),
    }
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "totals": totals,
        "comparisons": comparisons,
    }


def metric(label: str, value: Any, klass: str = "") -> str:
    class_name = f' class="metric {klass}"' if klass else ' class="metric"'
    return f'<div{class_name}><span>{esc(label)}</span><strong>{esc(value)}</strong></div>'


def issue_total(summary: dict[str, Any]) -> int:
    return (
        int(summary["gold_missing_in_ai"])
        + int(summary["ai_extra_candidates"])
        + int(summary["quantity_mismatch"])
        + int(summary["quantity_missing"])
        + int(summary["ai_only_quantities"])
        + int(summary["status_mismatch"])
    )


def verdict(summary: dict[str, Any]) -> tuple[str, str]:
    return ("clean", "Aligned") if issue_total(summary) == 0 else ("review", "Review")


def one_line_finding(item: dict[str, Any]) -> str:
    summary = item["summary"]
    if issue_total(summary) == 0:
        return "Expert and AI agree at the scored surface."
    parts = []
    candidate_delta = summary["gold_missing_in_ai"] + summary["ai_extra_candidates"]
    value_delta = (
        summary["quantity_mismatch"]
        + summary["quantity_missing"]
        + summary["ai_only_quantities"]
    )
    if summary["status_mismatch"]:
        parts.append("status differs")
    if candidate_delta:
        parts.append(f"{candidate_delta} candidate-set issue{'s' if candidate_delta != 1 else ''}")
    if value_delta:
        parts.append(f"{value_delta} quantity issue{'s' if value_delta != 1 else ''}")
    return "; ".join(parts) + "."


def stat_cell(label: str, value: Any, bad: bool = False) -> str:
    klass = " bad" if bad else ""
    return f'<span class="stat{klass}"><b>{esc(value)}</b><small>{esc(label)}</small></span>'


def render_index_html(data: dict[str, Any]) -> str:
    cards = []
    for item in data["comparisons"]:
        summary = item["summary"]
        verdict_class, verdict_text = verdict(summary)
        stats = "".join(
            [
                stat_cell("Gold", summary["gold_candidates"]),
                stat_cell("AI", summary["ai_candidates"]),
                stat_cell("Matched", summary["matched_candidates"]),
                stat_cell("Extra", summary["ai_extra_candidates"], summary["ai_extra_candidates"] > 0),
                stat_cell("Missing", summary["quantity_missing"], summary["quantity_missing"] > 0),
                stat_cell("AI-only", summary["ai_only_quantities"], summary["ai_only_quantities"] > 0),
            ]
        )
        role = item["manifest"].get("role", "")
        stratum = item["manifest"].get("stratum", "")
        cards.append(
            f'<a class="paper-row {verdict_class}" data-state="{verdict_class}" href="{esc(item["detail_href"])}">'
            f'<span class="verdict">{esc(verdict_text)}</span>'
            f'<span class="paper-main"><span class="eyebrow">{esc(role)} / {esc(stratum)}</span>'
            f'<strong>{esc(item["arxiv_id"])}</strong><em>{esc(item["title"])}</em>'
            f'<span class="finding">{esc(one_line_finding(item))}</span></span>'
            f'<span class="stat-strip">{stats}</span></a>'
        )
    clean_count = sum(1 for item in data["comparisons"] if issue_total(item["summary"]) == 0)
    review_count = len(data["comparisons"]) - clean_count
    return PAGE_TEMPLATE.format(
        title="Gold vs AI Comparison",
        body=f"""
        <section class="hero">
          <p class="eyebrow">POST-GOLD DIAGNOSTIC</p>
          <h1>Gold vs AI</h1>
          <div class="hero-metrics">
            {metric("Papers", data["totals"]["papers"])}
            {metric("Aligned", clean_count)}
            {metric("Review", review_count, "strong" if review_count else "")}
            {metric("Gold candidates", data["totals"]["gold_candidates"])}
            {metric("AI candidates", data["totals"]["ai_candidates"])}
            {metric("Missing values", data["totals"]["quantity_missing"], "strong" if data["totals"]["quantity_missing"] else "")}
          </div>
        </section>
        <section class="toolbar" aria-label="Paper filters">
          <button class="filter active" type="button" data-filter="all">All</button>
          <button class="filter" type="button" data-filter="review">Review</button>
          <button class="filter" type="button" data-filter="clean">Aligned</button>
          <span>Generated {esc(data["generated_at"])}</span>
        </section>
        <section class="paper-list">{''.join(cards)}</section>
        """,
    )


def issue_rows(item: dict[str, Any]) -> str:
    rows = []
    for missing in item["candidate_match"]["unmatched_gold"]:
        rows.append(f"<tr><td>{esc(missing['display_id'])}</td><td>candidate</td><td>Gold candidate</td><td>未匹配</td><td><span class=\"badge bad\">AI 缺失</span></td></tr>")
    for extra in item["candidate_match"]["unmatched_ai"]:
        rows.append(f"<tr><td>{esc(extra['display_id'])}</td><td>candidate</td><td>Gold 未记录</td><td>AI candidate</td><td><span class=\"badge bad\">AI-only</span></td></tr>")
    for match in item["matched_candidates"]:
        for row in match["quantity_comparison"]["rows"]:
            if row["status"] != "一致":
                rows.append(f"<tr><td>{esc(match['gold_id'])}</td><td class=\"field\">{esc(row['field'])}</td><td>{esc(row['gold'])}</td><td>{esc(row['ai'])}</td><td><span class=\"badge bad\">{esc(row['status'])}</span></td></tr>")
        for row in match["quantity_comparison"]["ai_only"]:
            rows.append(f"<tr><td>{esc(match['gold_id'])}</td><td class=\"field\">{esc(row['field'])}</td><td>Gold 未记录</td><td>{esc(row['value'])}</td><td><span class=\"badge bad\">AI-only</span></td></tr>")
    return "".join(rows) or '<tr><td colspan="5">无候选或数值差异。</td></tr>'


def details_block(title: str, summary: str, body: str) -> str:
    return f"""
    <details class="fold">
      <summary><span>{esc(title)}</span><b>{esc(summary)}</b></summary>
      <div class="fold-body">{body}</div>
    </details>
    """


def render_detail_html(item: dict[str, Any]) -> str:
    summary = item["summary"]
    verdict_class, verdict_text = verdict(summary)
    matched = "".join(
        f"<li>{esc(match['gold_id'])} ↔ {esc(match['ai_id'])} <span class=\"muted\">({esc(match['method'])}: {esc(match['detail'])})</span></li>"
        for match in item["matched_candidates"]
    ) or "<li>无匹配候选。</li>"
    ai_groups = "".join(
        f"<li><code>{esc(group.get('group_id', ''))}</code>: <strong>{esc(group.get('decision', ''))}</strong>. {esc(group.get('reason', ''))}</li>"
        for group in item["ai_candidate_groups"]
    ) or "<li>AI 未记录 candidate_groups_considered。</li>"
    issue_count = issue_total(summary)
    issue_table = f'<table class="issue-table"><thead><tr><th>候选</th><th>字段</th><th>专家 gold</th><th>AI</th><th>差异</th></tr></thead><tbody>{issue_rows(item)}</tbody></table>'
    body = f"""
    <section class="detail-hero {verdict_class}">
      <a class="back" href="../index.html">Back</a>
      <p class="eyebrow">PAPER DIAGNOSTIC</p>
      <h1>{esc(item["arxiv_id"])}</h1>
      <p class="title">{esc(item["title"])}</p>
      <span class="verdict hero-verdict">{esc(verdict_text)}</span>
      <p class="finding-large">{esc(one_line_finding(item))}</p>
    </section>
    <section class="detail-grid">
      {metric("Gold candidates", summary["gold_candidates"])}
      {metric("AI candidates", summary["ai_candidates"])}
      {metric("Matched", summary["matched_candidates"])}
      {metric("AI extra", summary["ai_extra_candidates"], "strong" if summary["ai_extra_candidates"] else "")}
      {metric("Missing values", summary["quantity_missing"], "strong" if summary["quantity_missing"] else "")}
      {metric("AI-only values", summary["ai_only_quantities"], "strong" if summary["ai_only_quantities"] else "")}
    </section>
    <section class="source-strip">
      <span>Expert <code>{esc(item["gold_path"])}</code></span>
      <span>AI <code>{esc(item["ai_source_path"])}</code></span>
      <span>Status <code>{esc(item["gold_status"])}</code> / <code>{esc(item["ai_status"])}</code></span>
    </section>
    <section class="folds">
      {details_block("Differences", f"{issue_count} item(s)", issue_table)}
      {details_block("Matched candidates", f"{len(item["matched_candidates"])} match(es)", f"<ul>{matched}</ul>")}
      {details_block("Expert notes", item["gold_kind"], f"<pre>{esc(item["gold_notes"])}</pre>")}
      {details_block("AI summary", item["ai_source_label"], f"<pre>{esc(item["ai_summary"])}</pre>")}
      {details_block("AI candidate groups", f"{len(item["ai_candidate_groups"])} group(s)", f"<ul>{ai_groups}</ul>")}
    </section>
    """
    return PAGE_TEMPLATE.format(title=f"{item['arxiv_id']} Gold vs AI", body=body)


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --black: #000;
      --night: #0a0a0a;
      --ink: #141414;
      --muted: #5a5a5f;
      --line: #d8d8de;
      --line-dark: #3a3a3f;
      --panel: #fff;
      --cool: #f0f0fa;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--panel);
      color: var(--ink);
      font-family: D-DIN, "Arial Narrow", Arial, Verdana, sans-serif;
      font-size: 16px;
      line-height: 1.5;
      letter-spacing: 0;
    }}
    main {{ min-height: 100vh; }}
    a {{ color: inherit; text-decoration: none; }}
    h1 {{
      margin: 0;
      color: inherit;
      font-family: D-DIN-Bold, "Arial Narrow", Arial, Verdana, sans-serif;
      font-size: clamp(40px, 7vw, 76px);
      font-weight: 700;
      line-height: 0.96;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 18px;
      line-height: 1.2;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    code {{
      padding: 2px 5px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: var(--cool);
      color: var(--ink);
      font-size: 13px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: D-DIN, "Arial Narrow", Arial, Verdana, sans-serif;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .hero, .detail-hero {{
      background: var(--black);
      color: #fff;
      padding: 32px;
    }}
    .hero {{
      min-height: 42vh;
      display: grid;
      align-content: end;
      gap: 28px;
    }}
    .detail-hero {{
      position: relative;
      min-height: 34vh;
      display: grid;
      align-content: end;
      gap: 10px;
      border-bottom: 1px solid var(--line-dark);
    }}
    .back {{
      position: absolute;
      top: 24px;
      left: 32px;
      border: 1px solid #fff;
      border-radius: 32px;
      padding: 12px 18px;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      transition: background .18s ease, color .18s ease, transform .18s ease;
    }}
    .back:hover {{ background: #fff; color: #000; transform: translateY(-1px); }}
    .eyebrow {{
      margin: 0;
      color: currentColor;
      opacity: .68;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .title {{
      max-width: 920px;
      margin: 0;
      color: inherit;
      opacity: .78;
    }}
    .hero-metrics, .detail-grid {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      border-top: 1px solid currentColor;
      border-left: 1px solid currentColor;
    }}
    .metric {{
      min-height: 82px;
      padding: 14px 16px;
      border-right: 1px solid currentColor;
      border-bottom: 1px solid currentColor;
      color: inherit;
    }}
    .metric span {{
      display: block;
      opacity: .66;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .metric strong {{
      display: block;
      margin-top: 6px;
      font-size: 30px;
      line-height: 1;
    }}
    .metric.strong {{ background: var(--ink); color: #fff; }}
    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 14px 32px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, .94);
      backdrop-filter: blur(12px);
    }}
    .toolbar span {{ margin-left: auto; color: var(--muted); font-size: 13px; }}
    .filter {{
      min-height: 44px;
      border: 1px solid var(--ink);
      border-radius: 32px;
      background: #fff;
      color: var(--ink);
      padding: 0 18px;
      font: inherit;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      cursor: pointer;
      transition: background .18s ease, color .18s ease, transform .18s ease;
    }}
    .filter:hover, .filter.active {{ background: var(--black); color: #fff; transform: translateY(-1px); }}
    .paper-list {{ padding: 24px 32px 56px; }}
    .paper-row {{
      display: grid;
      grid-template-columns: 104px minmax(240px, 1fr) minmax(360px, 44%);
      gap: 18px;
      align-items: stretch;
      min-height: 122px;
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 12px;
      background: #fff;
      overflow: hidden;
      transition: border-color .18s ease, transform .18s ease, background .18s ease;
    }}
    .paper-row:hover {{ border-color: var(--ink); transform: translateY(-2px); }}
    .paper-row.hidden {{ display: none; }}
    .verdict {{
      display: grid;
      place-items: center;
      padding: 16px 10px;
      background: var(--black);
      color: #fff;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .paper-row.clean .verdict {{ background: #fff; color: #000; border-right: 1px solid var(--line); }}
    .paper-main {{
      display: grid;
      align-content: center;
      gap: 5px;
      min-width: 0;
      padding: 16px 0;
    }}
    .paper-main strong {{
      font-size: 26px;
      line-height: 1;
      text-transform: uppercase;
    }}
    .paper-main em {{
      overflow: hidden;
      color: var(--muted);
      font-style: normal;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .finding {{ color: var(--ink); font-size: 14px; }}
    .stat-strip {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      border-left: 1px solid var(--line);
    }}
    .stat {{
      display: grid;
      align-content: center;
      gap: 3px;
      min-width: 0;
      padding: 10px;
      border-left: 1px solid var(--line);
    }}
    .stat:first-child {{ border-left: 0; }}
    .stat b {{ font-size: 22px; line-height: 1; }}
    .stat small {{ color: var(--muted); font-size: 10px; font-weight: 700; text-transform: uppercase; }}
    .stat.bad {{ background: var(--cool); color: var(--black); }}
    .hero-verdict {{
      position: absolute;
      right: 32px;
      top: 28px;
      min-width: 104px;
      min-height: 44px;
      border: 1px solid #fff;
      border-radius: 32px;
      background: transparent;
    }}
    .detail-hero.review .hero-verdict {{ background: #fff; color: #000; }}
    .finding-large {{ max-width: 860px; margin: 12px 0 0; font-size: 20px; }}
    .detail-grid {{
      margin: 0;
      padding: 0 32px;
      border-color: var(--line);
    }}
    .detail-grid .metric {{ border-color: var(--line); color: var(--ink); }}
    .source-strip {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 18px;
      padding: 18px 32px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
    }}
    .folds {{ padding: 24px 32px 56px; }}
    .fold {{
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 12px;
      background: #fff;
      overflow: hidden;
    }}
    .fold summary {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 58px;
      padding: 0 18px;
      cursor: pointer;
      list-style: none;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .fold summary::-webkit-details-marker {{ display: none; }}
    .fold summary::after {{
      content: "+";
      display: grid;
      place-items: center;
      width: 28px;
      height: 28px;
      border: 1px solid var(--ink);
      border-radius: 50%;
      margin-left: 14px;
      transition: transform .18s ease;
    }}
    .fold[open] summary::after {{ content: "-"; transform: rotate(180deg); }}
    .fold summary b {{ margin-left: auto; color: var(--muted); font-size: 12px; }}
    .fold-body {{
      border-top: 1px solid var(--line);
      padding: 18px;
      animation: foldIn .18s ease-out;
      overflow-x: auto;
    }}
    .issue-table td:nth-child(2) {{
      font-family: D-DIN, "Arial Narrow", Arial, Verdana, sans-serif;
      font-size: 13px;
      color: var(--muted);
    }}
    .badge {{
      display: inline-block;
      border: 1px solid var(--ink);
      border-radius: 32px;
      padding: 3px 9px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .badge.bad {{ background: var(--black); color: #fff; }}
    .muted {{ color: var(--muted); }}
    @keyframes foldIn {{
      from {{ opacity: 0; transform: translateY(-4px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    @media (max-width: 980px) {{
      .hero-metrics, .detail-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .paper-row {{ grid-template-columns: 86px 1fr; }}
      .stat-strip {{ grid-column: 1 / -1; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid var(--line); border-left: 0; }}
      .stat:nth-child(4) {{ border-left: 0; }}
    }}
    @media (max-width: 640px) {{
      .hero, .detail-hero {{ padding: 24px 18px; }}
      .toolbar, .paper-list, .folds, .source-strip {{ padding-left: 18px; padding-right: 18px; }}
      .toolbar {{ align-items: stretch; flex-wrap: wrap; }}
      .toolbar span {{ width: 100%; margin-left: 0; }}
      .hero-metrics, .detail-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); padding-left: 18px; padding-right: 18px; }}
      .paper-row {{ grid-template-columns: 1fr; }}
      .verdict {{ min-height: 44px; }}
      .paper-main {{ padding: 16px; }}
      .hero-verdict {{ position: static; justify-self: start; margin-top: 12px; }}
    }}
  </style>
</head>
<body><main>{body}</main>
<script>
  const filters = document.querySelectorAll('.filter');
  const rows = document.querySelectorAll('.paper-row');
  filters.forEach((button) => {{
    button.addEventListener('click', () => {{
      filters.forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      const mode = button.dataset.filter;
      rows.forEach((row) => {{
        const visible = mode === 'all' || row.dataset.state === mode;
        row.classList.toggle('hidden', !visible);
      }});
    }});
  }});
</script>
</body>
</html>
"""


def detail_filename(index: int, item: dict[str, Any]) -> str:
    suffix = "-draft" if item["gold_kind"] == "draft_checkpoint" else ""
    return f"{index:02d}-{item['arxiv_id']}{suffix}.html"


def clean_html(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def write_site(index_path: Path, data: dict[str, Any]) -> list[Path]:
    pages_dir = index_path.parent / "papers"
    pages_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, item in enumerate(data["comparisons"], start=1):
        filename = detail_filename(index, item)
        item["detail_href"] = f"papers/{filename}"
        detail_path = pages_dir / filename
        detail_path.write_text(clean_html(render_detail_html(item)), encoding="utf-8")
        written.append(detail_path)
    index_path.write_text(clean_html(render_index_html(data)), encoding="utf-8")
    return [index_path, *written]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    data = build_data()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = write_site(args.output, data)
    print("Wrote")
    for path in written:
        print(f"- {repo_path(path)}")
    print(json.dumps(data["totals"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
