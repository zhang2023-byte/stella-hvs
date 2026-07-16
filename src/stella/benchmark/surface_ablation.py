"""Private paired diagnostics for FULL versus CORE+PROV extraction runs.

The loader reduces private scoring details to aggregate L2 status counts as
soon as they are read.  The returned summary contains no candidate identity,
quantity value, quote, or row-level scoring record.
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import papers_for_split, sha256_file
from stella.benchmark.scoring import STRICT_STATUSES, _ci
from stella.benchmark.task_surfaces import CORE_PROV, FULL
from stella.benchmark.run_contract import (
    build_method_fingerprint,
    require_run_manifest_delivery_contract,
)
from stella.benchmark.paths import validate_path_segment
from stella.schema_registry import require_schema, schema_ref

DEFAULT_ITERATIONS = 2000
DEFAULT_SEED = 20260706
HEADLINE_KEYS = (
    "l1_micro_f1",
    "l2_agreement_over_compared_strict",
    "l2_delivery_end_to_end_strict",
)
TOKEN_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "total_tokens",
    "prompt_cache_hit_tokens",
)


@dataclass(frozen=True)
class PaperCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    strict: int = 0
    compared: int = 0
    gold_quantities: int = 0


@dataclass
class LoadedRun:
    run_id: str
    surface: str
    config: dict[str, Any]
    manifest: dict[str, Any]
    scorecard: dict[str, Any]
    counts: dict[str, PaperCounts]
    context_hashes: dict[str, str]
    resources: dict[str, int]
    scorecard_sha256: str
    run_manifest_sha256: str


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is missing or invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def _l2_counts(detail: dict[str, Any]) -> tuple[int, int, int]:
    if detail.get("gold_status") != "candidates_found":
        return 0, 0, 0
    strict = compared = gold_quantities = 0
    rows: list[dict[str, Any]] = []
    for pair in detail.get("pairs") or []:
        if isinstance(pair, dict):
            rows.extend(row for row in pair.get("l2") or [] if isinstance(row, dict))
    for missed in detail.get("unmatched_gold") or []:
        if isinstance(missed, dict):
            rows.extend(row for row in missed.get("l2") or [] if isinstance(row, dict))
    for row in rows:
        status = str(row.get("status") or "")
        if status == "ai_only":
            continue
        gold_quantities += 1
        if status == "gold_only":
            continue
        compared += 1
        if status in STRICT_STATUSES:
            strict += 1
    return strict, compared, gold_quantities


def _paper_counts(
    scorecard: dict[str, Any], details: dict[str, Any], expected: list[str]
) -> dict[str, PaperCounts]:
    l1_by_paper = {
        str(row.get("arxiv_id")): row
        for row in (scorecard.get("l1") or {}).get("per_paper") or []
        if isinstance(row, dict)
    }
    detail_by_paper = {
        str(row.get("arxiv_id")): row
        for row in details.get("papers") or []
        if isinstance(row, dict)
    }
    if set(l1_by_paper) != set(expected) or set(detail_by_paper) != set(expected):
        raise ValueError("scored per-paper membership does not match the dev cohort")
    result: dict[str, PaperCounts] = {}
    for arxiv_id in expected:
        l1 = l1_by_paper[arxiv_id]
        strict, compared, total = _l2_counts(detail_by_paper[arxiv_id])
        result[arxiv_id] = PaperCounts(
            tp=int(l1.get("tp") or 0),
            fp=int(l1.get("fp") or 0),
            fn=int(l1.get("fn") or 0),
            strict=strict,
            compared=compared,
            gold_quantities=total,
        )
    return result


def _run_resources(run_dir: Path, expected: list[str], method: str) -> dict[str, int]:
    totals = {key: 0 for key in TOKEN_KEYS}
    totals.update({"repair_rounds": 0, "api_calls": 0})
    for arxiv_id in expected:
        path = run_dir / arxiv_id / "report.json"
        if not path.is_file():
            continue
        report = _load_json(path, "paper report")
        usage = report.get("usage_totals") or {}
        for key in TOKEN_KEYS:
            value = usage.get(key)
            if isinstance(value, int):
                totals[key] += value
        totals["repair_rounds"] += int(report.get("repair_rounds") or 0)
        response_count = len(list((run_dir / arxiv_id / "attempts").glob("*.response.json")))
        if response_count:
            totals["api_calls"] += response_count
        elif method == "B":
            totals["api_calls"] += int(report.get("scaffold_attempts") or 0)
            totals["api_calls"] += int(report.get("batch_calls") or 0)
            totals["api_calls"] += int(report.get("review_calls") or 0)
        else:
            # Fallback for synthetic/legacy reports without request archives.
            totals["api_calls"] += int(report.get("plan_calls") or 0)
            totals["api_calls"] += int(report.get("candidate_calls") or 0)
            totals["api_calls"] += int(report.get("review_calls") or 0)
    return totals


def _method_without_surface(method: dict[str, Any]) -> dict[str, Any]:
    reduced = copy.deepcopy(method)
    parameters = reduced.get("parameters")
    if isinstance(parameters, dict):
        parameters.pop("task_surface", None)
        parameters.pop("task_surface_sha256", None)
    return reduced


def validate_pair_metadata(full: LoadedRun, core: LoadedRun, method: str) -> None:
    expected_producer = {
        "B": "stella-benchmark-extraction",
        "C": "stella-agentic-extraction",
    }[method]
    if full.surface != FULL or core.surface != CORE_PROV:
        raise ValueError("run pair must be ordered FULL then CORE+PROV")
    for run in (full, core):
        run_method = run.config.get("method") or {}
        if run_method.get("producer") != expected_producer:
            raise ValueError(f"run {run.run_id} does not belong to method {method}")
        models = run_method.get("models") or {}
        parameters = run_method.get("parameters") or {}
        if not models.get("reviewer") or parameters.get("reviewer_enabled") is not True:
            raise ValueError(
                f"run {run.run_id} is not a reviewer-backed default method"
            )
    stable_config_keys = ("mode", "campaign", "split", "expected_papers", "code")
    drift = [key for key in stable_config_keys if full.config.get(key) != core.config.get(key)]
    if drift:
        raise ValueError("paired run contract mismatch: " + ", ".join(drift))
    if _method_without_surface(full.config["method"]) != _method_without_surface(
        core.config["method"]
    ):
        raise ValueError("paired method settings differ beyond task surface")
    full_parameters = full.config["method"].get("parameters") or {}
    core_parameters = core.config["method"].get("parameters") or {}
    if full_parameters.get("task_surface_sha256") == core_parameters.get(
        "task_surface_sha256"
    ):
        raise ValueError("FULL and CORE task-surface hashes must differ")
    if full.context_hashes != core.context_hashes:
        raise ValueError("paired context-manifest input hashes differ")
    full_formal = full.scorecard.get("formal") or {}
    core_formal = core.scorecard.get("formal") or {}
    for key in ("campaign", "split", "gold_snapshot_sha256"):
        if full_formal.get(key) != core_formal.get(key):
            raise ValueError(f"paired scoring cohort mismatch: {key}")


def _load_run(
    *,
    run_id: str,
    surface: str,
    method: str,
    runs_dir: Path,
    scoring_dir: Path,
    details_dir: Path,
    campaign_ref: dict[str, str],
    expected: list[str],
) -> LoadedRun:
    run_dir = runs_dir / run_id
    config_path = run_dir / "run_config.json"
    manifest_path = run_dir / "run_manifest.json"
    scorecard_path = scoring_dir / run_id / "scorecard.json"
    details_path = details_dir / run_id / "details.json"
    config = _load_json(config_path, "run config")
    manifest = _load_json(manifest_path, "sealed run manifest")
    scorecard = _load_json(scorecard_path, "public scorecard")
    details = _load_json(details_path, "private scoring details")
    require_schema(config, "benchmark.run_config", require_current=True)
    require_schema(manifest, "benchmark.run_manifest", require_current=True)
    require_run_manifest_delivery_contract(manifest)
    require_schema(scorecard, "benchmark.scorecard", require_current=True)
    require_schema(details, "benchmark.scoring_details", require_current=True)
    if config.get("mode") != "formal" or config.get("split") != "dev":
        raise ValueError(f"run {run_id} is not a formal dev run")
    if config.get("campaign") != campaign_ref or manifest.get("campaign") != campaign_ref:
        raise ValueError(f"run {run_id} campaign binding mismatch")
    if config.get("expected_papers") != expected:
        raise ValueError(f"run {run_id} dev membership mismatch")
    if manifest.get("split") != "dev":
        raise ValueError(f"run {run_id} sealed split mismatch")
    if (manifest.get("leakage_audit") or {}).get("status") != "clean":
        raise ValueError(f"run {run_id} lacks a clean leakage audit")
    if manifest.get("run_config_sha256") != sha256_file(config_path):
        raise ValueError(f"run {run_id} sealed config hash mismatch")
    if manifest.get("method_fingerprint") != config.get("method_fingerprint"):
        raise ValueError(f"run {run_id} fingerprint mismatch")
    if build_method_fingerprint(config.get("method") or {}) != config.get(
        "method_fingerprint"
    ):
        raise ValueError(f"run {run_id} method fingerprint is not canonical")
    outcomes = manifest.get("papers") or {}
    delivered = [
        paper
        for key in ("valid", "invalid", "missing")
        for paper in outcomes.get(key) or []
    ]
    if sorted(delivered) != sorted(expected) or len(delivered) != len(set(delivered)):
        raise ValueError(f"run {run_id} sealed outcomes do not cover dev")
    parameters = (config.get("method") or {}).get("parameters") or {}
    if parameters.get("task_surface") != surface:
        raise ValueError(f"run {run_id} has the wrong task surface")
    if not str(parameters.get("task_surface_sha256") or ""):
        raise ValueError(f"run {run_id} lacks task-surface provenance")
    formal = scorecard.get("formal") or {}
    if formal.get("run_id") != run_id:
        raise ValueError(f"scorecard for {run_id} is bound to another run")
    if scorecard.get("run_label") != run_id or details.get("run_label") != run_id:
        raise ValueError(f"scoring label for {run_id} must equal the run id")
    if formal.get("campaign") != campaign_ref or formal.get("split") != "dev":
        raise ValueError(f"scorecard for {run_id} has a different cohort")
    if formal.get("method_fingerprint") != config.get("method_fingerprint"):
        raise ValueError(f"scorecard for {run_id} has a different fingerprint")
    actual_manifest_hash = sha256_file(manifest_path)
    if formal.get("run_manifest_sha256") != actual_manifest_hash:
        raise ValueError(f"scorecard for {run_id} has a stale run manifest")
    if details.get("formal") != formal:
        raise ValueError(f"private details for {run_id} have different formal bindings")
    delivery_counts = scorecard.get("delivery_counts") or {}
    for status in ("valid", "invalid", "missing"):
        if int(delivery_counts.get(status) or 0) != len(outcomes.get(status) or []):
            raise ValueError(f"scorecard delivery counts for {run_id} are stale")
    context_hashes: dict[str, str] = {}
    for arxiv_id in expected:
        context_path = run_dir / arxiv_id / "context_manifest.json"
        if not context_path.is_file():
            raise ValueError(f"run {run_id} lacks context manifest for {arxiv_id}")
        context_hash = sha256_file(context_path)
        recorded = (
            ((manifest.get("artifacts") or {}).get(arxiv_id) or {}).get(
                "context_manifest.json"
            )
            or {}
        )
        if recorded.get("sha256") != context_hash:
            raise ValueError(f"sealed context manifest changed for {run_id}/{arxiv_id}")
        context_hashes[arxiv_id] = context_hash
    return LoadedRun(
        run_id=run_id,
        surface=surface,
        config=config,
        manifest=manifest,
        scorecard=scorecard,
        counts=_paper_counts(scorecard, details, expected),
        context_hashes=context_hashes,
        resources=_run_resources(run_dir, expected, method),
        scorecard_sha256=sha256_file(scorecard_path),
        run_manifest_sha256=actual_manifest_hash,
    )


def _metrics(counts: list[PaperCounts]) -> dict[str, float | None]:
    tp = sum(item.tp for item in counts)
    fp = sum(item.fp for item in counts)
    fn = sum(item.fn for item in counts)
    l1_denominator = 2 * tp + fp + fn
    strict = sum(item.strict for item in counts)
    compared = sum(item.compared for item in counts)
    total = sum(item.gold_quantities for item in counts)
    return {
        "l1_micro_f1": (2 * tp / l1_denominator) if l1_denominator else None,
        "l2_agreement_over_compared_strict": strict / compared if compared else None,
        "l2_delivery_end_to_end_strict": strict / total if total else None,
    }


def paired_bootstrap(
    pairs: list[tuple[LoadedRun, LoadedRun]],
    papers: list[str],
    *,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> dict[str, dict[str, Any]]:
    if not pairs or not papers:
        raise ValueError("paired bootstrap requires run pairs and papers")
    full_point = _metrics(
        [pair[0].counts[paper] for pair in pairs for paper in papers]
    )
    core_point = _metrics(
        [pair[1].counts[paper] for pair in pairs for paper in papers]
    )
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {key: [] for key in HEADLINE_KEYS}
    for _ in range(iterations):
        full_sample: list[PaperCounts] = []
        core_sample: list[PaperCounts] = []
        for _ in pairs:
            pair = pairs[rng.randrange(len(pairs))]
            for _ in papers:
                paper = papers[rng.randrange(len(papers))]
                full_sample.append(pair[0].counts[paper])
                core_sample.append(pair[1].counts[paper])
        full_metrics = _metrics(full_sample)
        core_metrics = _metrics(core_sample)
        for key in HEADLINE_KEYS:
            if full_metrics[key] is not None and core_metrics[key] is not None:
                samples[key].append(core_metrics[key] - full_metrics[key])
    return {
        key: {
            "full": full_point[key],
            "core": core_point[key],
            "delta_core_minus_full": (
                core_point[key] - full_point[key]
                if full_point[key] is not None and core_point[key] is not None
                else None
            ),
            "paired_bootstrap_ci95": _ci(samples[key]),
        }
        for key in HEADLINE_KEYS
    }


def decide(
    headline: dict[str, dict[str, Any]],
    *,
    full_unavailable: int,
    core_unavailable: int,
) -> dict[str, Any]:
    deltas = [headline[key]["delta_core_minus_full"] for key in HEADLINE_KEYS]
    cis = [headline[key]["paired_bootstrap_ci95"] for key in HEADLINE_KEYS]
    defined = all(value is not None for value in deltas) and all(ci is not None for ci in cis)
    core_quality = defined and all(value >= 0 for value in deltas)
    core_strict = defined and any(ci[0] > 0 for ci in cis)
    core_delivery = core_unavailable <= full_unavailable
    if core_quality and core_strict and core_delivery:
        return {
            "status": "core_wins",
            "reasons": [
                "core_noninferior_on_all_headlines",
                "core_strictly_better_on_at_least_one_paired_ci",
                "core_unavailable_delivery_not_higher",
            ],
            "core_first_triggered": True,
        }
    full_quality = defined and all(value <= 0 for value in deltas)
    full_strict = defined and any(ci[1] < 0 for ci in cis)
    full_delivery = full_unavailable <= core_unavailable
    if full_quality and full_strict and full_delivery:
        return {
            "status": "full_wins",
            "reasons": [
                "full_noninferior_on_all_headlines",
                "full_strictly_better_on_at_least_one_paired_ci",
                "full_unavailable_delivery_not_higher",
            ],
            "core_first_triggered": False,
        }
    reasons = []
    if not defined:
        reasons.append("undefined_headline_or_ci")
    if not core_quality and not full_quality:
        reasons.append("mixed_headline_directions")
    if not core_strict and not full_strict:
        reasons.append("no_strict_paired_ci_advantage")
    if core_unavailable > full_unavailable:
        reasons.append("core_unavailable_delivery_higher")
    if full_unavailable > core_unavailable:
        reasons.append("full_unavailable_delivery_higher")
    return {
        "status": "inconclusive",
        "reasons": reasons or ["win_gate_not_met"],
        "core_first_triggered": False,
    }


def _sum_resources(runs: list[LoadedRun]) -> dict[str, int]:
    keys = (*TOKEN_KEYS, "repair_rounds", "api_calls")
    return {key: sum(run.resources.get(key, 0) for run in runs) for key in keys}


def _delta(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {key: right[key] - left[key] for key in left}


def analyze_surface_ablation(
    *,
    workspace: Path,
    campaign_path: Path,
    method: str,
    full_run_ids: list[str],
    core_run_ids: list[str],
    runs_dir: Path,
    scoring_dir: Path,
    details_dir: Path,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    if method not in {"B", "C"}:
        raise ValueError("method must be B or C")
    if not full_run_ids or len(full_run_ids) != len(core_run_ids):
        raise ValueError("FULL and CORE run counts must be equal and non-zero")
    full_run_ids = [validate_path_segment(run_id, "FULL run id") for run_id in full_run_ids]
    core_run_ids = [validate_path_segment(run_id, "CORE run id") for run_id in core_run_ids]
    campaign = _load_json(campaign_path, "campaign manifest")
    require_schema(campaign, "benchmark.campaign", require_current=True)
    expected = papers_for_split(campaign, "dev")
    if len(expected) != 10:
        raise ValueError("surface ablation requires the frozen 10-paper dev cohort")
    campaign_ref = {
        "campaign_id": str(campaign.get("campaign_id") or ""),
        "sha256": sha256_file(campaign_path),
    }
    full_runs = [
        _load_run(
            run_id=run_id,
            surface=FULL,
            method=method,
            runs_dir=runs_dir,
            scoring_dir=scoring_dir,
            details_dir=details_dir,
            campaign_ref=campaign_ref,
            expected=expected,
        )
        for run_id in full_run_ids
    ]
    core_runs = [
        _load_run(
            run_id=run_id,
            surface=CORE_PROV,
            method=method,
            runs_dir=runs_dir,
            scoring_dir=scoring_dir,
            details_dir=details_dir,
            campaign_ref=campaign_ref,
            expected=expected,
        )
        for run_id in core_run_ids
    ]
    pairs = list(zip(full_runs, core_runs, strict=True))
    for full, core in pairs:
        validate_pair_metadata(full, core, method)
    baseline_full = full_runs[0]
    baseline_core = core_runs[0]
    for run in full_runs[1:]:
        if run.config.get("method_fingerprint") != baseline_full.config.get("method_fingerprint"):
            raise ValueError("FULL replicates do not share one fingerprint")
        if run.context_hashes != baseline_full.context_hashes:
            raise ValueError("FULL replicate context hashes differ")
    for run in core_runs[1:]:
        if run.config.get("method_fingerprint") != baseline_core.config.get("method_fingerprint"):
            raise ValueError("CORE replicates do not share one fingerprint")
        if run.context_hashes != baseline_core.context_hashes:
            raise ValueError("CORE replicate context hashes differ")
    formal_bindings = [run.scorecard.get("formal") or {} for run in full_runs + core_runs]
    snapshot_hashes = {binding.get("gold_snapshot_sha256") for binding in formal_bindings}
    if len(snapshot_hashes) != 1:
        raise ValueError("runs do not share one scoring snapshot")
    headline = paired_bootstrap(
        pairs, expected, iterations=iterations, seed=seed
    )
    full_delivery = {
        key: sum(int((run.scorecard.get("delivery_counts") or {}).get(key) or 0) for run in full_runs)
        for key in ("valid", "invalid", "missing")
    }
    core_delivery = {
        key: sum(int((run.scorecard.get("delivery_counts") or {}).get(key) or 0) for run in core_runs)
        for key in ("valid", "invalid", "missing")
    }
    full_unavailable = full_delivery["invalid"] + full_delivery["missing"]
    core_unavailable = core_delivery["invalid"] + core_delivery["missing"]
    full_resources = _sum_resources(full_runs)
    core_resources = _sum_resources(core_runs)
    return {
        "schema": schema_ref("benchmark.extraction_surface_ablation"),
        "campaign": campaign_ref,
        "split": "dev",
        "method": method,
        "cohort": {
            "paper_count": len(expected),
            "gold_snapshot_sha256": next(iter(snapshot_hashes)),
        },
        "bootstrap": {
            "iterations": iterations,
            "seed": seed,
            "resample_unit": "replicate_pair_then_paper",
        },
        "run_pairs": [
            {
                "full_run_id": full.run_id,
                "core_run_id": core.run_id,
                "full_fingerprint": full.config["method_fingerprint"],
                "core_fingerprint": core.config["method_fingerprint"],
                "full_task_surface_sha256": full.config["method"]["parameters"]["task_surface_sha256"],
                "core_task_surface_sha256": core.config["method"]["parameters"]["task_surface_sha256"],
                "full_run_manifest_sha256": full.run_manifest_sha256,
                "core_run_manifest_sha256": core.run_manifest_sha256,
                "full_scorecard_sha256": full.scorecard_sha256,
                "core_scorecard_sha256": core.scorecard_sha256,
            }
            for full, core in pairs
        ],
        "headline": headline,
        "delivery": {
            "full": full_delivery,
            "core": core_delivery,
            "delta_core_minus_full": _delta(full_delivery, core_delivery),
        },
        "resources": {
            "full": full_resources,
            "core": core_resources,
            "delta_core_minus_full": _delta(full_resources, core_resources),
        },
        "decision": decide(
            headline,
            full_unavailable=full_unavailable,
            core_unavailable=core_unavailable,
        ),
    }
