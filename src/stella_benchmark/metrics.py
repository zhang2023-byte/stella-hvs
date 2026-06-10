"""Scoring metrics: variant extractions against gold-standard records."""

from __future__ import annotations

import random
from typing import Any

from astropy import units as u

from .alignment import normalize_identifier
from .field_specs import FIELD_SPECS, FieldSpec, get_by_path, value_snapshot

STRICT_REL_TOL = 1e-6
LOOSE_REL_TOL = 1e-2
ABS_TOL = 1e-12

# v7 unit spellings that astropy's generic parser rejects.
UNIT_ALIASES = {
    "km s^-1": "km/s",
    "km s-1": "km/s",
    "mas yr^-1": "mas/yr",
    "mas yr-1": "mas/yr",
    "mas/yr": "mas/yr",
    "uas": "uarcsec",
    "muas": "uarcsec",
    "micro-arcsecond": "uarcsec",
    "deg": "deg",
    "degree": "deg",
    "degrees": "deg",
}


def _normalize_unit_text(text: str) -> str:
    return " ".join(str(text or "").split())


def parse_unit(text: str) -> u.UnitBase | None:
    normalized = _normalize_unit_text(text)
    if not normalized:
        return None
    candidate = UNIT_ALIASES.get(normalized, normalized)
    try:
        return u.Unit(candidate)
    except Exception:
        return None


def parse_float(text: Any) -> float | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def numeric_match(gold: float, variant: float, *, rel_tol: float, abs_tol: float = ABS_TOL) -> bool:
    return abs(variant - gold) <= max(abs_tol, rel_tol * abs(gold))


def convert_value(value: float, from_unit_text: str, to_unit_text: str) -> float | None:
    if _normalize_unit_text(from_unit_text) == _normalize_unit_text(to_unit_text):
        return value
    from_unit = parse_unit(from_unit_text)
    to_unit = parse_unit(to_unit_text)
    if from_unit is None or to_unit is None:
        return None
    try:
        return float((value * from_unit).to(to_unit).value)
    except Exception:
        return None


def _quantity_matches(gold: dict[str, str], variant: dict[str, str], *, rel_tol: float) -> bool:
    gold_value = parse_float(gold.get("value"))
    variant_value = parse_float(variant.get("value"))
    if gold_value is None or variant_value is None:
        # Non-numeric values (e.g. sexagesimal coordinates) compare as text.
        return str(gold.get("value") or "").strip() == str(variant.get("value") or "").strip()
    converted = convert_value(variant_value, variant.get("unit", ""), gold.get("unit", ""))
    if converted is None:
        return False
    if not numeric_match(gold_value, converted, rel_tol=rel_tol):
        return False
    return _errors_match(gold, variant, rel_tol=rel_tol)


def _errors_match(gold: dict[str, str], variant: dict[str, str], *, rel_tol: float) -> bool:
    def parts(record: dict[str, str]) -> tuple[float | None, float | None, float | None]:
        return (
            parse_float(record.get("error")),
            parse_float(record.get("lower_error")),
            parse_float(record.get("upper_error")),
        )

    g_sym, g_lo, g_hi = parts(gold)
    v_sym, v_lo, v_hi = parts(variant)

    def one(g: float | None, v: float | None) -> bool:
        if g is None and v is None:
            return True
        if g is None or v is None:
            return False
        converted = convert_value(v, variant.get("unit", ""), gold.get("unit", ""))
        if converted is None:
            return False
        return numeric_match(g, converted, rel_tol=rel_tol)

    # Symmetric-vs-asymmetric mismatches count as wrong unless numerically identical.
    if g_sym is not None and v_sym is None and v_lo is not None and v_hi is not None:
        return one(g_sym, v_lo) and one(g_sym, v_hi)
    if g_sym is None and g_lo is not None and g_hi is not None and v_sym is not None:
        return one(g_lo, v_sym) and one(g_hi, v_sym)
    return one(g_sym, v_sym) and one(g_lo, v_lo) and one(g_hi, v_hi)


def _identifier_set(values: list[str] | None) -> set[str]:
    return {normalize_identifier(value) for value in values or [] if str(value).strip()}


def field_outcome(
    spec: FieldSpec,
    gold_candidate: dict[str, Any],
    variant_candidate: dict[str, Any],
    *,
    rel_tol: float,
) -> str | None:
    """correct | wrong | missing | spurious; None when absent on both sides."""
    gold_snapshot = value_snapshot(spec, get_by_path(gold_candidate, spec.path))
    variant_snapshot = value_snapshot(spec, get_by_path(variant_candidate, spec.path))
    if gold_snapshot is None and variant_snapshot is None:
        return None
    if gold_snapshot is None:
        return "spurious"
    if variant_snapshot is None:
        return "missing"
    if spec.kind in {"quantity", "coordinate"}:
        return "correct" if _quantity_matches(gold_snapshot, variant_snapshot, rel_tol=rel_tol) else "wrong"
    if spec.kind == "identifier_set":
        return (
            "correct"
            if _identifier_set(gold_snapshot) == _identifier_set(variant_snapshot)
            else "wrong"
        )
    if spec.kind == "label_set":
        return "correct" if set(gold_snapshot) == set(variant_snapshot) else "wrong"
    if spec.kind == "identifier":
        return (
            "correct"
            if normalize_identifier(str(gold_snapshot)) == normalize_identifier(str(variant_snapshot))
            else "wrong"
        )
    return "correct" if gold_snapshot == variant_snapshot else "wrong"


def _candidate_keys(candidate: dict[str, Any]) -> tuple[str, set[str]]:
    identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
    gaia = normalize_identifier(str(identifiers.get("gaia_source_id") or ""))
    ident = {
        normalize_identifier(str(item.get("value") or ""))
        for item in identifiers.get("all") or []
        if isinstance(item, dict) and str(item.get("value") or "").strip()
    }
    return gaia, ident


def match_candidates(
    gold_candidates: list[dict[str, Any]],
    variant_candidates: list[dict[str, Any]],
) -> list[tuple[int, int]]:
    """One-to-one (gold_index, variant_index) pairs; gaia tier first, then overlap."""
    gold_keys = [_candidate_keys(candidate) for candidate in gold_candidates]
    variant_keys = [_candidate_keys(candidate) for candidate in variant_candidates]
    pairs: list[tuple[int, int]] = []
    used_gold: set[int] = set()
    used_variant: set[int] = set()

    for g_index, (g_gaia, _) in enumerate(gold_keys):
        if not g_gaia:
            continue
        for v_index, (v_gaia, _) in enumerate(variant_keys):
            if v_index in used_variant or not v_gaia:
                continue
            if g_gaia == v_gaia:
                pairs.append((g_index, v_index))
                used_gold.add(g_index)
                used_variant.add(v_index)
                break

    overlap_edges: list[tuple[int, int, int]] = []
    for g_index, (_, g_ident) in enumerate(gold_keys):
        if g_index in used_gold:
            continue
        for v_index, (_, v_ident) in enumerate(variant_keys):
            if v_index in used_variant:
                continue
            overlap = len(g_ident & v_ident)
            if overlap:
                overlap_edges.append((overlap, g_index, v_index))
    overlap_edges.sort(key=lambda edge: (-edge[0], edge[1], edge[2]))
    for _, g_index, v_index in overlap_edges:
        if g_index in used_gold or v_index in used_variant:
            continue
        pairs.append((g_index, v_index))
        used_gold.add(g_index)
        used_variant.add(v_index)
    pairs.sort()
    return pairs


def status_bucket(status: str) -> str:
    if status in {"candidates_found", "no_candidates"}:
        return status
    return "other"


def score_paper(
    gold_payload: dict[str, Any],
    variant_payload: dict[str, Any] | None,
    *,
    strict_rel_tol: float = STRICT_REL_TOL,
    loose_rel_tol: float = LOOSE_REL_TOL,
) -> dict[str, Any]:
    gold_candidates = [c for c in gold_payload.get("candidates") or [] if isinstance(c, dict)]
    variant_candidates = (
        [c for c in (variant_payload or {}).get("candidates") or [] if isinstance(c, dict)]
        if variant_payload
        else []
    )
    pairs = match_candidates(gold_candidates, variant_candidates)
    tp = len(pairs)
    fp = len(variant_candidates) - tp
    fn = len(gold_candidates) - tp

    field_counts: dict[str, dict[str, int]] = {}
    for tolerance_name, rel_tol in (("strict", strict_rel_tol), ("loose", loose_rel_tol)):
        for spec in FIELD_SPECS:
            counts = field_counts.setdefault(
                f"{tolerance_name}:{spec.path}",
                {"correct": 0, "wrong": 0, "missing": 0, "spurious": 0},
            )
            for g_index, v_index in pairs:
                outcome = field_outcome(
                    spec, gold_candidates[g_index], variant_candidates[v_index], rel_tol=rel_tol
                )
                if outcome is not None:
                    counts[outcome] += 1

    gold_status = str((gold_payload.get("extraction") or {}).get("status") or "")
    variant_status = (
        str((variant_payload.get("extraction") or {}).get("status") or "")
        if variant_payload
        else "missing"
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "gold_status": gold_status,
        "variant_status": variant_status,
        "field_counts": field_counts,
    }


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def detection_summary(paper_scores: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tp = sum(score["tp"] for score in paper_scores.values())
    fp = sum(score["fp"] for score in paper_scores.values())
    fn = sum(score["fn"] for score in paper_scores.values())
    precision, recall, f1 = precision_recall_f1(tp, fp, fn)

    per_paper_f1: list[float] = []
    for score in paper_scores.values():
        if score["tp"] + score["fp"] + score["fn"] == 0:
            continue
        per_paper_f1.append(precision_recall_f1(score["tp"], score["fp"], score["fn"])[2])
    macro_f1 = sum(per_paper_f1) / len(per_paper_f1) if per_paper_f1 else 0.0

    no_candidate_papers = [
        score for score in paper_scores.values() if score["gold_status"] == "no_candidates"
    ]
    specificity = (
        sum(1 for score in no_candidate_papers if score["fp"] == 0) / len(no_candidate_papers)
        if no_candidate_papers
        else None
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "micro_precision": precision,
        "micro_recall": recall,
        "micro_f1": f1,
        "macro_f1": macro_f1,
        "no_candidate_specificity": specificity,
    }


def bootstrap_micro_ci(
    paper_scores: dict[str, dict[str, Any]],
    *,
    n_resamples: int = 1000,
    seed: int = 0,
    confidence: float = 0.95,
) -> dict[str, list[float]]:
    papers = sorted(paper_scores)
    if not papers:
        return {}
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {"micro_precision": [], "micro_recall": [], "micro_f1": []}
    for _ in range(n_resamples):
        resample = [paper_scores[rng.choice(papers)] for _ in papers]
        tp = sum(score["tp"] for score in resample)
        fp = sum(score["fp"] for score in resample)
        fn = sum(score["fn"] for score in resample)
        precision, recall, f1 = precision_recall_f1(tp, fp, fn)
        samples["micro_precision"].append(precision)
        samples["micro_recall"].append(recall)
        samples["micro_f1"].append(f1)
    lower_q = (1 - confidence) / 2
    upper_q = 1 - lower_q
    result: dict[str, list[float]] = {}
    for name, values in samples.items():
        ordered = sorted(values)
        lower = ordered[int(lower_q * (len(ordered) - 1))]
        upper = ordered[int(upper_q * (len(ordered) - 1))]
        result[name] = [lower, upper]
    return result


def paper_status_summary(paper_scores: dict[str, dict[str, Any]]) -> dict[str, Any]:
    buckets = ("candidates_found", "no_candidates", "other")
    confusion = {gold: {variant: 0 for variant in buckets + ("missing",)} for gold in buckets}
    agree = 0
    for score in paper_scores.values():
        gold = status_bucket(score["gold_status"])
        variant = (
            "missing" if score["variant_status"] == "missing" else status_bucket(score["variant_status"])
        )
        confusion[gold][variant] += 1
        if score["gold_status"] == score["variant_status"]:
            agree += 1
    accuracy = agree / len(paper_scores) if paper_scores else 0.0
    return {"accuracy": accuracy, "confusion": confusion}


def field_summary(paper_scores: dict[str, dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, dict[str, int]] = {}
    for score in paper_scores.values():
        for key, counts in score["field_counts"].items():
            bucket = totals.setdefault(
                key, {"correct": 0, "wrong": 0, "missing": 0, "spurious": 0}
            )
            for outcome, count in counts.items():
                bucket[outcome] += count

    headline_paths = {spec.path for spec in FIELD_SPECS if spec.headline}
    result: dict[str, Any] = {"per_field": {}, "headline": {}}
    for tolerance_name in ("strict", "loose"):
        headline_correct = 0
        headline_total = 0
        for spec in FIELD_SPECS:
            key = f"{tolerance_name}:{spec.path}"
            counts = totals.get(key, {"correct": 0, "wrong": 0, "missing": 0, "spurious": 0})
            gold_present = counts["correct"] + counts["wrong"] + counts["missing"]
            entry = {
                **counts,
                "accuracy": counts["correct"] / gold_present if gold_present else None,
                "value_accuracy": (
                    counts["correct"] / (counts["correct"] + counts["wrong"])
                    if counts["correct"] + counts["wrong"]
                    else None
                ),
            }
            result["per_field"][key] = entry
            if spec.path in headline_paths:
                headline_correct += counts["correct"]
                headline_total += gold_present
        result["headline"][tolerance_name] = {
            "correct": headline_correct,
            "gold_present": headline_total,
            "accuracy": headline_correct / headline_total if headline_total else None,
        }
    return result


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float | None:
    if len(labels_a) != len(labels_b) or not labels_a:
        return None
    total = len(labels_a)
    observed = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / total
    categories = set(labels_a) | set(labels_b)
    expected = sum(
        (labels_a.count(category) / total) * (labels_b.count(category) / total)
        for category in categories
    )
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)
