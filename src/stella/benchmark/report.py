"""Build a self-contained HTML report over formal benchmark scorecards.

The report aggregates scored runs into experiments (one method fingerprint,
several repeats), computes cross-run mean/std for the L0/L1/L2 headline
metrics, and renders a single offline HTML file with embedded data. Only
public aggregate scorecards and operational run summaries are consumed; no
item-level gold content ever enters the report. The output belongs beside
the external private gold store.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

from stella.benchmark.paths import validate_path_segment

MODEL_SHORT_NAMES = {
    "glm-5.2": "GLM-5.2",
    "deepseek-v4-flash-0731": "V4 Flash",
    "deepseek-v4-pro": "V4 Pro",
}

MODEL_FAMILIES = {
    "glm-5.2": "glm",
    "deepseek-v4-flash-0731": "flash",
    "deepseek-v4-pro": "pro",
}

MIN_REPEAT_RUNS = 3

METRIC_KEYS = (
    "l1_precision",
    "l1_recall",
    "l1_f1",
    "l2_coverage",
    "l2_agreement_strict",
    "l2_e2e_strict",
    "gold_only",
    "ai_only",
    "roster_delivery",
    "core_full_delivery",
    "core_usable_delivery",
    "format_first_pass",
    "tokens",
    "api_calls",
    "wall_minutes",
    "cost_cny",
)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _ratio(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return numerator / denominator


def normalize_scorecard(scorecard: dict[str, Any]) -> dict[str, Any]:
    """Extract one flat metrics dict across scorecard schema versions."""

    l1 = scorecard.get("l1") or {}
    l1_micro = l1.get("micro") or {}
    l2 = scorecard.get("l2") or {}
    l2_micro = l2.get("micro") or {}
    row_counts = l2.get("row_counts") or {}
    metrics: dict[str, Any] = {
        "l1_precision": l1_micro.get("precision"),
        "l1_recall": l1_micro.get("recall"),
        "l1_f1": l1_micro.get("f1"),
        "l2_coverage": l2_micro.get("coverage"),
        "l2_agreement_strict": l2_micro.get("agreement_over_compared_strict"),
        "l2_e2e_strict": l2_micro.get("delivery_end_to_end_strict"),
        "gold_only": row_counts.get("gold_only"),
        "ai_only": row_counts.get("ai_only"),
    }
    l0 = scorecard.get("l0") or {}
    roster = l0.get("roster_delivery") or {}
    core = l0.get("core_field_delivery") or {}
    if roster:
        metrics["roster_delivery"] = roster.get("delivery_rate")
        metrics["core_full_delivery"] = core.get("full_delivery_rate")
        metrics["core_usable_delivery"] = core.get("usable_delivery_rate")
        metrics["format_first_pass"] = (l0.get("format_validation") or {}).get(
            "first_pass_rate"
        )
    else:
        delivery = scorecard.get("delivery_counts") or {}
        metrics["roster_delivery"] = _ratio(
            float(delivery.get("valid") or 0), float(delivery.get("expected") or 0)
        )
        metrics["core_full_delivery"] = None
        metrics["core_usable_delivery"] = None
        metrics["format_first_pass"] = None
    operations = scorecard.get("operations") or {}
    usage_total = ((operations.get("usage") or {}).get("total")) or {}
    metrics["tokens"] = usage_total.get("total_tokens")
    metrics["api_calls"] = usage_total.get("api_calls")
    cost = operations.get("estimated_api_cost") or {}
    try:
        metrics["cost_cny"] = (
            float(cost["total_cny"]) if cost.get("total_cny") is not None else None
        )
    except (TypeError, ValueError):
        metrics["cost_cny"] = None
    bootstrap_l1 = (l1.get("bootstrap") or {}).get("micro_f1_ci95")
    bootstrap_l2 = (l2.get("bootstrap") or {}).get("delivery_end_to_end_strict_ci95")
    metrics["l1_f1_ci95"] = bootstrap_l1 if isinstance(bootstrap_l1, list) else None
    metrics["l2_e2e_ci95"] = bootstrap_l2 if isinstance(bootstrap_l2, list) else None
    return metrics


def _trim_messages(messages: list[Any], *, limit: int = 3, width: int = 240) -> list[str]:
    trimmed: list[str] = []
    for message in messages[:limit]:
        text = str(message).strip().replace("\n", " ")
        if len(text) > width:
            text = text[: width - 1] + "…"
        trimmed.append(text)
    return trimmed


def _paper_errors(paper_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not paper_result:
        return []
    errors: list[dict[str, Any]] = []
    top_failure = paper_result.get("failure")
    if isinstance(top_failure, dict) and top_failure.get("code"):
        errors.append(
            {
                "scope": "paper",
                "code": str(top_failure.get("code")),
                "messages": _trim_messages(
                    list(top_failure.get("initial_errors") or [])
                    + list(top_failure.get("correction_errors") or [])
                ),
            }
        )
    roster = paper_result.get("roster") or {}
    roster_failure = roster.get("failure")
    if isinstance(roster_failure, dict) and roster_failure.get("code"):
        errors.append(
            {
                "scope": "roster",
                "code": str(roster_failure.get("code")),
                "messages": _trim_messages(
                    list(roster_failure.get("initial_errors") or [])
                    + list(roster_failure.get("correction_errors") or [])
                ),
            }
        )
    for candidate in paper_result.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        failure = candidate.get("failure")
        if isinstance(failure, dict) and failure.get("code"):
            errors.append(
                {
                    "scope": str(candidate.get("record_id") or "candidate"),
                    "code": str(failure.get("code")),
                    "messages": _trim_messages(
                        list(failure.get("initial_errors") or [])
                        + list(failure.get("correction_errors") or [])
                    ),
                }
            )
    return errors


def load_run_details(run_dir: Path) -> dict[str, Any]:
    """Compact operational detail for one run from its local archive."""

    detail: dict[str, Any] = {
        "tokens": None,
        "api_calls": None,
        "wall_minutes": None,
        "roster_delivery": None,
        "core_full_delivery": None,
        "core_usable_delivery": None,
        "papers": [],
        "archive_present": run_dir.is_dir(),
    }
    if not run_dir.is_dir():
        return detail
    manifest = _load_json(run_dir / "run_manifest.json") or {}
    roster_block = manifest.get("l1_roster_delivery") or {}
    core_block = manifest.get("l2_core_field_delivery") or {}
    manifest_papers = manifest.get("papers") or []
    expected = len(manifest_papers)
    if expected and roster_block:
        detail["roster_delivery"] = len(roster_block.get("complete") or []) / expected
    if expected and core_block:
        detail["core_full_delivery"] = len(core_block.get("complete") or []) / expected
        detail["core_usable_delivery"] = (
            len(core_block.get("complete") or []) + len(core_block.get("partial") or [])
        ) / expected
    summary = _load_json(run_dir / "run_summary.json") or {}
    totals = summary.get("totals") or {}
    detail["tokens"] = totals.get("tokens")
    detail["api_calls"] = totals.get("api_calls")
    elapsed = totals.get("elapsed_seconds")
    detail["wall_minutes"] = round(float(elapsed) / 60.0, 1) if elapsed is not None else None
    papers: list[dict[str, Any]] = []
    for arxiv_id, record in (summary.get("papers") or {}).items():
        if not isinstance(record, dict):
            continue
        candidates = record.get("candidates") or {}
        candidate_total = len(candidates)
        candidate_failed = sum(
            1 for status in candidates.values() if status == "field_extraction_failed"
        )
        paper_result = _load_json(
            run_dir / "papers" / arxiv_id / "paper_result.json"
        )
        stage_calls = record.get("stage_calls") or {}
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "status": record.get("status"),
                "roster_status": record.get("roster_status"),
                "failure_code": record.get("failure_code"),
                "candidates_total": candidate_total,
                "candidates_failed": candidate_failed,
                "roster_calls": stage_calls.get("roster"),
                "field_calls": stage_calls.get("core_fields"),
                "tokens": record.get("total_tokens"),
                "wall_seconds": record.get("wall_seconds"),
                "errors": _paper_errors(paper_result),
            }
        )
    detail["papers"] = papers
    return detail


def _model_short(name: Any) -> str:
    return MODEL_SHORT_NAMES.get(str(name or ""), str(name or "?"))


def _role_text(role: dict[str, Any]) -> str:
    parts = [_model_short(role.get("model"))]
    overrides = role.get("request_overrides") or {}
    thinking = (overrides.get("thinking") or {}).get("type")
    effort = overrides.get("reasoning_effort")
    if thinking == "disabled":
        parts.append("nothink")
    elif effort:
        parts.append(str(effort))
    mode = str(role.get("structured_output_mode") or "")
    if mode and mode != "tool_submission":
        parts.append(mode)
    return "·".join(parts)


def _experiment_label(config: dict[str, Any] | None) -> tuple[str, str, str]:
    if not config:
        return "未知配置", "unknown", ""
    method = config.get("method") or {}
    roster = method.get("roster_model") or {}
    field = method.get("core_field_model") or {}
    roster_text = _role_text(roster)
    field_text = _role_text(field)
    label = f"{roster_text} roster / {field_text} field"
    family = MODEL_FAMILIES.get(str(roster.get("model") or ""), "other")
    revision = str((config.get("code") or {}).get("revision") or "")[:7]
    return label, family, revision


def load_legacy_run_costs(workspace: Path) -> dict[str, float]:
    """Index run_id -> total CNY from the public legacy dev10 cost inventories."""

    costs: dict[str, float] = {}
    costs_root = workspace / "benchmark" / "costs"
    if not costs_root.is_dir():
        return costs
    for inventory_path in sorted(costs_root.glob("*/legacy_dev10.json")):
        inventory = _load_json(inventory_path)
        if not inventory:
            continue
        for campaign in inventory.get("campaigns") or []:
            if not isinstance(campaign, dict):
                continue
            for entry in campaign.get("runs") or []:
                if not isinstance(entry, dict) or not entry.get("run_id"):
                    continue
                total = (entry.get("estimated_api_cost") or {}).get("total_cny")
                try:
                    if total is not None:
                        costs[str(entry["run_id"])] = float(total)
                except (TypeError, ValueError):
                    continue
    return costs


def aggregate(values: list[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"mean": None, "std": None, "min": None, "max": None, "n": 0, "values": []}
    mean = sum(clean) / len(clean)
    if len(clean) > 1:
        variance = sum((value - mean) ** 2 for value in clean) / (len(clean) - 1)
        std = math.sqrt(variance)
    else:
        std = 0.0
    return {
        "mean": mean,
        "std": std,
        "min": min(clean),
        "max": max(clean),
        "n": len(clean),
        "values": clean,
    }


def build_report_data(
    workspace: Path,
    campaign_ids: list[str],
    baseline_dirs: list[Path],
) -> dict[str, Any]:
    """Collect scorecards and run archives into the embedded report model."""

    runs: list[dict[str, Any]] = []
    legacy_costs = load_legacy_run_costs(workspace)
    for campaign_id in campaign_ids:
        scoring_root = (
            workspace / "benchmark" / "campaigns" / campaign_id / "scoring"
        )
        if not scoring_root.is_dir():
            continue
        for score_dir in sorted(scoring_root.iterdir()):
            scorecard_path = score_dir / "scorecard.json"
            scorecard = _load_json(scorecard_path)
            if not scorecard:
                continue
            formal = scorecard.get("formal") or {}
            run_id = formal.get("run_id") or (scorecard.get("run_source") or {}).get(
                "run_id"
            )
            if not run_id:
                continue
            metrics = normalize_scorecard(scorecard)
            run_dir = workspace / "benchmark" / "campaigns" / campaign_id / "runs" / run_id
            detail = load_run_details(run_dir)
            for key in ("tokens", "api_calls"):
                if metrics.get(key) is None:
                    metrics[key] = detail.get(key)
            if metrics.get("wall_minutes") is None:
                metrics["wall_minutes"] = detail.get("wall_minutes")
            if metrics.get("cost_cny") is None:
                metrics["cost_cny"] = legacy_costs.get(run_id)
            for key in ("roster_delivery", "core_full_delivery", "core_usable_delivery"):
                if metrics.get(key) is None:
                    metrics[key] = detail.get(key)
            config = _load_json(run_dir / "run_config.json")
            runs.append(
                {
                    "run_id": run_id,
                    "campaign": campaign_id,
                    "score_label": scorecard.get("run_label") or score_dir.name,
                    "fingerprint": str(formal.get("method_fingerprint") or run_id),
                    "gold_selection": str(
                        (formal.get("gold_selection") or {}).get("selection_id") or ""
                    ),
                    "metrics": metrics,
                    "papers": detail["papers"],
                    "archive_present": detail["archive_present"],
                    "config": config,
                }
            )

    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        groups.setdefault(run["fingerprint"], []).append(run)

    experiments: list[dict[str, Any]] = []
    for fingerprint, members in groups.items():
        members.sort(key=lambda item: str(item["run_id"]))
        label, family, _first_revision = _experiment_label(members[0].get("config"))
        revisions = sorted(
            {
                str(((member.get("config") or {}).get("code") or {}).get("revision") or "")[:7]
                for member in members
            }
            - {""}
        )
        revision = ",".join(revisions)
        campaigns = sorted({member["campaign"] for member in members})
        gold_selection = next(
            (member["gold_selection"] for member in members if member["gold_selection"]),
            "",
        )
        metrics_agg = {
            key: aggregate([member["metrics"].get(key) for member in members])
            for key in METRIC_KEYS
        }
        experiments.append(
            {
                "id": fingerprint[:8],
                "fingerprint": fingerprint,
                "label": label,
                "family": family,
                "code_revision": revision,
                "campaigns": campaigns,
                "gold_selection": gold_selection,
                "n_runs": len(members),
                "metrics": metrics_agg,
                "runs": [
                    {
                        "run_id": member["run_id"],
                        "campaign": member["campaign"],
                        "score_label": member["score_label"],
                        "metrics": member["metrics"],
                        "papers": member["papers"],
                        "archive_present": member["archive_present"],
                    }
                    for member in members
                ],
            }
        )

    def _sort_key(experiment: dict[str, Any]) -> float:
        mean = (experiment["metrics"]["l2_coverage"] or {}).get("mean")
        return -(mean if mean is not None else -1.0)

    main = sorted(
        [exp for exp in experiments if exp["n_runs"] >= MIN_REPEAT_RUNS], key=_sort_key
    )
    singles = sorted(
        [exp for exp in experiments if exp["n_runs"] < MIN_REPEAT_RUNS], key=_sort_key
    )

    baseline: dict[str, Any] | None = None
    for baseline_dir in baseline_dirs:
        if not baseline_dir.is_dir():
            continue
        for score_dir in sorted(baseline_dir.iterdir()):
            scorecard = _load_json(score_dir / "scorecard.json")
            if not scorecard:
                continue
            if (scorecard.get("run_source") or {}).get("mode") != "legacy_literature":
                continue
            metrics = normalize_scorecard(scorecard)
            candidate = {
                "id": "baseline-literature",
                "label": "Literature 基线（初始抽取）",
                "family": "baseline",
                "score_label": scorecard.get("run_label") or score_dir.name,
                "gold_selection": str(
                    ((scorecard.get("formal") or {}).get("gold_selection") or {}).get(
                        "selection_id"
                    )
                    or ""
                ),
                "gold_papers": scorecard.get("gold_papers"),
                "metrics": {key: aggregate([metrics.get(key)]) for key in METRIC_KEYS},
                "flat": metrics,
            }
            if baseline is None or str(candidate["score_label"]) > str(
                baseline["score_label"]
            ):
                baseline = candidate
    return {"experiments": main, "singles": singles, "baseline": baseline}


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HVS 抽取 Benchmark 实验报告</title>
<style>
:root {
  --bg: #f5f7fa;
  --card: #ffffff;
  --ink: #2b3445;
  --ink-soft: #8a93a6;
  --grid: #e8ebf1;
  --green: #7cc47f;
  --pink: #e08bb6;
  --purple: #9b8ce8;
  --flash: #5da2f5;
  --glm: #f0a35c;
  --pro: #e57373;
  --baseline: #b0bec5;
  --other: #9ca8bb;
  --error: #c25555;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  padding: 28px 20px 80px;
}
.page { max-width: 1080px; margin: 0 auto; }
header.hero { margin-bottom: 20px; }
header.hero h1 { font-size: 24px; font-weight: 700; }
header.hero p { color: var(--ink-soft); font-size: 13px; margin-top: 6px; }
.card {
  background: var(--card);
  border-radius: 14px;
  box-shadow: 0 1px 4px rgba(30, 41, 59, 0.07);
  padding: 20px 22px;
  margin-bottom: 18px;
}
.card h2 { font-size: 16px; font-weight: 700; margin-bottom: 4px; }
.card .hint { color: var(--ink-soft); font-size: 12px; margin-bottom: 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 4px; }
.chip {
  display: inline-flex; align-items: center; gap: 7px;
  border: 1.5px solid var(--grid); border-radius: 999px;
  padding: 6px 13px; font-size: 13px; cursor: pointer;
  background: #fff; transition: border-color .15s, background .15s;
  user-select: none;
}
.chip:hover { border-color: #c6cdd9; }
.chip.selected { background: #eef4ff; border-color: var(--flash); }
.chip .dot { width: 10px; height: 10px; border-radius: 50%; }
.chip .n { color: var(--ink-soft); font-size: 11px; }
.chip .go {
  color: var(--flash); font-size: 12px; font-weight: 600;
  border-left: 1px solid var(--grid); padding-left: 7px; margin-left: 2px;
}
.chip .go:hover { text-decoration: underline; }
.chip.baseline-chip { border-style: dashed; }
.legend { display: flex; gap: 18px; flex-wrap: wrap; font-size: 12px; color: var(--ink-soft); margin: 6px 0 2px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.chart-scroll { overflow-x: auto; }
svg text { font-family: inherit; }
.bar-group { cursor: pointer; }
.bar-group:hover rect.bar { opacity: 0.82; }
.hbar-row { display: flex; align-items: center; gap: 12px; padding: 7px 0; }
.hbar-label { width: 250px; font-size: 13px; text-align: right; flex-shrink: 0; }
.hbar-track { flex: 1; background: #f0f2f7; border-radius: 6px; height: 22px; position: relative; }
.hbar-fill { height: 100%; border-radius: 6px; min-width: 2px; }
.hbar-value { width: 150px; font-size: 12.5px; color: var(--ink); flex-shrink: 0; }
.hbar-value small { color: var(--ink-soft); }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
th, td { padding: 7px 9px; text-align: right; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--ink-soft); font-weight: 600; background: #fafbfe; }
tr.run-row { cursor: pointer; }
tr.run-row:hover td { background: #f6f9ff; }
tr.papers-row td { text-align: left; background: #fafbfe; white-space: normal; }
.badge { display: inline-block; padding: 1.5px 8px; border-radius: 999px; font-size: 11px; }
.badge.complete { background: #e5f4e5; color: #3d7a3d; }
.badge.partial { background: #fdf0e0; color: #a86a1d; }
.badge.failed { background: #fbe3e3; color: #a13a3a; }
.badge.missing { background: #eceff4; color: #6b7484; }
.err-list { margin: 4px 0 0; padding: 0; list-style: none; }
.err-list li { font-size: 12px; color: var(--error); margin: 2px 0; }
.err-list code { background: #fbeaea; border-radius: 4px; padding: 0 5px; font-size: 11px; }
.detail-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.detail-head .meta { color: var(--ink-soft); font-size: 12px; }
.btn {
  border: 1.5px solid var(--grid); background: #fff; border-radius: 8px;
  padding: 6px 14px; font-size: 13px; cursor: pointer; color: var(--ink);
}
.btn:hover { border-color: #c6cdd9; }
.btn.primary { background: var(--flash); border-color: var(--flash); color: #fff; }
.controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 8px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.detail-sub { font-size: 13.5px; font-weight: 700; margin: 14px 0 6px; color: var(--ink); }
.detail-sub:first-of-type { margin-top: 6px; }
.footnote { color: var(--ink-soft); font-size: 12px; line-height: 1.7; }
.paper-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; margin-top: 10px; }
.paper-card { border: 1px solid var(--grid); border-radius: 10px; padding: 10px 12px; font-size: 12px; background: #fff; }
.paper-card .pid { font-weight: 700; font-size: 12.5px; margin-bottom: 4px; }
.paper-card .kv { color: var(--ink-soft); margin: 1.5px 0; }
.paper-card .kv b { color: var(--ink); font-weight: 600; }
</style>
</head>
<body>
<div class="page">
  <header class="hero">
    <h1>HVS 抽取 Benchmark 实验报告</h1>
    <p id="subtitle"></p>
  </header>

  <div class="card">
    <h2>实验选择</h2>
    <div class="hint">勾选两个及以上实验可进入对比视图；点击实验名称右侧的「详情 ›」或图表中的柱子，查看该实验的整体评分、每次 run 的评分与论文级报错细节。</div>
    <div class="chips" id="chips"></div>
    <div class="controls">
      <button class="btn primary" id="compare-btn">对比选中实验</button>
      <button class="btn" id="reset-btn">重置为总览</button>
    </div>
  </div>

  <div id="compare-view"></div>

  <div class="card" id="quality-card">
    <h2>质量指标（越高越好）</h2>
    <div class="hint">柱高为跨 run 均值，误差线为 ±1 标准差；基线为单次诊断评分，无误差线。L0/L1/L2 分层报告，不存在综合分。</div>
    <div class="legend">
      <span><i style="background:var(--green)"></i>L1 F1</span>
      <span><i style="background:var(--pink)"></i>L2 coverage</span>
      <span><i style="background:var(--purple)"></i>L2 严格端到端</span>
    </div>
    <div class="chart-scroll" id="quality-chart"></div>
  </div>

  <div id="overview-sections"></div>

  <div class="card" id="detail-card" style="display:none">
    <div class="detail-head">
      <h2 id="detail-title"></h2>
      <span class="meta" id="detail-meta"></span>
    </div>
    <div class="hint" id="detail-config"></div>
    <div id="detail-body"></div>
  </div>

  <div class="card" id="singles-card" style="display:none">
    <h2>附录：单次 run 配置</h2>
    <div class="hint">同一配置不足 3 次 run，不参与首页均值对比，仅列出观测值。</div>
    <div id="singles-body"></div>
  </div>

  <div class="card">
    <h2>说明</h2>
    <p class="footnote" id="footnotes"></p>
  </div>
</div>
<script>
const DATA = __DATA__;
const FAMILY_COLORS = {flash: "var(--flash)", glm: "var(--glm)", pro: "var(--pro)", baseline: "var(--baseline)", other: "var(--other)", unknown: "var(--other)"};
const QUALITY_METRICS = [
  {key: "l1_f1", name: "L1 F1", color: "var(--green)"},
  {key: "l2_coverage", name: "L2 coverage", color: "var(--pink)"},
  {key: "l2_e2e_strict", name: "L2 严格端到端", color: "var(--purple)"},
];
const state = {selected: new Set(), detail: null, comparing: false};

function pct(v, digits=1) { return v == null ? "—" : (v * 100).toFixed(digits) + "%"; }
function num(v, digits=3) { return v == null ? "—" : (+v).toFixed(digits); }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function fmtTokens(v) { return v == null ? "—" : (v / 1e6).toFixed(2) + "M"; }
function fmtMin(v) { return v == null ? "—" : (+v).toFixed(1) + " min"; }
function fmtCost(v) { return v == null ? "—" : "¥" + (+v).toFixed(3); }
function aggText(agg, fmt) {
  if (!agg || agg.mean == null) return "—";
  const mean = fmt(agg.mean);
  if (agg.n >= 2 && agg.std != null) {
    let std;
    if (fmt === pct) std = "±" + (agg.std * 100).toFixed(1) + "%";
    else if (fmt === fmtTokens) std = "±" + (agg.std / 1e6).toFixed(2) + "M";
    else if (fmt === fmtMin) std = "±" + agg.std.toFixed(1);
    else if (fmt === fmtCost) std = "±" + agg.std.toFixed(3);
    else std = "±" + agg.std.toFixed(3);
    return mean + " " + std;
  }
  return mean;
}

function experimentGroups() {
  const groups = [...DATA.experiments];
  if (DATA.baseline) groups.push(DATA.baseline);
  return groups;
}
function selectedGroups() {
  const all = experimentGroups();
  return all.filter(g => state.selected.has(g.id));
}

function hideDetail() {
  state.detail = null;
  document.getElementById("detail-card").style.display = "none";
}

function renderChips() {
  const host = document.getElementById("chips");
  host.innerHTML = "";
  for (const g of experimentGroups()) {
    const chip = document.createElement("span");
    chip.className = "chip" + (state.selected.has(g.id) ? " selected" : "") + (g.family === "baseline" ? " baseline-chip" : "");
    chip.innerHTML = `<span class="dot" style="background:${FAMILY_COLORS[g.family] || FAMILY_COLORS.other}"></span>` +
      `<span>${esc(g.label)}</span><span class="n">${g.family === "baseline" ? "基线" : "n=" + g.n_runs}</span>` +
      `<span class="go" title="查看实验详情">详情 ›</span>`;
    chip.querySelector(".go").onclick = (ev) => { ev.stopPropagation(); showDetail(g.id); };
    chip.onclick = (ev) => {
      if (state.selected.has(g.id)) state.selected.delete(g.id); else state.selected.add(g.id);
      hideDetail();
      render();
    };
    host.appendChild(chip);
  }
}

function qualityChartSVG(groups) {
  const barW = 36, gap = 6, groupPad = 46;
  const groupW = QUALITY_METRICS.length * (barW + gap) - gap + groupPad;
  const width = Math.max(640, groups.length * groupW + 70);
  const height = 400, top = 46, bottom = 62, left = 52;
  const plotH = height - top - bottom;
  const y = v => top + plotH * (1 - v);
  let parts = [];
  for (const frac of [0, 0.25, 0.5, 0.75, 1]) {
    parts.push(`<line x1="${left}" y1="${y(frac)}" x2="${width - 14}" y2="${y(frac)}" stroke="var(--grid)" stroke-width="1"/>`);
    parts.push(`<text x="${left - 8}" y="${y(frac) + 4}" font-size="11" fill="var(--ink-soft)" text-anchor="end">${frac * 100}%</text>`);
  }
  groups.forEach((g, gi) => {
    const gx = left + 14 + gi * groupW;
    parts.push(`<g class="bar-group" data-exp="${esc(g.id)}">`);
    QUALITY_METRICS.forEach((m, mi) => {
      const agg = (g.metrics || {})[m.key] || {};
      if (agg.mean == null) return;
      const bx = gx + mi * (barW + gap);
      const by = y(agg.mean), bh = plotH * agg.mean;
      const dashed = g.family === "baseline" ? ` stroke="${m.color}" stroke-width="1.5" stroke-dasharray="4 3" fill-opacity="0.45"` : "";
      parts.push(`<rect class="bar" x="${bx}" y="${by}" width="${barW}" height="${bh}" rx="5" fill="${m.color}"${dashed}/>`);
      parts.push(`<text x="${bx + barW / 2}" y="${by - 6}" font-size="11" fill="var(--ink)" text-anchor="middle">${(agg.mean * 100).toFixed(1)}</text>`);
      if (agg.n >= 2 && agg.std != null && agg.std > 0) {
        const lo = Math.max(0, agg.mean - agg.std), hi = Math.min(1, agg.mean + agg.std);
        const cx = bx + barW / 2;
        parts.push(`<line x1="${cx}" y1="${y(lo)}" x2="${cx}" y2="${y(hi)}" stroke="#5b6472" stroke-width="1.6"/>`);
        parts.push(`<line x1="${cx - 6}" y1="${y(hi)}" x2="${cx + 6}" y2="${y(hi)}" stroke="#5b6472" stroke-width="1.6"/>`);
        parts.push(`<line x1="${cx - 6}" y1="${y(lo)}" x2="${cx + 6}" y2="${y(lo)}" stroke="#5b6472" stroke-width="1.6"/>`);
      }
    });
    const cx = gx + (QUALITY_METRICS.length * (barW + gap) - gap) / 2;
    if (g.family === "baseline") {
      parts.push(`<text x="${cx}" y="${height - bottom + 22}" font-size="12" fill="var(--ink)" text-anchor="middle">Literature 基线</text>`);
      parts.push(`<text x="${cx}" y="${height - bottom + 40}" font-size="10.5" fill="var(--ink-soft)" text-anchor="middle">诊断基线</text>`);
    } else {
      const halves = g.label.split(" / ");
      parts.push(`<text x="${cx}" y="${height - bottom + 18}" font-size="10.5" fill="var(--ink)" text-anchor="middle">${esc(halves[0] || g.label)}</text>`);
      parts.push(`<text x="${cx}" y="${height - bottom + 33}" font-size="10.5" fill="var(--ink)" text-anchor="middle">${esc(halves[1] || "")}</text>`);
      parts.push(`<text x="${cx}" y="${height - bottom + 48}" font-size="10" fill="var(--ink-soft)" text-anchor="middle">n=${g.n_runs}</text>`);
    }
    parts.push(`</g>`);
  });
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${parts.join("")}</svg>`;
}

function renderQualityChart(groups) {
  const host = document.getElementById("quality-chart");
  host.innerHTML = qualityChartSVG(groups);
  host.querySelectorAll(".bar-group").forEach(el => {
    el.addEventListener("click", () => showDetail(el.getAttribute("data-exp")));
  });
}

function hbarSection(title, hint, key, fmt, colorOf) {
  const groups = experimentGroups().filter(g => ((g.metrics || {})[key] || {}).mean != null);
  const values = groups.map(g => g.metrics[key].mean);
  if (!values.length) return "";
  const max = Math.max(...values, 1e-9);
  const rows = groups.map(g => {
    const agg = g.metrics[key];
    const w = Math.max(agg.mean / max * 100, 0.5);
    const color = colorOf ? colorOf(g) : (FAMILY_COLORS[g.family] || FAMILY_COLORS.other);
    const dashed = g.family === "baseline" ? "background:repeating-linear-gradient(45deg," + color + "," + color + " 6px,#ffffff66 6px,#ffffff66 12px);" : `background:${color};`;
    return `<div class="hbar-row">
      <div class="hbar-label">${esc(g.label)}</div>
      <div class="hbar-track"><div class="hbar-fill" style="width:${w}%;${dashed}"></div></div>
      <div class="hbar-value">${aggText(agg, fmt)}</div>
    </div>`;
  }).join("");
  return `<div class="card"><h2>${title}</h2><div class="hint">${hint}</div>${rows}</div>`;
}

function renderOverview() {
  const host = document.getElementById("overview-sections");
  host.innerHTML =
    hbarSection("论文交付率（越高越好）", "L0 roster 交付率的跨 run 均值 ± 标准差；基线无运行概念故不展示。", "roster_delivery", pct, null) +
    hbarSection("总耗时（越低越好）", "单次完整 dev10 run 的墙钟时间均值 ± 标准差。", "wall_minutes", fmtMin, null) +
    hbarSection("总 Tokens（仅表示用量）", "单次 run 的总 token 用量均值 ± 标准差，不进入质量评分。", "tokens", fmtTokens, null) +
    hbarSection("估计成本 CNY（仅表示用量）", "按 TokenDance 快照估算的单次 run API 成本均值 ± 标准差，运营成本，不是分数。", "cost_cny", fmtCost, null);
}

const COMPARE_ROWS = [
  ["L1 precision", "l1_precision", num], ["L1 recall", "l1_recall", num], ["L1 F1", "l1_f1", num],
  ["L2 coverage", "l2_coverage", num], ["L2 严格一致（compared 行）", "l2_agreement_strict", num],
  ["L2 严格端到端", "l2_e2e_strict", num], ["L2 gold_only 行", "gold_only", v => v == null ? "—" : String(Math.round(v))],
  ["L0 roster 交付率", "roster_delivery", pct], ["L0 core 完整交付率", "core_full_delivery", pct],
  ["L0 首轮格式通过率", "format_first_pass", pct],
  ["总 tokens", "tokens", fmtTokens], ["API 调用数", "api_calls", v => v == null ? "—" : String(Math.round(v))],
  ["墙钟耗时", "wall_minutes", fmtMin], ["估计成本 (CNY)", "cost_cny", fmtCost],
];

const COMPARE_RATIO_METRICS = [
  {key: "l1_precision", name: "L1 P"},
  {key: "l1_recall", name: "L1 R"},
  {key: "l1_f1", name: "L1 F1"},
  {key: "l2_coverage", name: "L2 cov"},
  {key: "l2_agreement_strict", name: "L2 严格一致"},
  {key: "l2_e2e_strict", name: "L2 e2e"},
  {key: "roster_delivery", name: "roster 交付"},
  {key: "core_full_delivery", name: "core 交付"},
  {key: "format_first_pass", name: "首轮格式"},
];
const COMPARE_USAGE_METRICS = [
  {key: "tokens", name: "总 Tokens", fmt: v => (v / 1e6).toFixed(2) + "M"},
  {key: "wall_minutes", name: "总耗时", fmt: v => (+v).toFixed(1) + " min"},
  {key: "cost_cny", name: "估计成本 CNY", fmt: v => "¥" + (+v).toFixed(3)},
];

const COMPARE_PALETTE = ["#5da2f5", "#f0a35c", "#7cc47f", "#9b8ce8", "#e57373", "#4db6ac", "#e08bb6", "#b0bec5"];

function expColor(g) { return FAMILY_COLORS[g.family] || FAMILY_COLORS.other; }
function compareColor(g, gi) {
  if (g.family === "baseline") return "var(--baseline)";
  return COMPARE_PALETTE[gi % COMPARE_PALETTE.length];
}

function groupedCompareChartSVG(groups, metricDefs, opts) {
  const ratio = !opts || opts.scale !== "linear";
  const barW = ratio ? 24 : 44, gap = 5, groupPad = ratio ? 34 : 0;
  const defs = metricDefs.filter(m => groups.some(g => ((g.metrics || {})[m.key] || {}).mean != null));
  if (!defs.length) return "";
  const groupW = groups.length * (barW + gap) - gap + groupPad;
  const width = Math.max(640, defs.length * groupW + 70);
  const height = ratio ? 380 : 300, top = 44, bottom = ratio ? 58 : 46, left = 52;
  const plotH = height - top - bottom;
  let maxV = 1;
  if (!ratio) {
    maxV = 0;
    for (const m of defs) for (const g of groups) {
      const mean = ((g.metrics || {})[m.key] || {}).mean;
      if (mean != null) maxV = Math.max(maxV, mean);
    }
    maxV *= 1.12;
  }
  const y = v => top + plotH * (1 - v / maxV);
  let parts = [];
  const gridFracs = ratio ? [0, 0.25, 0.5, 0.75, 1] : [0, 0.5, 1];
  for (const frac of gridFracs) {
    const gv = frac * maxV;
    parts.push(`<line x1="${left}" y1="${y(gv)}" x2="${width - 14}" y2="${y(gv)}" stroke="var(--grid)" stroke-width="1"/>`);
    const label = ratio ? `${Math.round(gv * 100)}%` : (defs[0].fmt ? defs[0].fmt(gv) : gv.toFixed(1));
    parts.push(`<text x="${left - 8}" y="${y(gv) + 4}" font-size="11" fill="var(--ink-soft)" text-anchor="end">${label}</text>`);
  }
  defs.forEach((m, mi) => {
    const gx = left + 14 + mi * groupW;
    groups.forEach((g, gi) => {
      const agg = (g.metrics || {})[m.key] || {};
      if (agg.mean == null) return;
      const bx = gx + gi * (barW + gap);
      const by = y(agg.mean), bh = plotH * (agg.mean / maxV);
      const color = compareColor(g, gi);
      const dashed = g.family === "baseline" ? ` stroke="${color}" stroke-width="1.5" stroke-dasharray="4 3" fill-opacity="0.45"` : "";
      parts.push(`<rect x="${bx}" y="${by}" width="${barW}" height="${Math.max(bh, 1)}" rx="4" fill="${color}"${dashed}/>`);
      const vlabel = ratio ? (agg.mean * 100).toFixed(1) : (m.fmt ? m.fmt(agg.mean) : agg.mean);
      parts.push(`<text x="${bx + barW / 2}" y="${by - 5}" font-size="${ratio ? 9.5 : 11}" fill="var(--ink)" text-anchor="middle">${vlabel}</text>`);
      if (agg.n >= 2 && agg.std != null && agg.std > 0) {
        const lo = Math.max(0, agg.mean - agg.std), hi = agg.mean + agg.std;
        const cx = bx + barW / 2;
        parts.push(`<line x1="${cx}" y1="${y(lo)}" x2="${cx}" y2="${y(hi)}" stroke="#5b6472" stroke-width="1.4"/>`);
        parts.push(`<line x1="${cx - 4}" y1="${y(hi)}" x2="${cx + 4}" y2="${y(hi)}" stroke="#5b6472" stroke-width="1.4"/>`);
        parts.push(`<line x1="${cx - 4}" y1="${y(lo)}" x2="${cx + 4}" y2="${y(lo)}" stroke="#5b6472" stroke-width="1.4"/>`);
      }
    });
    const cxm = gx + (groups.length * (barW + gap) - gap) / 2;
    parts.push(`<text x="${cxm}" y="${height - bottom + 20}" font-size="10.5" fill="var(--ink)" text-anchor="middle">${m.name}</text>`);
  });
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${parts.join("")}</svg>`;
}

function compareLegend(groups) {
  return `<div class="legend">` + groups.map((g, gi) =>
    `<span><i style="background:${compareColor(g, gi)}"></i>${esc(g.label)}${g.family === "baseline" ? "（基线）" : ""}</span>`
  ).join("") + `</div>`;
}

function renderCompare() {
  const host = document.getElementById("compare-view");
  const groups = selectedGroups();
  if (!state.comparing || groups.length < 2) { host.innerHTML = ""; return; }
  const head = groups.map(g => `<th>${esc(g.label)}${g.family === "baseline" ? "（基线）" : ""}</th>`).join("");
  const rows = COMPARE_ROWS.map(([name, key, fmt]) => {
    const cells = groups.map(g => {
      const agg = (g.metrics || {})[key] || {};
      let text;
      if (g.family === "baseline") text = (agg.mean == null ? "—" : fmt(agg.mean));
      else text = agg.n >= 2 ? aggText(agg, fmt) : (agg.mean == null ? "—" : fmt(agg.mean));
      return `<td>${text}</td>`;
    }).join("");
    return `<tr><td>${name}</td>${cells}</tr>`;
  }).join("");
  host.innerHTML = `<div class="card"><h2>实验对比（${groups.length}）</h2>
    <div class="hint">同一指标的柱子并排展示，便于直接比较；柱高为跨 run 均值，误差线为 ±1 标准差，基线为虚线柱。</div>
    ${compareLegend(groups)}
    <div class="chart-scroll" id="compare-ratio-chart"></div>
    <div id="compare-usage-charts"></div>
    <div class="chart-scroll" style="margin-top:14px"><table><thead><tr><th>指标</th>${head}</tr></thead><tbody>${rows}</tbody></table></div></div>`;
  const ratioHost = host.querySelector("#compare-ratio-chart");
  ratioHost.innerHTML = groupedCompareChartSVG(groups, COMPARE_RATIO_METRICS);
  const usageHost = host.querySelector("#compare-usage-charts");
  usageHost.innerHTML = COMPARE_USAGE_METRICS.map(m => {
    const svg = groupedCompareChartSVG(groups, [m], {scale: "linear"});
    return svg ? `<div style="margin-top:10px"><div class="hint" style="margin-bottom:2px">${m.name}</div>${svg}</div>` : "";
  }).join("");
}

function runMetricsCells(m) {
  return `<td>${pct(m.roster_delivery)}</td><td>${num(m.l1_precision)}</td><td>${num(m.l1_recall)}</td><td>${num(m.l1_f1)}</td><td>${num(m.l2_coverage)}</td>` +
    `<td>${num(m.l2_agreement_strict)}</td><td>${num(m.l2_e2e_strict)}</td>` +
    `<td>${m.gold_only == null ? "—" : m.gold_only}</td>` +
    `<td>${fmtTokens(m.tokens)}</td><td>${fmtMin(m.wall_minutes)}</td><td>${fmtCost(m.cost_cny)}</td>`;
}

function paperCard(p) {
  const badge = `<span class="badge ${esc(p.status || "missing")}">${esc(p.status || "missing")}</span>`;
  let errHtml = "";
  if (p.errors && p.errors.length) {
    errHtml = `<ul class="err-list">` + p.errors.map(e =>
      `<li><code>${esc(e.scope)}</code> ${esc(e.code)}${e.messages && e.messages.length ? "<br>" + e.messages.map(esc).join("<br>") : ""}</li>`
    ).join("") + `</ul>`;
  }
  return `<div class="paper-card">
    <div class="pid">${esc(p.arxiv_id)} ${badge}</div>
    <div class="kv">roster: <b>${esc(p.roster_status || "—")}</b>${p.failure_code ? ` · failure: <b>${esc(p.failure_code)}</b>` : ""}</div>
    <div class="kv">候选: <b>${p.candidates_total}</b>${p.candidates_failed ? `（字段失败 ${p.candidates_failed}）` : ""} · 调用 roster/field: <b>${p.roster_calls ?? "—"}/${p.field_calls ?? "—"}</b></div>
    <div class="kv">tokens: <b>${p.tokens == null ? "—" : p.tokens.toLocaleString()}</b> · 耗时: <b>${p.wall_seconds == null ? "—" : (+p.wall_seconds).toFixed(1) + "s"}</b></div>
    ${errHtml}
  </div>`;
}

function minMaxText(agg, fmt) {
  if (!agg || agg.n == null || agg.n < 1 || agg.min == null) return "—";
  if (agg.n < 2) return fmt(agg.min);
  return fmt(agg.min) + " – " + fmt(agg.max);
}

function detailSummaryTable(g) {
  const rows = COMPARE_ROWS.map(([name, key, fmt]) => {
    const agg = (g.metrics || {})[key] || {};
    return `<tr><td>${name}</td><td>${aggText(agg, fmt)}</td><td>${minMaxText(agg, fmt)}</td><td>${agg.n || 0}</td></tr>`;
  }).join("");
  return `<table><thead><tr><th>指标</th><th>均值 ± 标准差</th><th>min–max</th><th>n</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function toggleRunRow(body, index, forceOpen) {
  const target = body.querySelector(`tr.papers-row[data-papers="${index}"]`);
  if (!target) return;
  const open = target.style.display !== "none";
  if (forceOpen === true && open) return;
  target.style.display = open ? "none" : "";
}

function showDetail(id, scroll) {
  const g = experimentGroups().find(x => x.id === id) || DATA.singles.find(x => x.id === id);
  if (!g) return;
  state.detail = id;
  const card = document.getElementById("detail-card");
  card.style.display = "";
  document.getElementById("detail-title").textContent = g.label + (g.family === "baseline" ? "（基线）" : "");
  const meta = g.family === "baseline"
    ? `${g.score_label} · gold selection: ${g.gold_selection || "—"} · gold papers: ${g.gold_papers ?? "—"}`
    : `n=${g.n_runs} · campaigns: ${(g.campaigns || []).join(", ")} · gold selection: ${g.gold_selection || "—"} · fingerprint: ${g.fingerprint ? g.fingerprint.slice(0, 12) + "…" : "—"} · code: ${g.code_revision || "—"}`;
  document.getElementById("detail-meta").textContent = meta;
  document.getElementById("detail-config").textContent = g.family === "baseline"
    ? "由 literature/<arxiv_id>/literature_hvs_candidates.json 直接评分得到的诊断基线，无 L0/运行操作数据。"
    : "第一部分为该实验跨 run 的整体评分汇总；第二部分列出每次 run 的正式评分，点击 run 行展开 10 篇论文的状态与报错细节。";
  const body = document.getElementById("detail-body");
  if (g.family === "baseline") {
    const m = g.flat || {};
    body.innerHTML = `<table><thead><tr><th>L1 P</th><th>L1 R</th><th>L1 F1</th><th>L2 coverage</th><th>L2 严格一致</th><th>L2 严格端到端</th><th>gold_only</th></tr></thead>
      <tbody><tr><td>${num(m.l1_precision)}</td><td>${num(m.l1_recall)}</td><td>${num(m.l1_f1)}</td><td>${num(m.l2_coverage)}</td><td>${num(m.l2_agreement_strict)}</td><td>${num(m.l2_e2e_strict)}</td><td>${m.gold_only ?? "—"}</td></tr></tbody></table>`;
  } else {
    const rows = g.runs.map((r, i) => {
      const m = r.metrics || {};
      const papers = (r.papers || []).map(paperCard).join("");
      return `<tr class="run-row" data-run="${i}"><td class="mono" style="text-align:left">${esc(r.run_id)}</td>${runMetricsCells(m)}</tr>
        <tr class="papers-row" data-papers="${i}" style="display:none"><td colspan="12">
        ${r.archive_present === false ? '<div class="hint">本地未找到该 run 的归档目录，仅有评分卡数据。</div>' : ""}
        <div class="paper-grid">${papers || '<div class="hint">无论文级细节。</div>'}</div></td></tr>`;
    }).join("");
    body.innerHTML = `<h3 class="detail-sub">整体评分（跨 ${g.n_runs} 次 run 汇总）</h3>
      <div class="chart-scroll">${detailSummaryTable(g)}</div>
      <h3 class="detail-sub">每次 run 评分（点击行展开论文级细节）</h3>
      <div class="chart-scroll"><table><thead><tr><th>run</th><th>roster 交付</th><th>L1 P</th><th>L1 R</th><th>L1 F1</th><th>L2 cov</th><th>L2 严格一致</th><th>L2 严格 e2e</th><th>gold_only</th><th>tokens</th><th>耗时</th><th>成本</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    body.querySelectorAll(".run-row").forEach(row => {
      row.addEventListener("click", () => {
        toggleRunRow(body, row.getAttribute("data-run"));
      });
    });
    const expandRun = document.getElementById("detail-card").getAttribute("data-expand-run");
    if (expandRun != null && expandRun !== "") {
      toggleRunRow(body, expandRun, true);
      document.getElementById("detail-card").removeAttribute("data-expand-run");
    }
  }
  if (scroll !== false) card.scrollIntoView({behavior: "smooth", block: "start"});
}

function renderSingles() {
  const card = document.getElementById("singles-card");
  if (!DATA.singles.length) { card.style.display = "none"; return; }
  card.style.display = "";
  const rows = DATA.singles.map(g => {
    const r = g.runs[0] || {metrics: {}};
    const m = r.metrics || {};
    return `<tr class="run-row" data-exp="${esc(g.id)}"><td>${esc(g.label)}</td>${runMetricsCells(m)}</tr>`;
  }).join("");
  document.getElementById("singles-body").innerHTML = `<div class="chart-scroll"><table><thead><tr><th>配置</th><th>roster 交付</th><th>L1 P</th><th>L1 R</th><th>L1 F1</th><th>L2 cov</th><th>L2 严格一致</th><th>L2 严格 e2e</th><th>gold_only</th><th>tokens</th><th>耗时</th><th>成本</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  card.querySelectorAll(".run-row").forEach(row => {
    row.addEventListener("click", () => showDetail(row.getAttribute("data-exp")));
  });
}

function render() {
  renderChips();
  renderCompare();
  const groups = state.comparing && selectedGroups().length >= 2 ? selectedGroups() : experimentGroups();
  renderQualityChart(groups);
  if (!state.comparing) renderOverview();
  else document.getElementById("overview-sections").innerHTML = "";
  if (state.detail) { const keep = state.detail; state.detail = null; showDetail(keep, false); }
  renderSingles();
}

document.getElementById("compare-btn").onclick = () => {
  if (selectedGroups().length < 2) { alert("请先勾选两个及以上实验。"); return; }
  state.comparing = true; render();
};
document.getElementById("reset-btn").onclick = () => { state.comparing = false; state.selected.clear(); render(); };

document.getElementById("subtitle").textContent =
  `生成时间：${DATA.generated_at} · 数据：正式评分卡（公开聚合）+ 本地 run 归档（操作细节） · 分层报告 L0 / L1 / L2，无综合分`;
document.getElementById("footnotes").innerHTML = DATA.footnotes.map(esc).join("<br>");
render();
const hashMatch = location.hash.match(/exp=([A-Za-z0-9_-]+)/);
if (hashMatch) {
  const runMatch = location.hash.match(/run=(\\d+)/);
  if (runMatch) document.getElementById("detail-card").setAttribute("data-expand-run", runMatch[1]);
  showDetail(hashMatch[1]);
}
const compareMatch = location.hash.match(/compare=([A-Za-z0-9_%,-]+)/);
if (compareMatch) {
  compareMatch[1].split(",").forEach(id => { if (id) state.selected.add(id); });
  if (selectedGroups().length >= 2) { state.comparing = true; render(); }
}
</script>
</body>
</html>
"""

FOOTNOTES = [
    "质量指标：L1 F1 为候选身份 micro F1；L2 coverage 为 gold 核心量被覆盖的比例；L2 严格端到端为严格匹配占全部 gold 量的比例（与 L1 召回耦合，按规则不与 L1 合成单一分数）。",
    "误差线：跨 run 的样本标准差（n-1）；n=1 与基线无误差线。",
    "基线：literature/<arxiv_id>/literature_hvs_candidates.json 对相同 gold selection（dev-primary-v1）的诊断评分，无 L0 交付与运行操作概念。",
    "交付率 / 耗时 / tokens / 成本为 L0 与运营指标，仅作背景，不进入质量层。成本按 tokendance-2026-08-03-screenshots-v1 快照估算；V6 run 取自评分卡，V5 run（GLM-5.2 与 V5 Flash）取自公开 legacy_dev10 成本清单。V5 评分卡没有 L0 块，其 roster/core 交付率取自密封 run_manifest.json 的 l1_roster_delivery / l2_core_field_delivery（与 V6 L0 同义，只是命名不同）；V5 未记录首轮格式通过率。",
    "报错细节来自本地 run 归档的 paper_result.json（failure code 与操作错误消息），不包含任何 gold 条目内容。",
    "GLM R2/R3 等历史配置见附录与 benchmark/benchmark_implementation.md；配额中断的两次 field-high run 未被评分，按约定不属于科学证据，不在本报告中。",
]


def render_html(data: dict[str, Any], generated_at: str) -> str:
    payload = {
        "generated_at": generated_at,
        "experiments": data["experiments"],
        "singles": data["singles"],
        "baseline": data["baseline"],
        "footnotes": FOOTNOTES,
    }
    json_text = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return HTML_PAGE.replace("__DATA__", json_text)


def write_report(output_dir: Path, html_text: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "dev_report.html"
    path.write_text(html_text, encoding="utf-8")
    return path
