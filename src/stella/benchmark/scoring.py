"""Phase 4 benchmark scoring: expert gold vs archived AI extractions.

L1 (formal): candidate-set precision/recall/F1 after deterministic identity
matching (``stella.benchmark.identity`` tiers: Gaia id, alias, coordinates),
per paper and aggregated (micro, macro, sampling-weight weighted micro),
false positives on no-candidate papers, paired bootstrap confidence
intervals over papers, and a no-coordinate-tier matching sensitivity check.

L2 (diagnostic draft): per-field value agreement rates for matched pairs
after unit-synonym and probability normalization. Explicitly not a formal
metric yet — the full projection/normalization contract lives in
``docs/schema-v0.2-notes.md`` and lands in a later revision.

Output discipline: the public scorecard contains only counts, rates, and
paper ids. Anything that quotes gold content (candidate identities, values,
matched-pair tables) belongs to the private details document, which is
written next to the external gold store, never inside this workspace.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stella.benchmark.gold import _coordinate_value_degrees
from stella.benchmark.identity import (
    DEFAULT_FALLBACK_TOLERANCE_ARCSEC,
    DEFAULT_PROPAGATED_TOLERANCE_ARCSEC,
    CandidateIdentity,
    identity_from_candidate,
    match_identities,
    normalize_name,
    parse_gaia_id,
)

SCORECARD_SCHEMA_VERSION = "stella.benchmark_scorecard.v0.1"
SCORING_DETAILS_SCHEMA_VERSION = "stella.benchmark_scoring_details.v0.1"
DEFAULT_BOOTSTRAP_ITERATIONS = 2000
DEFAULT_BOOTSTRAP_SEED = 20260706

# Unit spellings treated as identical for L2 draft comparison. Keys are the
# canonical form; values list synonyms as they appear in papers/extractions.
UNIT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "km/s": ("km/s", "km s^-1", "km s-1", "km s⁻¹", "kms^-1", "km/sec"),
    "mas/yr": ("mas/yr", "mas yr^-1", "mas yr-1", "mas yr⁻¹", "mas/year"),
    "mas": ("mas",),
    "deg": ("deg", "degree", "degrees", "°"),
    "kpc": ("kpc",),
    "pc": ("pc",),
}

_UNIT_CANONICAL = {
    synonym: canonical
    for canonical, synonyms in UNIT_SYNONYMS.items()
    for synonym in synonyms
}

_GROUP_KEYS = ("observed_phase_space", "derived_kinematics", "bound_assessment")


# --------------------------------------------------------------------------
# Loading


def load_gold_annotations(gold_dir: Path) -> dict[str, dict[str, Any]]:
    """Return arxiv_id -> gold annotation document (one per paper).

    Papers with multiple annotators are not aggregated here; the
    lexicographically first annotation file is used and a ``_warnings`` key
    records the rest.
    """

    annotations: dict[str, dict[str, Any]] = {}
    for paper_dir in sorted(path for path in gold_dir.iterdir() if path.is_dir()):
        files = sorted(paper_dir.glob("annotation_*.json"))
        if not files:
            continue
        document = json.loads(files[0].read_text(encoding="utf-8"))
        if len(files) > 1:
            document["_warnings"] = [
                f"multiple annotations present, using {files[0].name}; "
                f"ignored: {', '.join(path.name for path in files[1:])}"
            ]
        annotations[str(document.get("arxiv_id") or paper_dir.name)] = document
    return annotations


def load_ai_document(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def load_sampling_weights(manifest_path: Path) -> dict[str, float]:
    if not manifest_path.is_file():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    weights: dict[str, float] = {}
    for entry in payload.get("papers") or []:
        if isinstance(entry, dict) and entry.get("arxiv_id"):
            try:
                weights[str(entry["arxiv_id"])] = float(entry.get("sampling_weight", 1.0))
            except (TypeError, ValueError):
                continue
    return weights


# --------------------------------------------------------------------------
# Identity adaptation (gold side)


def _gold_quantity(candidate: dict[str, Any], field: str) -> dict[str, Any] | None:
    for quantity in candidate.get("quantities") or []:
        if isinstance(quantity, dict) and quantity.get("field") == field:
            return quantity
    return None


def _gold_coordinate_degrees(candidate: dict[str, Any], field: str) -> float | None:
    quantity = _gold_quantity(candidate, field)
    if quantity is None:
        return None
    value = str(quantity.get("value") or "").strip()
    if not value:
        return None
    return _coordinate_value_degrees(field, value, str(quantity.get("unit") or ""))


def _gold_proper_motion(candidate: dict[str, Any], field: str) -> float | None:
    quantity = _gold_quantity(candidate, field)
    if quantity is None:
        return None
    value = str(quantity.get("value") or "").strip()
    unit = str(quantity.get("unit") or "").lower()
    if "mas" not in unit or "yr" not in unit:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def identity_from_gold_candidate(candidate: dict[str, Any]) -> CandidateIdentity:
    names: set[str] = set()
    for value in (
        candidate.get("paper_candidate_id"),
        *(candidate.get("aliases") or []),
    ):
        normalized = normalize_name(value)
        if normalized and parse_gaia_id(value) is None:
            names.add(normalized)
    display = str(
        candidate.get("paper_candidate_id")
        or candidate.get("gaia_source_id")
        or ((candidate.get("aliases") or [""])[0])
    )
    return CandidateIdentity(
        record_id=display,
        gaia=parse_gaia_id(candidate.get("gaia_source_id")),
        names=names,
        ra_deg=_gold_coordinate_degrees(candidate, "observed_phase_space.ra"),
        dec_deg=_gold_coordinate_degrees(candidate, "observed_phase_space.dec"),
        pm_ra_masyr=_gold_proper_motion(candidate, "observed_phase_space.proper_motion_ra"),
        pm_dec_masyr=_gold_proper_motion(candidate, "observed_phase_space.proper_motion_dec"),
        epoch_year=None,
    )


# --------------------------------------------------------------------------
# Matching (greedy, tiered — mirrors identity.match_candidate_sets, with a
# switchable coordinate tier for the sensitivity report)


def match_gold_to_ai(
    gold_identities: list[CandidateIdentity],
    ai_identities: list[CandidateIdentity],
    *,
    allow_coordinates: bool = True,
) -> dict[str, Any]:
    unmatched_gold = set(range(len(gold_identities)))
    unmatched_ai = set(range(len(ai_identities)))
    pairs: list[dict[str, Any]] = []

    def compare(i: int, j: int):
        return match_identities(
            gold_identities[i],
            ai_identities[j],
            propagated_tolerance_arcsec=DEFAULT_PROPAGATED_TOLERANCE_ARCSEC,
            fallback_tolerance_arcsec=DEFAULT_FALLBACK_TOLERANCE_ARCSEC,
        )

    def take(i: int, j: int, method: str, detail: str) -> None:
        unmatched_gold.discard(i)
        unmatched_ai.discard(j)
        pairs.append(
            {"gold_index": i, "ai_index": j, "method": method, "detail": detail}
        )

    for tier in ("gaia_id", "alias"):
        for i in sorted(unmatched_gold):
            for j in sorted(unmatched_ai):
                if j not in unmatched_ai:
                    continue
                result = compare(i, j)
                if result.matched and result.method == tier:
                    take(i, j, result.method, result.detail)
                    break

    if allow_coordinates:
        coordinate_pairs: list[tuple[float, int, int, Any]] = []
        for i in sorted(unmatched_gold):
            for j in sorted(unmatched_ai):
                result = compare(i, j)
                if result.matched and result.method == "coordinates":
                    coordinate_pairs.append(
                        (result.separation_arcsec or 0.0, i, j, result)
                    )
        for _, i, j, result in sorted(
            coordinate_pairs, key=lambda item: (item[0], item[1], item[2])
        ):
            if i in unmatched_gold and j in unmatched_ai:
                take(i, j, result.method, result.detail)

    return {
        "pairs": pairs,
        "unmatched_gold": sorted(unmatched_gold),
        "unmatched_ai": sorted(unmatched_ai),
    }


# --------------------------------------------------------------------------
# L1 metrics


def _rate(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _prf(tp: float, fp: float, fn: float) -> dict[str, float | None]:
    precision = _rate(tp, tp + fp)
    recall = _rate(tp, tp + fn)
    f1: float | None
    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


@dataclass
class PaperScore:
    arxiv_id: str
    gold_status: str
    ai_status: str
    gold_candidates: int
    ai_candidates: int
    tp: int
    fp: int
    fn: int
    match_methods: dict[str, int]
    weight: float
    ai_output_missing: bool

    def public_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "arxiv_id": self.arxiv_id,
            "gold_status": self.gold_status,
            "ai_status": self.ai_status,
            "gold_candidates": self.gold_candidates,
            "ai_candidates": self.ai_candidates,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "sampling_weight": self.weight,
            "match_methods": self.match_methods,
        }
        record.update(_prf(self.tp, self.fp, self.fn))
        if self.ai_output_missing:
            record["ai_output_missing"] = True
        return record


def _micro(scores: list[PaperScore], *, weighted: bool) -> dict[str, Any]:
    tp = sum(score.tp * (score.weight if weighted else 1.0) for score in scores)
    fp = sum(score.fp * (score.weight if weighted else 1.0) for score in scores)
    fn = sum(score.fn * (score.weight if weighted else 1.0) for score in scores)
    payload: dict[str, Any] = {"tp": tp, "fp": fp, "fn": fn}
    payload.update(_prf(tp, fp, fn))
    return payload


def _macro(scores: list[PaperScore]) -> dict[str, Any]:
    precisions = [
        p
        for score in scores
        if (p := _prf(score.tp, score.fp, score.fn)["precision"]) is not None
    ]
    recalls = [
        r
        for score in scores
        if (r := _prf(score.tp, score.fp, score.fn)["recall"]) is not None
    ]
    f1s = [
        f
        for score in scores
        if (f := _prf(score.tp, score.fp, score.fn)["f1"]) is not None
    ]
    return {
        "precision": sum(precisions) / len(precisions) if precisions else None,
        "recall": sum(recalls) / len(recalls) if recalls else None,
        "f1": sum(f1s) / len(f1s) if f1s else None,
        "papers_with_defined_precision": len(precisions),
        "papers_with_defined_recall": len(recalls),
        "papers_with_defined_f1": len(f1s),
    }


def _bootstrap(
    scores: list[PaperScore], *, iterations: int, seed: int
) -> dict[str, Any]:
    rng = random.Random(seed)
    metrics: dict[str, list[float]] = {"precision": [], "recall": [], "f1": []}
    for _ in range(iterations):
        sample = [scores[rng.randrange(len(scores))] for _ in scores]
        micro = _micro(sample, weighted=False)
        for name in metrics:
            value = micro[name]
            if value is not None:
                metrics[name].append(value)

    def ci(values: list[float]) -> list[float] | None:
        if not values:
            return None
        ordered = sorted(values)
        lo = ordered[max(0, int(0.025 * len(ordered)) - 1) if len(ordered) > 40 else 0]
        hi = ordered[min(len(ordered) - 1, int(0.975 * len(ordered)))]
        return [round(lo, 4), round(hi, 4)]

    return {
        "iterations": iterations,
        "seed": seed,
        "resample_unit": "paper",
        "micro_precision_ci95": ci(metrics["precision"]),
        "micro_recall_ci95": ci(metrics["recall"]),
        "micro_f1_ci95": ci(metrics["f1"]),
    }


# --------------------------------------------------------------------------
# L2 draft comparison


def normalize_unit(unit: str) -> str:
    text = unit.strip().lower().replace("  ", " ")
    return _UNIT_CANONICAL.get(text, text)


def _to_float(text: Any) -> float | None:
    value = str(text or "").strip().replace("\u2212", "-")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _ai_quantity_at(candidate: dict[str, Any], field: str) -> dict[str, Any] | None:
    group, _, name = field.partition(".")
    if group not in _GROUP_KEYS:
        return None
    core = candidate.get("core") if isinstance(candidate.get("core"), dict) else {}
    section = core.get(group) if isinstance(core.get(group), dict) else {}
    quantity = section.get(name)
    return quantity if isinstance(quantity, dict) else None


def _probability_field(field: str) -> bool:
    return "probability" in field


def _ai_value_for_compare(field: str, quantity: dict[str, Any]) -> float | None:
    value = _to_float(quantity.get("value"))
    if value is None:
        return None
    unit = str(quantity.get("unit") or "")
    raw = str(quantity.get("raw_value") or "")
    if _probability_field(field) and ("%" in unit or "%" in raw or value > 1.0):
        return value / 100.0
    return value


def compare_quantity(field: str, gold: dict[str, Any], ai: dict[str, Any] | None) -> dict[str, Any]:
    """Classify one gold quantity against the AI candidate's same field."""

    row: dict[str, Any] = {"field": field}
    if ai is None or (
        not str(ai.get("value") or "").strip()
        and not str(ai.get("range_lower") or "").strip()
    ):
        row["status"] = "gold_only"
        return row

    gold_kind = str(gold.get("limit_kind") or "")
    ai_kind = str(ai.get("limit_kind") or "")
    if gold_kind == "range" or ai_kind == "range":
        if gold_kind != ai_kind:
            row["status"] = "limit_kind_mismatch"
            return row
        bounds_equal = _to_float(gold.get("range_lower")) == _to_float(
            ai.get("range_lower")
        ) and _to_float(gold.get("range_upper")) == _to_float(ai.get("range_upper"))
        row["status"] = "value_match" if bounds_equal else "value_mismatch"
        return row

    gold_value = _to_float(gold.get("value"))
    ai_value = _ai_value_for_compare(field, ai)
    if gold_value is None:
        # Sexagesimal coordinates and other verbatim strings: exact text.
        row["status"] = (
            "value_match"
            if str(gold.get("value") or "").strip()
            == str(ai.get("value") or "").strip()
            else "value_mismatch"
        )
        return row
    if _probability_field(field):
        gold_unit = ""
        ai_unit = ""
    else:
        gold_unit = normalize_unit(str(gold.get("unit") or ""))
        ai_unit = normalize_unit(str(ai.get("unit") or ""))
    if ai_value is None:
        row["status"] = "value_mismatch"
        return row
    if gold_unit and ai_unit and gold_unit != ai_unit:
        row["status"] = "unit_mismatch"
        return row
    if abs(gold_value - ai_value) <= 1e-9 * max(1.0, abs(gold_value)):
        row["status"] = "value_match"
    else:
        gold_error = _to_float(gold.get("error"))
        if gold_error and abs(gold_value - ai_value) <= gold_error:
            row["status"] = "within_gold_error"
        else:
            row["status"] = "value_mismatch"
    if gold_kind != ai_kind:
        row["limit_kind_differs"] = True
    return row


def compare_pair_quantities(
    gold_candidate: dict[str, Any], ai_candidate: dict[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for quantity in gold_candidate.get("quantities") or []:
        if not isinstance(quantity, dict):
            continue
        field = str(quantity.get("field") or "")
        ai_quantity = _ai_quantity_at(ai_candidate, field)
        projected = False
        if (
            field == "derived_kinematics.galactic_rest_frame_velocity"
            and (
                ai_quantity is None
                or not str(ai_quantity.get("value") or "").strip()
            )
        ):
            fallback = _ai_quantity_at(
                ai_candidate, "derived_kinematics.total_velocity"
            )
            if fallback is not None and str(fallback.get("value") or "").strip():
                ai_quantity = fallback
                projected = True
        row = compare_quantity(field, quantity, ai_quantity)
        if projected:
            row["projected_from_total_velocity"] = True
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# Paper and run scoring


def _display_gold(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("paper_candidate_id")
        or candidate.get("gaia_source_id")
        or ((candidate.get("aliases") or [""])[0])
    )


def _display_ai(candidate: dict[str, Any], index: int) -> str:
    identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
    return str(
        identifiers.get("record_id")
        or identifiers.get("paper_candidate_id")
        or identifiers.get("gaia_source_id")
        or f"ai-{index:03d}"
    )


def score_paper(
    arxiv_id: str,
    gold_document: dict[str, Any],
    ai_document: dict[str, Any] | None,
    *,
    weight: float,
    allow_coordinates: bool = True,
) -> tuple[PaperScore, dict[str, Any]]:
    """Score one paper. Returns the public PaperScore and the private detail."""

    gold_candidates = [
        candidate
        for candidate in gold_document.get("candidates") or []
        if isinstance(candidate, dict)
    ]
    ai_missing = ai_document is None
    ai_candidates = [
        candidate
        for candidate in ((ai_document or {}).get("candidates") or [])
        if isinstance(candidate, dict)
    ]
    ai_status = str(
        ((ai_document or {}).get("extraction") or {}).get("status") or "missing"
    )
    matching = match_gold_to_ai(
        [identity_from_gold_candidate(candidate) for candidate in gold_candidates],
        [identity_from_candidate(candidate) for candidate in ai_candidates],
        allow_coordinates=allow_coordinates,
    )
    methods: dict[str, int] = {}
    for pair in matching["pairs"]:
        methods[pair["method"]] = methods.get(pair["method"], 0) + 1
    score = PaperScore(
        arxiv_id=arxiv_id,
        gold_status=str(gold_document.get("status") or ""),
        ai_status=ai_status,
        gold_candidates=len(gold_candidates),
        ai_candidates=len(ai_candidates),
        tp=len(matching["pairs"]),
        fp=len(matching["unmatched_ai"]),
        fn=len(matching["unmatched_gold"]),
        match_methods=methods,
        weight=weight,
        ai_output_missing=ai_missing,
    )
    detail = {
        "arxiv_id": arxiv_id,
        "pairs": [
            {
                "gold_id": _display_gold(gold_candidates[pair["gold_index"]]),
                "ai_id": _display_ai(ai_candidates[pair["ai_index"]], pair["ai_index"]),
                "method": pair["method"],
                "detail": pair["detail"],
                "l2": compare_pair_quantities(
                    gold_candidates[pair["gold_index"]],
                    ai_candidates[pair["ai_index"]],
                ),
            }
            for pair in matching["pairs"]
        ],
        "unmatched_gold": [
            _display_gold(gold_candidates[index])
            for index in matching["unmatched_gold"]
        ],
        "unmatched_ai": [
            _display_ai(ai_candidates[index], index)
            for index in matching["unmatched_ai"]
        ],
        "gold_warnings": gold_document.get("_warnings") or [],
    }
    return score, detail


def _l2_summary(details: list[dict[str, Any]]) -> dict[str, Any]:
    per_field: dict[str, dict[str, int]] = {}
    projected = 0
    for detail in details:
        for pair in detail["pairs"]:
            for row in pair["l2"]:
                bucket = per_field.setdefault(
                    row["field"],
                    {
                        "gold_quantities": 0,
                        "value_match": 0,
                        "within_gold_error": 0,
                        "value_mismatch": 0,
                        "unit_mismatch": 0,
                        "limit_kind_mismatch": 0,
                        "gold_only": 0,
                    },
                )
                bucket["gold_quantities"] += 1
                bucket[row["status"]] = bucket.get(row["status"], 0) + 1
                if row.get("projected_from_total_velocity"):
                    projected += 1
    total = sum(bucket["gold_quantities"] for bucket in per_field.values())
    matched = sum(
        bucket["value_match"] + bucket["within_gold_error"]
        for bucket in per_field.values()
    )
    compared = sum(
        bucket["gold_quantities"] - bucket["gold_only"]
        for bucket in per_field.values()
    )
    return {
        "note": (
            "diagnostic draft — unit synonyms and probability normalization "
            "only; the formal L2 projection contract is not implemented yet "
            "(docs/schema-v0.2-notes.md)"
        ),
        "gold_quantities": total,
        "compared": compared,
        "value_agreement": matched,
        "value_agreement_rate_over_compared": _rate(matched, compared),
        "coverage_rate": _rate(compared, total),
        "projected_from_total_velocity": projected,
        "fields": {
            field: bucket for field, bucket in sorted(per_field.items())
        },
    }


def score_run(
    *,
    gold_annotations: dict[str, dict[str, Any]],
    ai_documents: dict[str, dict[str, Any] | None],
    weights: dict[str, float],
    run_label: str,
    run_source: dict[str, Any],
    bootstrap_iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Score every gold paper. Returns (public scorecard, private details)."""

    scores: list[PaperScore] = []
    details: list[dict[str, Any]] = []
    sensitivity_scores: list[PaperScore] = []
    for arxiv_id in sorted(gold_annotations):
        gold_document = gold_annotations[arxiv_id]
        ai_document = ai_documents.get(arxiv_id)
        weight = weights.get(arxiv_id, 1.0)
        score, detail = score_paper(
            arxiv_id, gold_document, ai_document, weight=weight
        )
        scores.append(score)
        details.append(detail)
        sensitivity_scores.append(
            score_paper(
                arxiv_id,
                gold_document,
                ai_document,
                weight=weight,
                allow_coordinates=False,
            )[0]
        )

    negative = [score for score in scores if score.gold_status == "no_candidates"]
    scorecard = {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "run_label": run_label,
        "run_source": run_source,
        "gold_papers": len(scores),
        "matching": {
            "tiers": ["gaia_id", "alias", "coordinates"],
            "propagated_tolerance_arcsec": DEFAULT_PROPAGATED_TOLERANCE_ARCSEC,
            "fallback_tolerance_arcsec": DEFAULT_FALLBACK_TOLERANCE_ARCSEC,
        },
        "l1": {
            "per_paper": [score.public_record() for score in scores],
            "micro": _micro(scores, weighted=False),
            "macro": _macro(scores),
            "weighted_micro": _micro(scores, weighted=True),
            "negative_papers": {
                "count": len(negative),
                "papers_with_false_positives": sum(
                    1 for score in negative if score.fp
                ),
                "false_positive_candidates": sum(score.fp for score in negative),
            },
            "bootstrap": _bootstrap(
                scores, iterations=bootstrap_iterations, seed=bootstrap_seed
            ),
            "sensitivity": {
                "no_coordinate_tier": {
                    "micro": _micro(sensitivity_scores, weighted=False)
                }
            },
        },
        "l2_draft": _l2_summary(details),
        "papers_missing_ai_output": [
            score.arxiv_id for score in scores if score.ai_output_missing
        ],
    }
    private_details = {
        "schema_version": SCORING_DETAILS_SCHEMA_VERSION,
        "run_label": run_label,
        "papers": details,
    }
    return scorecard, private_details
