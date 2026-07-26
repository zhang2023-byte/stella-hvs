#!/usr/bin/env python3
"""Build the human-readable benchmark report from scorer outputs.

Renders static HTML from scorecards under the active campaign scoring directory and the
private per-row details under ``$STELLA_GOLD_DIR/../scoring-details/``. This
replaced the standalone comparison dashboard: the report is a pure view over
the scorer's own outputs (benchmark/SCORE_SPEC.md), so the numbers on the
page and the numbers in the scorecards can never disagree.

The report covers every requested compatible formal campaign run side by side,
including canonical extraction and coding-agent baseline runs, with one index
page plus one page per gold paper.

The pages embed gold values and note text, so they are written next to the
external gold store (default: ``$STELLA_GOLD_DIR/../report/``) and the
script refuses to write inside this workspace.

Usage:
    conda run -n stella-env python scripts/build_benchmark_report.py \
        --campaign hvs-extraction-v5 \
        --run-label canonical-run-score \
        --run-label coding-baseline-score
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import sha256_file
from stella.benchmark.test_release import find_matching_release
from stella.benchmark.paths import (
    campaign_paths,
    require_external_path,
    validate_path_segment,
)
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id
from stella.schema_registry import require_schema

WORKSPACE = Path(__file__).resolve().parents[1]
GOLD_DIR_ENV = "STELLA_GOLD_DIR"
DEFAULT_PATHS = campaign_paths(WORKSPACE)
DEFAULT_SCORING_DIR = DEFAULT_PATHS.scoring
DEFAULT_CAMPAIGN = DEFAULT_PATHS.campaign_manifest
DEFAULT_RELEASES_ROOT = DEFAULT_PATHS.releases
DEFAULT_RUNS_DIR = DEFAULT_PATHS.runs

STRICT_STATUSES = {"value_match", "value_match_cross_format"}
STATUS_CLASSES = {
    "value_match": "good",
    "value_match_cross_format": "good",
    "within_gold_error": "warn",
    "value_mismatch": "bad",
    "unit_mismatch": "bad",
    "limit_kind_mismatch": "bad",
    "gold_only": "miss",
    "ai_only": "bad",
}
STATUS_LABELS = {
    "value_match": "match",
    "value_match_cross_format": "match (format bridge)",
    "within_gold_error": "within gold error",
    "value_mismatch": "value mismatch",
    "unit_mismatch": "unit mismatch",
    "limit_kind_mismatch": "limit kind mismatch",
    "gold_only": "gold only",
    "ai_only": "AI only",
}


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def fmt_rate(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.1f}%"


def fmt_ci(value: Any) -> str:
    if not value:
        return ""
    return f"[{float(value[0]) * 100:.1f}, {float(value[1]) * 100:.1f}]"


def default_gold_dir() -> Path | None:
    value = os.environ.get(GOLD_DIR_ENV, "").strip()
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render the benchmark HTML report from scorer outputs."
    )
    parser.add_argument(
        "--run-label",
        action="append",
        default=None,
        help="Scored run label (repeatable, order preserved). "
        "Default: every label under the scoring directory.",
    )
    parser.add_argument(
        "--scoring-dir",
        type=Path,
        default=DEFAULT_SCORING_DIR,
        help="Public scorecard root. Default: the active campaign scoring directory.",
    )
    parser.add_argument(
        "--details-dir",
        type=Path,
        default=None,
        help="Private details root. Default: <gold-dir>/../scoring-details/.",
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=None,
        help=f"External private gold root (for defaults). Default: ${GOLD_DIR_ENV}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output index path. Default: <gold-dir>/../report/index.html.",
    )
    parser.add_argument("--campaign-manifest", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--campaign", help="Campaign id; resolves all public benchmark paths.")
    parser.add_argument("--releases-root", type=Path, default=DEFAULT_RELEASES_ROOT)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    return parser


# --------------------------------------------------------------------------
# Data assembly (pure view over scorer outputs — no re-judgment)


def load_runs(
    labels: list[str], scoring_dir: Path, details_root: Path
) -> list[dict[str, Any]]:
    runs = []
    for label in labels:
        label = validate_path_segment(label, "run label")
        scorecard_path = scoring_dir / label / "scorecard.json"
        details_path = details_root / label / "details.json"
        if not scorecard_path.is_file():
            raise SystemExit(f"missing scorecard: {scorecard_path}")
        if not details_path.is_file():
            raise SystemExit(f"missing private details: {details_path}")
        scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
        details = json.loads(details_path.read_text(encoding="utf-8"))
        runs.append(
            {
                "label": label,
                "scorecard": scorecard,
                "papers": {
                    paper["arxiv_id"]: paper for paper in details.get("papers", [])
                },
                "details_schema": details.get("schema"),
            }
        )
    return runs


def validate_formal_cohort(
    runs: list[dict[str, Any]],
    *,
    campaign_path: Path,
    releases_root: Path,
    runs_dir: Path,
) -> None:
    """Reject legacy cards and any mixed campaign/split/gold-snapshot cohort."""

    if not runs:
        raise ValueError("report requires at least one current scorecard")
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    expected_campaign = {
        "campaign_id": campaign.get("campaign_id"),
        "sha256": sha256_file(campaign_path),
    }
    cohort: tuple[str, str, str] | None = None
    for run in runs:
        card = run["scorecard"]
        try:
            require_schema(card, "benchmark.scorecard", require_current=True)
        except ValueError:
            raise ValueError("report refuses legacy scorecards; use one current campaign cohort")
        try:
            require_schema({"schema": run.get("details_schema")}, "benchmark.scoring_details", require_current=True)
        except ValueError:
            raise ValueError("report refuses legacy or mismatched private details")
        formal = card.get("formal")
        if not isinstance(formal, dict):
            raise ValueError("current scorecard is missing formal cohort provenance")
        if formal.get("campaign") != expected_campaign:
            raise ValueError("scorecard campaign binding does not match supplied campaign")
        key = (
            str(formal.get("campaign", {}).get("sha256") or ""),
            str(formal.get("split") or ""),
            str(formal.get("gold_snapshot_sha256") or ""),
        )
        if not all(key):
            raise ValueError("scorecard formal provenance is incomplete")
        if cohort is None:
            cohort = key
        elif cohort != key:
            raise ValueError("report refuses mixed campaign, split, or gold snapshot cohorts")
    assert cohort is not None
    if cohort[1] != "test":
        return
    for run in runs:
        formal = run["scorecard"]["formal"]
        run_dir = runs_dir / validate_path_segment(
            str(formal.get("run_id") or ""), "run id"
        )
        release = find_matching_release(
            campaign_path=campaign_path, run_dir=run_dir, releases_root=releases_root
        )
        if release is None:
            raise ValueError("test report requires a matching persistent release manifest")
        if sha256_file(run_dir / "run_manifest.json") != formal.get("run_manifest_sha256"):
            raise ValueError("scorecard run manifest hash no longer matches sealed run")
        if (formal.get("test_release") or {}).get("sha256") != sha256_file(release):
            raise ValueError("scorecard test release binding no longer matches release manifest")


def run_subtitle(scorecard: dict[str, Any]) -> str:
    source = scorecard.get("run_source") or {}
    parts = [str(source.get("mode") or "")]
    harness = source.get("harness") or {}
    if isinstance(harness, dict) and harness.get("name"):
        parts.append(
            f"harness {harness.get('name')}/{harness.get('version') or '?'}"
        )
    for key in ("pipeline", "model", "prompt_version"):
        if source.get(key):
            parts.append(str(source[key]))
    formal = scorecard.get("formal") or {}
    if formal.get("method_fingerprint"):
        parts.append(f"method {str(formal['method_fingerprint'])[:12]}")
    return " · ".join(part for part in parts if part)


def paper_l2_counts(paper: dict[str, Any]) -> dict[str, int]:
    """Presentation counts from scorer-emitted statuses (no re-judgment)."""

    counts = {"gold": 0, "strict": 0, "lenient": 0, "ai_only": 0}
    rows = [row for pair in paper.get("pairs", []) for row in pair.get("l2", [])]
    rows += [
        row for missed in paper.get("unmatched_gold", []) for row in missed.get("l2", [])
    ]
    for row in rows:
        status = row.get("status")
        if status == "ai_only":
            counts["ai_only"] += 1
            continue
        counts["gold"] += 1
        if status in STRICT_STATUSES:
            counts["strict"] += 1
            counts["lenient"] += 1
        elif status == "within_gold_error":
            counts["lenient"] += 1
    return counts


# --------------------------------------------------------------------------
# Rendering


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --canvas: #ffffff;
      --canvas-cool: #f0f0fa;
      --ink: #000000;
      --ink-mute: #5a5a5f;
      --hairline: #e0e0e8;
      --good: #128a58;
      --good-soft: #e2f5eb;
      --warn: #8c6d00;
      --warn-soft: #fff3c7;
      --bad: #d83b35;
      --bad-soft: #ffe6e2;
      --miss: #5a5a5f;
      --miss-soft: #ececf2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--canvas);
      color: var(--ink);
      font-family: D-DIN, "Arial Narrow", Arial, Verdana, sans-serif;
      font-size: 16px;
      line-height: 1.5;
      letter-spacing: 0.32px;
    }}
    a {{ color: inherit; text-decoration: underline; }}
    h1 {{
      margin: 0;
      font-family: D-DIN-Bold, "Arial Narrow", Arial, Verdana, sans-serif;
      font-size: clamp(40px, 6vw, 60px);
      font-weight: 700;
      line-height: 1.2;
      letter-spacing: 1.2px;
      text-transform: uppercase;
    }}
    h2 {{
      margin: 0 0 16px;
      font-family: D-DIN-Bold, "Arial Narrow", Arial, Verdana, sans-serif;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0.96px;
      text-transform: uppercase;
    }}
    .eyebrow {{
      margin: 0 0 8px;
      color: var(--ink-mute);
      font-size: 12px;
      font-weight: 400;
      line-height: 2.0;
      letter-spacing: 0.96px;
      text-transform: uppercase;
    }}
    .hero {{
      padding: 48px 32px 32px;
      border-bottom: 1px solid var(--hairline);
    }}
    .hero p {{ max-width: 920px; color: var(--ink-mute); }}
    section {{ padding: 32px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      border-bottom: 1px solid var(--hairline);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--ink-mute);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.96px;
      text-transform: uppercase;
    }}
    td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .mute {{ color: var(--ink-mute); font-size: 13px; letter-spacing: 0; }}
    .pill {{
      display: inline-block;
      min-height: 0;
      border: 1px solid var(--ink);
      border-radius: 32px;
      padding: 2px 10px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1.17px;
      text-transform: uppercase;
    }}
    .pill.good {{ border-color: var(--good); color: var(--good); }}
    .pill.warn {{ border-color: var(--warn); color: var(--warn); }}
    .pill.bad {{ border-color: var(--bad); color: var(--bad); }}
    .pill.miss {{ border-color: var(--miss); color: var(--miss); }}
    tr.row-good td {{ background: var(--good-soft); }}
    tr.row-warn td {{ background: var(--warn-soft); }}
    tr.row-bad td {{ background: var(--bad-soft); }}
    tr.row-miss td {{ background: var(--miss-soft); }}
    .note {{
      margin-top: 4px;
      color: var(--ink-mute);
      font-size: 12px;
      letter-spacing: 0;
    }}
    .method-card {{
      border: 1px solid var(--hairline);
      border-radius: 8px;
      margin-bottom: 24px;
      overflow: hidden;
    }}
    .method-card > header {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px 16px;
      align-items: baseline;
      padding: 14px 16px;
      background: var(--canvas-cool);
      border-bottom: 1px solid var(--hairline);
    }}
    .method-card > header b {{
      font-size: 16px;
      letter-spacing: 0.96px;
      text-transform: uppercase;
    }}
    .method-card .body {{ padding: 12px 16px 16px; }}
    .back {{
      display: inline-block;
      border: 1px solid var(--ink);
      border-radius: 32px;
      padding: 10px 18px;
      margin-bottom: 24px;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 1.17px;
      text-decoration: none;
      text-transform: uppercase;
    }}
    .back:hover {{ background: var(--canvas-cool); }}
    .pair-head {{
      margin: 18px 0 6px;
      font-weight: 700;
    }}
    .pair-head .mute {{ font-weight: 400; }}
    footer {{
      padding: 32px;
      border-top: 1px solid var(--hairline);
      color: var(--ink-mute);
      font-size: 13px;
      letter-spacing: 0;
    }}
    @media (max-width: 760px) {{
      .hero, section, footer {{ padding-left: 18px; padding-right: 18px; }}
      table {{ font-size: 14px; }}
    }}
  </style>
</head>
<body>
{body}
<footer>
  Generated {generated} · scorer spec benchmark/SCORE_SPEC.md v1.0.0 ·
  layered metrics: L1 F1 (finding), agreement-over-compared (transcribing),
  delivery-end-to-end — never combined into one score.
  This page embeds gold values; it lives in the private repository only.
</footer>
</body>
</html>
"""


def render_runs_table(runs: list[dict[str, Any]]) -> str:
    head = (
        "<tr><th>Run</th><th class='num'>L1 F1</th>"
        "<th class='num'>L1 P / R</th>"
        "<th class='num'>Agreement (strict)</th>"
        "<th class='num'>Delivery end-to-end</th>"
        "<th class='num'>Fill precision</th>"
        "<th class='num'>Coverage</th>"
        "<th class='num'>AI-only</th>"
        "<th>Delivery</th><th>Sensitivity</th></tr>"
    )
    rows = []
    for run in runs:
        card = run["scorecard"]
        l1 = card["l1"]["micro"]
        l1_ci = (card["l1"].get("bootstrap") or {}).get("micro_f1_ci95")
        l2 = card["l2"]["micro"]
        l2_boot = card["l2"].get("bootstrap") or {}
        delivery = card.get("delivery_counts") or {}
        delivery_text = (
            f"valid {delivery.get('valid', '—')}/{delivery.get('expected', '—')}"
            f" · invalid {delivery.get('invalid', '—')}"
            f" · missing {delivery.get('missing', '—')}"
        )
        sensitivity = card.get("post_stratified_sensitivity") or {}
        sensitivity_text = "—"
        if sensitivity:
            sensitivity_text = (
                f"{sensitivity.get('label')}: "
                f"L1 F1 {fmt_rate((sensitivity.get('l1') or {}).get('f1'))}"
            )
        rows.append(
            "<tr>"
            f"<td><b>{esc(run['label'])}</b>"
            f"<div class='mute'>{esc(run_subtitle(card))}</div></td>"
            f"<td class='num'><b>{fmt_rate(l1.get('f1'))}</b>"
            f"<div class='mute'>{esc(fmt_ci(l1_ci))}</div></td>"
            f"<td class='num'>{fmt_rate(l1.get('precision'))} / "
            f"{fmt_rate(l1.get('recall'))}</td>"
            f"<td class='num'>{fmt_rate(l2.get('agreement_over_compared_strict'))}"
            f"<div class='mute'>{esc(fmt_ci(l2_boot.get('agreement_over_compared_strict_ci95')))}</div></td>"
            f"<td class='num'><b>{fmt_rate(l2.get('delivery_end_to_end_strict'))}</b>"
            f"<div class='mute'>{esc(fmt_ci(l2_boot.get('delivery_end_to_end_strict_ci95')))}</div></td>"
            f"<td class='num'>{fmt_rate(l2.get('fill_precision_strict'))}</td>"
            f"<td class='num'>{fmt_rate(l2.get('coverage'))}</td>"
            f"<td class='num'>{esc(int(l2.get('ai_only') or 0))}</td>"
            f"<td class='mute'>{esc(delivery_text)}</td>"
            f"<td class='mute'>{esc(sensitivity_text)}</td>"
            "</tr>"
        )
    return f"<table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>"


def render_paper_matrix(runs: list[dict[str, Any]], paper_ids: list[str]) -> str:
    head = "<tr><th>Paper</th>" + "".join(
        f"<th>{esc(run['label'])}</th>" for run in runs
    ) + "</tr>"
    body_rows = []
    for arxiv_id in paper_ids:
        cells = [
            f"<td><a href='papers/{esc(arxiv_id)}.html'><b>{esc(arxiv_id)}</b></a></td>"
        ]
        for run in runs:
            record = next(
                (
                    item
                    for item in run["scorecard"]["l1"]["per_paper"]
                    if item["arxiv_id"] == arxiv_id
                ),
                None,
            )
            paper = run["papers"].get(arxiv_id)
            if record is None or paper is None:
                cells.append("<td class='mute'>not scored</td>")
                continue
            clean = record["fp"] == 0 and record["fn"] == 0
            pill = "good" if clean else "bad"
            counts = paper_l2_counts(paper)
            delivered = (
                f"{counts['strict']}/{counts['gold']}" if counts["gold"] else "—"
            )
            ai_only = (
                f" · ai_only {counts['ai_only']}" if counts["ai_only"] else ""
            )
            cells.append(
                "<td>"
                f"<span class='pill {pill}'>tp {record['tp']} · fp {record['fp']} · "
                f"fn {record['fn']}</span>"
                f"<div class='mute'>L2 strict {delivered}{esc(ai_only)}</div>"
                "</td>"
            )
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table><thead>{head}</thead><tbody>{''.join(body_rows)}</tbody></table>"


def render_index(runs: list[dict[str, Any]], paper_ids: list[str], generated: str) -> str:
    body = f"""
<div class="hero">
  <p class="eyebrow">Stella HVS benchmark · gold vs AI</p>
  <h1>Benchmark scoreboard</h1>
  <p>Every number on this page is read from the scorer outputs
  (scorecard.json + private details.json); the report renders, it never
  re-judges. Rows below cover {len(paper_ids)} gold paper(s) and
  {len(runs)} scored run(s).</p>
</div>
<section>
  <h2>Runs side by side</h2>
  {render_runs_table(runs)}
</section>
<section>
  <h2>Per-paper results</h2>
  {render_paper_matrix(runs, paper_ids)}
</section>
"""
    return PAGE_TEMPLATE.format(
        title="Benchmark scoreboard", body=body, generated=esc(generated)
    )


def render_l2_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='mute'>No scored quantities.</p>"
    head = (
        "<tr><th>Field</th><th>Gold</th><th>AI</th><th>Status</th></tr>"
    )
    rendered = []
    for row in rows:
        status = str(row.get("status") or "")
        klass = STATUS_CLASSES.get(status, "miss")
        flags = []
        if row.get("projected_from_total_velocity"):
            flags.append("projected from total_velocity")
        if row.get("unit_missing_one_side"):
            flags.append("unit missing one side")
        note = str(row.get("gold_note") or "")
        extras = ""
        if flags:
            extras += f"<div class='note'>{esc('; '.join(flags))}</div>"
        if note:
            extras += f"<div class='note'>gold note: {esc(note)}</div>"
        rendered.append(
            f"<tr class='row-{klass}'>"
            f"<td>{esc(row.get('field'))}</td>"
            f"<td>{esc(row.get('gold'))}</td>"
            f"<td>{esc(row.get('ai'))}</td>"
            f"<td><span class='pill {klass}'>{esc(STATUS_LABELS.get(status, status))}</span>{extras}</td>"
            "</tr>"
        )
    return f"<table><thead>{head}</thead><tbody>{''.join(rendered)}</tbody></table>"


def render_method_section(run: dict[str, Any], arxiv_id: str) -> str:
    paper = run["papers"].get(arxiv_id)
    card = run["scorecard"]
    record = next(
        (
            item
            for item in card["l1"]["per_paper"]
            if item["arxiv_id"] == arxiv_id
        ),
        None,
    )
    if paper is None or record is None:
        return (
            f"<div class='method-card'><header><b>{esc(run['label'])}</b>"
            "<span class='mute'>not scored</span></header></div>"
        )
    blocks = []
    for pair in paper.get("pairs", []):
        origin = ""
        if pair.get("gold_origin_type") or pair.get("ai_origin_type"):
            origin = (
                f"<span class='mute'>origin: gold {esc(pair.get('gold_origin_type') or '—')}"
                f" / ai {esc(pair.get('ai_origin_type') or '—')}</span>"
            )
        blocks.append(
            f"<p class='pair-head'>{esc(pair.get('gold_id'))} ↔ {esc(pair.get('ai_id'))} "
            f"<span class='mute'>({esc(pair.get('method'))}: {esc(pair.get('detail'))})</span> "
            f"{origin}</p>"
            + render_l2_rows(pair.get("l2", []))
        )
    for missed in paper.get("unmatched_gold", []):
        blocks.append(
            f"<p class='pair-head'>{esc(missed.get('gold_id'))} "
            "<span class='pill bad'>missed by AI</span></p>"
            + render_l2_rows(missed.get("l2", []))
        )
    if paper.get("unmatched_ai"):
        extra = ", ".join(str(item) for item in paper["unmatched_ai"])
        blocks.append(
            "<p class='pair-head'>AI-only candidates "
            f"<span class='pill bad'>{len(paper['unmatched_ai'])} false positive(s)</span></p>"
            f"<p class='mute'>{esc(extra)}</p>"
        )
    if not blocks:
        blocks.append("<p class='mute'>No candidates on either side.</p>")
    status_line = (
        f"gold {esc(paper.get('gold_status'))} / ai {esc(paper.get('ai_status'))}"
    )
    return (
        "<div class='method-card'>"
        f"<header><b>{esc(run['label'])}</b>"
        f"<span class='mute'>{esc(run_subtitle(card))}</span>"
        f"<span class='mute'>tp {record['tp']} · fp {record['fp']} · fn {record['fn']}"
        f" · {status_line}</span></header>"
        f"<div class='body'>{''.join(blocks)}</div>"
        "</div>"
    )


def render_paper(
    runs: list[dict[str, Any]], arxiv_id: str, generated: str
) -> str:
    sections = "".join(render_method_section(run, arxiv_id) for run in runs)
    body = f"""
<div class="hero">
  <a class="back" href="../index.html">Back</a>
  <p class="eyebrow">Paper diagnostic</p>
  <h1>{esc(arxiv_id)}</h1>
</div>
<section>
{sections}
</section>
"""
    return PAGE_TEMPLATE.format(
        title=f"{arxiv_id} benchmark report", body=body, generated=esc(generated)
    )


def clean_html(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def write_site(
    index_path: Path, runs: list[dict[str, Any]], paper_ids: list[str]
) -> list[Path]:
    generated = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    pages_dir = index_path.parent / "papers"
    pages_dir.mkdir(parents=True, exist_ok=True)
    written = [index_path]
    index_path.write_text(
        clean_html(render_index(runs, paper_ids, generated)), encoding="utf-8"
    )
    current = set()
    for arxiv_id in paper_ids:
        arxiv_id = validate_unversioned_arxiv_id(arxiv_id)
        page = pages_dir / f"{arxiv_id}.html"
        page.write_text(
            clean_html(render_paper(runs, arxiv_id, generated)), encoding="utf-8"
        )
        written.append(page)
        current.add(page)
    for stale in pages_dir.glob("*.html"):
        if stale not in current:
            stale.unlink()
    return written


def main() -> int:
    from stella.lit.env import load_env_files

    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    if args.campaign:
        paths = campaign_paths(WORKSPACE, args.campaign)
        args.campaign_manifest = paths.campaign_manifest
        args.releases_root = paths.releases
        args.runs_dir = paths.runs
        args.scoring_dir = paths.scoring

    gold_dir = args.gold_dir if args.gold_dir is not None else default_gold_dir()
    if gold_dir is not None:
        try:
            gold_dir = require_external_path(
                gold_dir, workspace=WORKSPACE, label="gold directory"
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    details_root = args.details_dir
    if details_root is None:
        if gold_dir is None:
            raise SystemExit(
                f"Set {GOLD_DIR_ENV}, or pass --gold-dir or --details-dir."
            )
        details_root = gold_dir.expanduser().resolve().parent / "scoring-details"
    output = args.output
    if output is None:
        if gold_dir is None:
            raise SystemExit(
                f"Set {GOLD_DIR_ENV}, or pass --gold-dir or --output."
            )
        output = gold_dir.expanduser().resolve().parent / "report" / "index.html"
    try:
        details_root = require_external_path(
            details_root, workspace=WORKSPACE, label="private scoring details"
        )
        output = require_external_path(
            output, workspace=WORKSPACE, label="private benchmark report"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    scoring_dir = args.scoring_dir.expanduser().resolve()
    labels = args.run_label or sorted(
        path.parent.name for path in scoring_dir.glob("*/scorecard.json")
    )
    if not labels:
        raise SystemExit(f"no scored runs found under {scoring_dir}")

    runs = load_runs(labels, scoring_dir, details_root)
    try:
        validate_formal_cohort(
            runs,
            campaign_path=args.campaign_manifest.expanduser().resolve(),
            releases_root=args.releases_root.expanduser().resolve(),
            runs_dir=args.runs_dir.expanduser().resolve(),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    paper_ids = sorted(
        {arxiv_id for run in runs for arxiv_id in run["papers"]}
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    written = write_site(output, runs, paper_ids)
    print("Wrote")
    for path in written:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
