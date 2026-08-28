"""Formal benchmark scoring: sealed runs vs selected expert gold.

L0 reports delivery and format validity from the sealed run manifest. API
usage and snapshot-bound estimated cost are operational metadata outside all
quality layers.

L1 (formal): candidate-set precision/recall/F1 after deterministic identity
matching (``stella.benchmark.identity`` tiers: Gaia id, alias, coordinates),
per paper and aggregated (micro, macro, sampling-weight weighted micro),
false positives on no-candidate papers, paired bootstrap confidence
intervals over papers, and a no-coordinate-tier matching sensitivity check.

L2 (formal, benchmark/SCORE_SPEC.md v2.0.0): per-quantity transcription
scoring for matched pairs — gold-driven rows plus an ``ai_only``
hallucination audit over the scored vocabulary, the unconditional
total_velocity projection (flagged, dual-reported), the numeric equality
ladder with directional asymmetric gold errors, unit spelling
normalization without dimensional conversion, the 0.5-arcsec coordinate
bridge, probability normalization to 0-1 fractions, and gold-note triage
flags. L1 misses propagate into L2 as ``gold_only`` rows so the end-to-end
delivery rate deliberately couples to L1 recall; the layering clause
forbids fusing L1 and end-to-end L2 into one composite score.

Output discipline: the public scorecard contains only counts, rates, and
paper ids. Anything that quotes gold content (candidate identities, values,
matched-pair tables, note text) belongs to the private details document,
which is written next to the external gold store, never inside this
workspace.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import papers_for_split, sha256_file
from stella.benchmark.paths import validate_path_segment
from stella.benchmark.pricing import (
    COST_FORMULA_VERSION,
    estimate_api_cost,
    load_pricing_snapshot,
)
from stella.benchmark.gold_selection import load_gold_selection_snapshot
from stella.benchmark.run_contract import (
    canonical_sha256,
    require_v6_run_manifest,
)
from stella.schema_registry import require_campaign_writable, require_schema, schema_ref
from stella.benchmark.gold import (
    SCORED_QUANTITY_FIELDS,
    UNICODE_SIGN_TRANSLATION,
    _coordinate_value_degrees,
    validate_annotator_handle,
)
from stella.lit.coordinates import _coordinate_value_degrees
from stella.lit.identity import (
    DEFAULT_FALLBACK_TOLERANCE_ARCSEC,
    DEFAULT_PROPAGATED_TOLERANCE_ARCSEC,
    NAME_NORMALIZATION_VERSION,
    CandidateIdentity,
    identity_from_candidate,
    match_identities,
    normalize_name,
    parse_gaia_id,
)

DELIVERY_STATUSES = (
    "complete",
    "partial",
    "failed",
    "network_failed",
    "interrupted",
    "pending",
    "running",
    "skipped",
)


def delivery_counts(delivery: dict[str, str]) -> dict[str, int]:
    """Return an exhaustive public count for every persisted paper state."""

    return {
        status: sum(1 for value in delivery.values() if value == status)
        for status in DELIVERY_STATUSES
    }

SCORE_SPEC_VERSION = "benchmark/SCORE_SPEC.md v2.0.0"
L0_DEFINITION_VERSION = "1.0.0"
DEFAULT_BOOTSTRAP_ITERATIONS = 2000
DEFAULT_BOOTSTRAP_SEED = 20260706
COORDINATE_BRIDGE_ARCSEC = 0.5
# v2: normalize_unit strips LaTeX spelling residue (braces, $, spacing
# macros) before the synonym lookup, so "mas yr^{-1}" and "mas yr^-1" are
# the same printed unit. Spelling only — never dimensional conversion.
UNIT_SYNONYMS_VERSION = "v2"

# Unit spellings treated as identical for L2 comparison (R4). Keys are the
# canonical form; values list synonyms as they appear in papers/extractions.
# Spelling normalization only — never dimensional conversion.
UNIT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "km/s": ("km/s", "km s^-1", "km s-1", "km s⁻¹", "kms^-1", "km/sec"),
    "mas/yr": ("mas/yr", "mas yr^-1", "mas yr-1", "mas yr⁻¹", "mas/year"),
    "mas": ("mas",),
    # Frozen by benchmark/SCORE_SPEC.md R4. Coordinate parsing accepts a
    # wider input vocabulary, but the scorer must not silently broaden the
    # campaign's unit-equivalence contract.
    "deg": ("deg", "degree", "degrees", "°"),
    "kpc": ("kpc",),
    "pc": ("pc",),
    "mag": ("mag",),
    "dex": ("dex",),
}

_UNIT_CANONICAL = {
    synonym: canonical
    for canonical, synonyms in UNIT_SYNONYMS.items()
    for synonym in synonyms
}

_GROUP_KEYS = ("observed_phase_space", "derived_kinematics", "bound_assessment")
COORDINATE_FIELDS = ("observed_phase_space.ra", "observed_phase_space.dec")
PROJECTION_FIELD = "derived_kinematics.galactic_rest_frame_velocity"
PROJECTION_SOURCE_FIELD = "derived_kinematics.total_velocity"

# Strict tier (R3a): exact transcription matches only. Lenient adds
# within_gold_error.
STRICT_STATUSES = ("value_match", "value_match_cross_format")
L2_STATUSES = (
    "value_match",
    "value_match_cross_format",
    "within_gold_error",
    "value_mismatch",
    "unit_mismatch",
    "limit_kind_mismatch",
    "gold_only",
    "ai_only",
)
_L2_FLAGS = (
    "projected_from_total_velocity",
    "unit_missing_one_side",
    "gold_note_present",
)


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
    gaia = parse_gaia_id(candidate.get("gaia_source_id"))
    if gaia:
        # Bridge to manuscripts that quote the bare Gaia source number.
        names.add(gaia[1])
    display = str(
        candidate.get("paper_candidate_id")
        or candidate.get("gaia_source_id")
        or ((candidate.get("aliases") or [""])[0])
    )
    return CandidateIdentity(
        record_id=display,
        gaia=gaia,
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


def _ci(values: list[float]) -> list[float] | None:
    if not values:
        return None
    ordered = sorted(values)
    lo = ordered[max(0, int(0.025 * len(ordered)) - 1) if len(ordered) > 40 else 0]
    hi = ordered[min(len(ordered) - 1, int(0.975 * len(ordered)))]
    return [round(lo, 4), round(hi, 4)]


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

    return {
        "iterations": iterations,
        "seed": seed,
        "resample_unit": "paper",
        "micro_precision_ci95": _ci(metrics["precision"]),
        "micro_recall_ci95": _ci(metrics["recall"]),
        "micro_f1_ci95": _ci(metrics["f1"]),
    }


# --------------------------------------------------------------------------
# L2 value comparison (benchmark/SCORE_SPEC.md v1.1.0)


_UNIT_LATEX_MACRO_RE = re.compile(r"\\(?:mathrm|mathit|rm|text|textrm)\b")
_UNIT_LATEX_SPACE_RE = re.compile(r"(?:\\[,;! ]|~)")


def normalize_unit(unit: str) -> str:
    """R4 spelling normalization. Strips LaTeX markup residue (a spelling
    artifact of TeX-sourced extractions) before the synonym lookup; never
    converts dimensions."""

    text = unit.strip().lower()
    text = _UNIT_LATEX_MACRO_RE.sub("", text)
    text = _UNIT_LATEX_SPACE_RE.sub(" ", text)
    text = text.translate(str.maketrans("", "", "${}\\"))
    text = re.sub(r"\s+", " ", text).strip()
    return _UNIT_CANONICAL.get(text, text)


def _to_float(text: Any) -> float | None:
    """R3 numeric parse: sign folding, approximation markers, thousands
    commas. Gold forbids the markers; the AI side may transcribe them."""

    value = str(text or "").translate(UNICODE_SIGN_TRANSLATION).strip()
    for marker in ("~", "≈", "∼"):
        value = value.replace(marker, "")
    value = value.replace(",", "").strip()
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
    if not isinstance(quantity, dict):
        return None
    # v3 core documents use the explicit native spelling ``none`` while
    # historical scorer inputs used an empty string for an exact value.
    if quantity.get("limit_kind") == "none":
        return {**quantity, "limit_kind": ""}
    return quantity


def _has_value(quantity: dict[str, Any] | None) -> bool:
    if quantity is None:
        return False
    return bool(
        str(quantity.get("value") or "").strip()
        or str(quantity.get("range_lower") or "").strip()
        or str(quantity.get("range_upper") or "").strip()
    )


def _probability_field(field: str) -> bool:
    return "probability" in field


def _normalize_probability(field: str, value: float | None, quantity: dict[str, Any]) -> float | None:
    """R7: the specification's only numeric normalization — % (or a value
    above 1, impossible for a probability) becomes a 0-1 fraction."""

    if value is None or not _probability_field(field):
        return value
    unit = str(quantity.get("unit") or "")
    raw = str(quantity.get("raw_value") or "")
    if "%" in unit or "%" in raw or abs(value) > 1.0:
        return value / 100.0
    return value


def _values_exactly_equal(gold_value: float, ai_value: float) -> bool:
    return abs(gold_value - ai_value) <= 1e-9 * max(1.0, abs(gold_value))


def _within_gold_error(gold: dict[str, Any], gold_value: float, ai_value: float) -> bool:
    """R3 rung 3: symmetric error, else the directional asymmetric bound."""

    difference = ai_value - gold_value
    error = _to_float(gold.get("error"))
    if error:
        return abs(difference) <= error
    bound = _to_float(gold.get("upper_error") if difference > 0 else gold.get("lower_error"))
    return bool(bound) and abs(difference) <= bound


def _value_ladder(field: str, gold: dict[str, Any], ai: dict[str, Any]) -> str:
    gold_value = _normalize_probability(field, _to_float(gold.get("value")), gold)
    ai_value = _normalize_probability(field, _to_float(ai.get("value")), ai)
    if gold_value is None:
        # Non-numeric verbatim gold text (rare outside coordinates).
        gold_text = str(gold.get("value") or "").translate(UNICODE_SIGN_TRANSLATION).strip()
        ai_text = str(ai.get("value") or "").translate(UNICODE_SIGN_TRANSLATION).strip()
        return "value_match" if gold_text and gold_text == ai_text else "value_mismatch"
    if ai_value is None:
        return "value_mismatch"
    if _values_exactly_equal(gold_value, ai_value):
        return "value_match"
    if _within_gold_error(gold, gold_value, ai_value):
        return "within_gold_error"
    return "value_mismatch"


_LADDER_RANK = {"value_match": 0, "within_gold_error": 1, "value_mismatch": 2}


def _range_ladder(field: str, gold: dict[str, Any], ai: dict[str, Any]) -> str:
    worst = "value_match"
    for key in ("range_lower", "range_upper"):
        rung = _value_ladder(
            field,
            {**gold, "value": gold.get(key)},
            {**ai, "value": ai.get(key), "raw_value": ai.get("raw_value")},
        )
        if _LADDER_RANK[rung] > _LADDER_RANK[worst]:
            worst = rung
    return worst


def _ai_coordinate_degrees(field: str, quantity: dict[str, Any]) -> float | None:
    text = str(quantity.get("value") or "").strip()
    if not text:
        return None
    coordinate_format = str(quantity.get("coordinate_format") or "")
    if coordinate_format == "decimal_degrees":
        hint = "deg"
    elif coordinate_format == "sexagesimal_hms":
        hint = "hms"
    elif coordinate_format == "sexagesimal_dms":
        hint = "dms"
    else:
        # sexagesimal_colon or legacy records: fall back to the unit and the
        # field-level convention (colon RA without a degree unit is hours).
        hint = str(quantity.get("unit") or "")
    return _coordinate_value_degrees(field, text, hint)


def _coordinate_is_decimal(quantity: dict[str, Any]) -> bool:
    declared = str(quantity.get("coordinate_format") or "")
    if declared:
        return declared == "decimal_degrees"
    return _to_float(quantity.get("value")) is not None


def _compare_coordinate(field: str, gold: dict[str, Any], ai: dict[str, Any]) -> str:
    """R5: degree comparison with the 0.5-arcsec printed-precision bridge.

    The bridge applies whenever exact equality fails — cross-format pairs
    (sexagesimal vs decimal) are the designed case, but same-format pairs
    printed at different precisions in different views of the paper get the
    same treatment. RA differences skip the cos(dec) correction, which only
    makes the bridge stricter.
    """

    gold_degrees = _coordinate_value_degrees(
        field, str(gold.get("value") or "").strip(), str(gold.get("unit") or "")
    )
    ai_degrees = _ai_coordinate_degrees(field, ai)
    if gold_degrees is None or ai_degrees is None:
        gold_text = str(gold.get("value") or "").translate(UNICODE_SIGN_TRANSLATION).strip()
        ai_text = str(ai.get("value") or "").translate(UNICODE_SIGN_TRANSLATION).strip()
        return "value_match" if gold_text and gold_text == ai_text else "value_mismatch"
    same_format = _coordinate_is_decimal(gold) == _coordinate_is_decimal(ai)
    if _values_exactly_equal(gold_degrees, ai_degrees):
        return "value_match" if same_format else "value_match_cross_format"
    if abs(gold_degrees - ai_degrees) * 3600.0 <= COORDINATE_BRIDGE_ARCSEC:
        return "value_match_cross_format"
    return "value_mismatch"


def _display_quantity(quantity: dict[str, Any] | None) -> str:
    if quantity is None:
        return ""
    if str(quantity.get("limit_kind") or "") == "range":
        value = (
            f"{str(quantity.get('range_lower') or '').strip()} to "
            f"{str(quantity.get('range_upper') or '').strip()}"
        ).strip()
    else:
        value = str(quantity.get("value") or "").strip()
    parts = [value] if value else []
    error = str(quantity.get("error") or "").strip()
    lower = str(quantity.get("lower_error") or "").strip()
    upper = str(quantity.get("upper_error") or "").strip()
    if error:
        parts.append(f"± {error}")
    elif lower or upper:
        parts.append(f"-{lower or '?'} +{upper or '?'}")
    unit = str(quantity.get("unit") or "").strip()
    if unit:
        parts.append(unit)
    kind = str(quantity.get("limit_kind") or "").strip()
    if kind and kind != "range":
        parts.append(f"[{kind}]")
    return " ".join(parts) if parts else "(empty)"


def compare_quantity(
    field: str, gold: dict[str, Any], ai: dict[str, Any] | None
) -> dict[str, Any]:
    """Classify one gold quantity against the AI candidate's same field."""

    row: dict[str, Any] = {"field": field}
    if str(gold.get("notes") or "").strip():
        row["gold_note_present"] = True

    if not _has_value(ai):
        row["status"] = "gold_only"
        return row
    assert ai is not None

    gold_kind = str(gold.get("limit_kind") or "").strip()
    ai_kind = str(ai.get("limit_kind") or "").strip()
    if gold_kind != ai_kind:
        # R6: numerically equal but semantically different (exact vs limit
        # vs range) is an error outright.
        row["status"] = "limit_kind_mismatch"
        return row

    if field in COORDINATE_FIELDS and gold_kind == "":
        row["status"] = _compare_coordinate(field, gold, ai)
        return row

    if not _probability_field(field):
        gold_unit = normalize_unit(str(gold.get("unit") or ""))
        ai_unit = normalize_unit(str(ai.get("unit") or ""))
        if gold_unit and ai_unit and gold_unit != ai_unit:
            row["status"] = "unit_mismatch"
            return row
        if bool(gold_unit) != bool(ai_unit):
            row["unit_missing_one_side"] = True

    if gold_kind == "range":
        row["status"] = _range_ladder(field, gold, ai)
        return row

    row["status"] = _value_ladder(field, gold, ai)
    return row


def compare_pair_quantities(
    gold_candidate: dict[str, Any], ai_candidate: dict[str, Any]
) -> list[dict[str, Any]]:
    """All L2 rows for one matched pair: gold-driven rows (R1) with the
    total_velocity projection (R2), then the ai_only hallucination audit
    over the remaining scored vocabulary (R1 amendment)."""

    rows: list[dict[str, Any]] = []
    gold_fields: set[str] = set()
    for quantity in gold_candidate.get("quantities") or []:
        if not isinstance(quantity, dict):
            continue
        field = str(quantity.get("field") or "")
        gold_fields.add(field)
        ai_quantity = _ai_quantity_at(ai_candidate, field)
        projected = False
        if field == PROJECTION_FIELD and not _has_value(ai_quantity):
            fallback = _ai_quantity_at(ai_candidate, PROJECTION_SOURCE_FIELD)
            if _has_value(fallback):
                ai_quantity = fallback
                projected = True
        row = compare_quantity(field, quantity, ai_quantity)
        if projected:
            row["projected_from_total_velocity"] = True
        row["gold"] = _display_quantity(quantity)
        row["ai"] = _display_quantity(ai_quantity) if _has_value(ai_quantity) else ""
        note = str(quantity.get("notes") or "").strip()
        if note:
            row["gold_note"] = note
        rows.append(row)

    # ai_only audit: gold is exhaustive over the scored vocabulary, so an AI
    # value with no gold row is a presumed hallucination. total_velocity is
    # not in the vocabulary, so a bare AI total_velocity (R2 note) is never
    # ai_only.
    for field in SCORED_QUANTITY_FIELDS:
        if field in gold_fields:
            continue
        ai_quantity = _ai_quantity_at(ai_candidate, field)
        if not _has_value(ai_quantity):
            continue
        rows.append(
            {
                "field": field,
                "status": "ai_only",
                "gold": "",
                "ai": _display_quantity(ai_quantity),
            }
        )
    return rows


def _gold_only_rows(gold_candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """R9: quantities of L1-missed gold candidates propagate as gold_only."""

    rows: list[dict[str, Any]] = []
    for quantity in gold_candidate.get("quantities") or []:
        if not isinstance(quantity, dict):
            continue
        row: dict[str, Any] = {
            "field": str(quantity.get("field") or ""),
            "status": "gold_only",
            "gold": _display_quantity(quantity),
            "ai": "",
        }
        if str(quantity.get("notes") or "").strip():
            row["gold_note_present"] = True
            row["gold_note"] = str(quantity.get("notes") or "").strip()
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
        "gold_status": score.gold_status,
        "ai_status": ai_status,
        "pairs": [
            {
                "gold_id": _display_gold(gold_candidates[pair["gold_index"]]),
                "ai_id": _display_ai(ai_candidates[pair["ai_index"]], pair["ai_index"]),
                "method": pair["method"],
                "detail": pair["detail"],
                "gold_origin_type": str(
                    gold_candidates[pair["gold_index"]].get("origin_type") or ""
                ),
                "ai_origin_type": str(
                    (
                        (ai_candidates[pair["ai_index"]].get("candidate_origin") or {})
                        if isinstance(ai_candidates[pair["ai_index"]].get("candidate_origin"), dict)
                        else {}
                    ).get("origin_type")
                    or ""
                ),
                "l2": compare_pair_quantities(
                    gold_candidates[pair["gold_index"]],
                    ai_candidates[pair["ai_index"]],
                ),
            }
            for pair in matching["pairs"]
        ],
        "unmatched_gold": [
            {
                "gold_id": _display_gold(gold_candidates[index]),
                "l2": _gold_only_rows(gold_candidates[index]),
            }
            for index in matching["unmatched_gold"]
        ],
        "unmatched_ai": [
            _display_ai(ai_candidates[index], index)
            for index in matching["unmatched_ai"]
        ],
        "gold_warnings": gold_document.get("_warnings") or [],
    }
    return score, detail


# --------------------------------------------------------------------------
# L2 aggregation (R9)


def _paper_l2_rows(detail: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in detail["pairs"]:
        for row in pair["l2"]:
            rows.append({**row, "source": "pair"})
    for missed in detail["unmatched_gold"]:
        for row in missed["l2"]:
            rows.append({**row, "source": "unmatched_gold"})
    return rows


def _without_projection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """R2 dual reporting: in the no-projection view a projected row reverts
    to gold_only (the AI's own field was empty)."""

    adjusted = []
    for row in rows:
        if row.get("projected_from_total_velocity"):
            adjusted.append({**row, "status": "gold_only"})
        else:
            adjusted.append(row)
    return adjusted


def _l2_rates(rows: list[dict[str, Any]], *, weights: dict[str, float] | None = None) -> dict[str, Any]:
    def row_weight(row: dict[str, Any]) -> float:
        if weights is None:
            return 1.0
        return weights.get(str(row.get("arxiv_id") or ""), 1.0)

    gold_total = 0.0
    compared = 0.0
    strict = 0.0
    lenient = 0.0
    ai_only = 0.0
    for row in rows:
        w = row_weight(row)
        status = row["status"]
        if status == "ai_only":
            ai_only += w
            continue
        gold_total += w
        if status == "gold_only":
            continue
        compared += w
        if status in STRICT_STATUSES:
            strict += w
            lenient += w
        elif status == "within_gold_error":
            lenient += w
    return {
        "gold_quantities": gold_total,
        "compared": compared,
        "strict_matches": strict,
        "lenient_matches": lenient,
        "ai_only": ai_only,
        "coverage": _rate(compared, gold_total),
        "agreement_over_compared_strict": _rate(strict, compared),
        "agreement_over_compared_lenient": _rate(lenient, compared),
        "delivery_end_to_end_strict": _rate(strict, gold_total),
        "delivery_end_to_end_lenient": _rate(lenient, gold_total),
        "fill_precision_strict": _rate(strict, compared + ai_only),
        "fill_precision_lenient": _rate(lenient, compared + ai_only),
    }


_MACRO_RATE_KEYS = (
    "coverage",
    "agreement_over_compared_strict",
    "agreement_over_compared_lenient",
    "delivery_end_to_end_strict",
    "delivery_end_to_end_lenient",
    "fill_precision_strict",
    "fill_precision_lenient",
)


def _l2_macro(per_paper_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    macro: dict[str, Any] = {}
    for key in _MACRO_RATE_KEYS:
        values = [
            rates[key]
            for rows in per_paper_rows.values()
            if (rates := _l2_rates(rows))[key] is not None
        ]
        macro[key] = sum(values) / len(values) if values else None
        macro[f"papers_with_defined_{key}"] = len(values)
    return macro


def _l2_bootstrap(
    per_paper_rows: dict[str, list[dict[str, Any]]],
    *,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    papers = sorted(per_paper_rows)
    rng = random.Random(seed)
    tracked = (
        "delivery_end_to_end_strict",
        "agreement_over_compared_strict",
        "fill_precision_strict",
    )
    samples: dict[str, list[float]] = {key: [] for key in tracked}
    for _ in range(iterations):
        pooled: list[dict[str, Any]] = []
        for _ in papers:
            pooled.extend(per_paper_rows[papers[rng.randrange(len(papers))]])
        rates = _l2_rates(pooled)
        for key in tracked:
            if rates[key] is not None:
                samples[key].append(rates[key])
    return {
        "iterations": iterations,
        "seed": seed,
        "resample_unit": "paper",
        **{f"{key}_ci95": _ci(samples[key]) for key in tracked},
    }


def _l2_per_field(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    per_field: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = per_field.setdefault(
            row["field"],
            {status: 0 for status in L2_STATUSES}
            | {"gold_quantities": 0}
            | {flag: 0 for flag in _L2_FLAGS},
        )
        bucket[row["status"]] = bucket.get(row["status"], 0) + 1
        if row["status"] != "ai_only":
            bucket["gold_quantities"] += 1
        for flag in _L2_FLAGS:
            if row.get(flag):
                bucket[flag] += 1
    return dict(sorted(per_field.items()))


def _l2_block(
    details: list[dict[str, Any]],
    weights: dict[str, float],
    *,
    bootstrap_iterations: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    per_paper_rows: dict[str, list[dict[str, Any]]] = {}
    all_rows: list[dict[str, Any]] = []
    for detail in details:
        if detail["gold_status"] != "candidates_found":
            continue
        rows = [
            {**row, "arxiv_id": detail["arxiv_id"]}
            for row in _paper_l2_rows(detail)
        ]
        per_paper_rows[detail["arxiv_id"]] = rows
        all_rows.extend(rows)

    matched_only_rows = [row for row in all_rows if row.get("source") == "pair"]
    without_projection_rows = _without_projection(all_rows)
    mismatch_with_note = sum(
        1
        for row in all_rows
        if row["status"] in ("value_mismatch", "unit_mismatch", "limit_kind_mismatch")
        and row.get("gold_note_present")
    )

    return {
        "spec": SCORE_SPEC_VERSION,
        "config": {
            "unit_synonyms_version": UNIT_SYNONYMS_VERSION,
            "coordinate_bridge_arcsec": COORDINATE_BRIDGE_ARCSEC,
            "projection": "unconditional_flagged",
            "probability_normalization": "fraction_0_1",
            "strict_statuses": list(STRICT_STATUSES),
        },
        "row_counts": {
            status: sum(1 for row in all_rows if row["status"] == status)
            for status in L2_STATUSES
        },
        "flags": {
            **{
                flag: sum(1 for row in all_rows if row.get(flag))
                for flag in _L2_FLAGS
            },
            "mismatch_with_gold_note": mismatch_with_note,
        },
        "micro": _l2_rates(all_rows),
        "micro_without_projection": _l2_rates(without_projection_rows),
        "micro_matched_pairs_only": _l2_rates(matched_only_rows),
        "weighted_micro": _l2_rates(all_rows, weights=weights),
        "macro": _l2_macro(per_paper_rows),
        "bootstrap": _l2_bootstrap(
            per_paper_rows,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        )
        if per_paper_rows
        else None,
        "per_field": _l2_per_field(all_rows),
        "layering_note": (
            "report L1 micro F1, agreement_over_compared_strict, and "
            "delivery_end_to_end_strict side by side; never combine L1 with "
            "delivery_end_to_end into a composite score (the latter already "
            "embeds L1 recall)"
        ),
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

    run_label = validate_path_segment(run_label, "run label")

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
        "schema": schema_ref("benchmark.scorecard"),
        "run_label": run_label,
        "run_source": run_source,
        "gold_papers": len(scores),
        "matching": {
            "tiers": ["gaia_id", "alias", "coordinates"],
            "name_normalization_version": NAME_NORMALIZATION_VERSION,
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
        "l2": _l2_block(
            details,
            weights,
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed,
        ),
        "papers_missing_ai_output": [
            score.arxiv_id for score in scores if score.ai_output_missing
        ],
    }
    private_details = {
        "schema": schema_ref("benchmark.scoring_details"),
        "run_label": run_label,
        "papers": details,
    }
    return scorecard, private_details


# --------------------------------------------------------------------------
# Formal V6 campaign scoring


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def load_formal_gold_snapshot(
    *,
    gold_dir: Path,
    gold_manifest_path: Path,
    gold_selection_path: Path,
    paper_ids: list[str],
    campaign_id: str,
    campaign_sha256: str,
    split: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Load one explicit expert selection for an exact campaign split."""

    return load_gold_selection_snapshot(
        selection_path=gold_selection_path,
        gold_manifest_path=gold_manifest_path,
        gold_dir=gold_dir,
        paper_ids=paper_ids,
        campaign_id=campaign_id,
        campaign_sha256=campaign_sha256,
        split=split,
    )


def _formal_run_bindings(
    *,
    campaign_path: Path,
    split: str,
    run_dir: Path,
    workspace: Path,
    current_component_hashes: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[str], str, dict[str, str]]:
    if split not in {"dev", "test"}:
        raise ValueError("formal scoring split must be dev or test")
    campaign = _load_json_object(campaign_path, label="campaign manifest")
    try:
        require_schema(campaign, "benchmark.campaign", require_current=True)
    except ValueError:
        raise ValueError("formal scoring requires the current campaign manifest schema")
    campaign_hash = sha256_file(campaign_path)
    require_campaign_writable(str(campaign.get("campaign_id") or ""))
    expected = papers_for_split(campaign, split)
    config_path = run_dir / "run_config.json"
    manifest_path = run_dir / "run_manifest.json"
    summary_path = run_dir / "run_summary.json"
    config = _load_json_object(config_path, label="run config")
    manifest = _load_json_object(manifest_path, label="run manifest")
    summary = _load_json_object(summary_path, label="run summary")
    try:
        require_schema(config, "benchmark.run_config", require_current=True)
    except ValueError:
        raise ValueError("formal scoring refuses legacy run config")
    try:
        require_schema(manifest, "benchmark.run_manifest", require_current=True)
    except ValueError:
        raise ValueError("formal scoring requires the current sealed run manifest schema")
    try:
        require_schema(summary, "benchmark.run_summary", require_current=True)
    except ValueError:
        raise ValueError("formal scoring requires the current sealed run summary schema")
    l1_delivery, _ = require_v6_run_manifest(manifest)
    expected_scope = "full_dev" if split == "dev" else "full_test"
    if config.get("scope") != expected_scope:
        raise ValueError(
            f"V6 formal scoring requires scope={expected_scope} for split={split}"
        )
    if split == "test" and campaign.get("test_ready") is not True:
        raise ValueError("V6 formal test scoring requires a test-ready campaign")
    if config.get("papers") != expected:
        raise ValueError("V6 run config papers do not match campaign split")
    if manifest.get("papers") != expected:
        raise ValueError("V6 run manifest papers do not match campaign split")
    campaign_binding = config.get("campaign") or {}
    if (
        campaign_binding.get("campaign_id") != campaign.get("campaign_id")
        or campaign_binding.get("manifest_sha256") != campaign_hash
        or manifest.get("campaign") != campaign_binding
    ):
        raise ValueError("V6 run campaign binding does not match campaign manifest")
    if manifest.get("run_config_sha256") != sha256_file(config_path):
        raise ValueError("V6 sealed run config hash does not match current run config")
    if manifest.get("run_summary_sha256") != sha256_file(summary_path):
        raise ValueError("V6 sealed run summary hash does not match current run summary")
    if (
        manifest.get("l0", {}).get("format_validation")
        != summary.get("format_validation")
        or manifest.get("usage") != summary.get("usage")
    ):
        raise ValueError("V6 sealed L0 or usage does not match run summary")
    if manifest.get("method_fingerprint") != config.get("method_fingerprint"):
        raise ValueError("V6 sealed method fingerprint does not match run config")
    component_hashes = dict(config.get("component_hashes") or {})
    if not component_hashes or manifest.get("component_hashes") != component_hashes:
        raise ValueError("V6 sealed component hashes do not match run config")
    if (
        current_component_hashes is not None
        and dict(current_component_hashes) != component_hashes
    ):
        raise ValueError("V6 scoring component hashes do not match the run")
    core_delivery = {
        "papers": {
            "valid": list(l1_delivery["complete"]),
            "invalid": list(l1_delivery["failed"]),
            "missing": list(l1_delivery["missing"]),
        },
        "artifacts": manifest.get("artifacts") or {},
    }
    return (
        campaign,
        config,
        manifest,
        core_delivery,
        expected,
        campaign_hash,
        component_hashes,
    )


def _require_sealed_artifacts(*, run_dir: Path, manifest: dict[str, Any]) -> None:
    """Fail closed when any artifact recorded by the sealed manifest changed."""

    for arxiv_id, records in (manifest.get("artifacts") or {}).items():
        if not isinstance(records, dict):
            raise ValueError(f"sealed artifact records are invalid: {arxiv_id}")
        for name, record in records.items():
            if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
                raise ValueError(f"sealed artifact record is invalid: {arxiv_id}/{name}")
            candidates = (run_dir / arxiv_id / name, run_dir / "papers" / arxiv_id / name)
            path = next((candidate for candidate in candidates if candidate.is_file()), None)
            if path is None or sha256_file(path) != record["sha256"]:
                raise ValueError(f"sealed artifact changed or is missing: {arxiv_id}/{name}")


def _l0_scorecard_block(
    *,
    manifest: dict[str, Any],
    expected: list[str],
    integrity_checks: list[str] | None = None,
) -> dict[str, Any]:
    roster = manifest["l1_roster_delivery"]
    core = manifest["l2_core_field_delivery"]
    expected_count = len(expected)
    roster_complete = len(roster["complete"])
    core_complete = len(core["complete"])
    core_partial = len(core["partial"])
    denominator = expected_count or 1
    return {
        "definition_version": L0_DEFINITION_VERSION,
        "roster_delivery": {
            "expected": expected_count,
            "complete": roster_complete,
            "failed": len(roster["failed"]),
            "missing": len(roster["missing"]),
            "delivery_rate": round(roster_complete / denominator, 6),
        },
        "core_field_delivery": {
            "expected": expected_count,
            "complete": core_complete,
            "partial": core_partial,
            "failed": len(core["failed"]),
            "missing": len(core["missing"]),
            "full_delivery_rate": round(core_complete / denominator, 6),
            "usable_delivery_rate": round(
                (core_complete + core_partial) / denominator, 6
            ),
            "candidate_counts": dict(core["candidate_counts"]),
        },
        "format_validation": dict(manifest["l0"]["format_validation"]),
        "integrity_gate": {
            "passed": True,
            "checks": integrity_checks
            or [
                "sealed_manifest",
                "schema",
                "config_hash",
                "artifact_hashes",
            ],
        },
    }


def _valid_ai_documents(
    *, run_dir: Path, core_delivery: dict[str, Any], expected: list[str]
) -> dict[str, dict[str, Any] | None]:
    """Load documents for L1-valid papers.

    The scorer consumes the core document of each delivery: L1 identity and
    the 19 L2 scored quantities all live in ``identifiers``/``core``, so a
    paper with field-stage failures still contributes its roster to L1 while
    its unavailable fields remain missing for L2.
    """

    valid = set((core_delivery.get("papers") or {}).get("valid") or [])
    artifacts = core_delivery.get("artifacts") or {}
    documents: dict[str, dict[str, Any] | None] = {}
    for arxiv_id in expected:
        if arxiv_id not in valid:
            documents[arxiv_id] = None
            continue
        path = run_dir / arxiv_id / "literature_hvs_candidates.json"
        if not path.is_file():
            path = (
                run_dir
                / "papers"
                / arxiv_id
                / "literature_hvs_candidates.json"
            )
        recorded = ((artifacts.get(arxiv_id) or {}).get("literature_hvs_candidates.json") or {})
        if not path.is_file() or recorded.get("sha256") != sha256_file(path):
            raise ValueError(f"sealed valid output changed or missing: {arxiv_id}")
        document = load_ai_document(path)
        if document is None:
            raise ValueError(f"sealed valid output is no longer parseable: {arxiv_id}")
        documents[arxiv_id] = document
    return documents


def _invalid_diagnostics(
    *, gold_annotations: dict[str, dict[str, Any]], run_dir: Path, core_delivery: dict[str, Any]
) -> list[dict[str, Any]]:
    """Private-only exploration; never contributes to formal L1/L2 metrics."""

    diagnostics: list[dict[str, Any]] = []
    for arxiv_id in (core_delivery.get("papers") or {}).get("invalid") or []:
        path = run_dir / arxiv_id / "literature_hvs_candidates.json"
        if not path.is_file():
            path = (
                run_dir
                / "papers"
                / arxiv_id
                / "literature_hvs_candidates.json"
            )
        document = load_ai_document(path)
        if document is None:
            continue
        _, detail = score_paper(
            arxiv_id, gold_annotations[arxiv_id], document, weight=1.0
        )
        diagnostics.append(
            {
                "arxiv_id": arxiv_id,
                "label": "diagnostic-only invalid delivery; excluded from formal metrics",
                "detail": detail,
            }
        )
    return diagnostics


def _debug_delivery_ledger(
    run_dir: Path, expected: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build L1/L2 delivery maps and core artifact hashes for a debug run."""

    l1 = {"complete": [], "failed": [], "missing": []}
    l2 = {
        "complete": [],
        "partial": [],
        "failed": [],
        "missing": [],
        "candidate_counts": {
            "total": 0,
            "fields_complete": 0,
            "field_extraction_failed": 0,
        },
    }
    artifacts: dict[str, dict[str, Any]] = {}
    for arxiv_id in expected:
        paper_result_path = (
            run_dir / "papers" / arxiv_id / "paper_result.json"
        )
        if not paper_result_path.is_file():
            l1["missing"].append(arxiv_id)
            l2["missing"].append(arxiv_id)
            continue
        paper_result = _load_json_object(
            paper_result_path, label="debug paper result"
        )
        if paper_result.get("roster_status") in {"candidates_found", "no_candidates"}:
            l1["complete"].append(arxiv_id)
        else:
            l1["failed"].append(arxiv_id)
        status = paper_result.get("status")
        if status in {"complete", "partial", "failed"}:
            l2[status].append(arxiv_id)
        else:
            l2["missing"].append(arxiv_id)
        counts = l2["candidate_counts"]
        for candidate in paper_result.get("candidates") or []:
            counts["total"] += 1
            if candidate.get("status") == "fields_complete":
                counts["fields_complete"] += 1
            else:
                counts["field_extraction_failed"] += 1
        core_path = (
            run_dir / "papers" / arxiv_id / "literature_hvs_candidates.json"
        )
        if core_path.is_file():
            artifacts[arxiv_id] = {
                "literature_hvs_candidates.json": {
                    "sha256": sha256_file(core_path),
                    "bytes": core_path.stat().st_size,
                }
            }
    return l1, {"l1": l1, "l2": l2, "artifacts": artifacts}



def score_formal_campaign_run(
    *,
    campaign_path: Path,
    split: str,
    run_dir: Path,
    gold_dir: Path,
    gold_manifest_path: Path,
    gold_selection_path: Path,
    pricing_snapshot_path: Path,
    releases_root: Path | None = None,
    run_label: str | None = None,
    supersedes: str | None = None,
    bootstrap_iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    workspace: Path | None = None,
    current_component_hashes: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Score a sealed, clean campaign run under the current formal contract."""

    campaign_path = campaign_path.resolve()
    run_dir = run_dir.resolve()


def write_scorecard_once(scoring_root: Path, scorecard: dict[str, Any]) -> Path:
    """Create one immutable public scorecard under its evaluation label."""

    require_schema(scorecard, "benchmark.scorecard", require_current=True)
    label = validate_path_segment(str(scorecard.get("run_label") or ""), "run label")
    provenance = scorecard.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("evaluation_label") != label:
        raise ValueError("scorecard evaluation label must match run_label")
    output_dir = scoring_root / label
    path = output_dir / "scorecard.json"
    if path.exists():
        raise ValueError(
            f"scorecard already exists for {label}; use a new evaluation label"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as exc:
        raise ValueError(
            f"scorecard already exists for {label}; use a new evaluation label"
        ) from exc
    return path


def score(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.score adapter: delivery/L0/L1/L2 only, never a composite.

    Delivery comes from the run's paper statuses, L0 from schema validity,
    and L1/L2 from the maintained contribution scorer over the private
    gold annotations and the run's delivered documents. Per-paper details
    (including gold_only and ai_only items) stay in the private store;
    only value-free aggregates reach the public scorecard.
    """

    import os

    from stella.benchmark.hvs_contribution_scoring import (
        build_private_details,
        score_contribution_suite,
    )
    from stella.workflows import operation_complete, operation_failed

    authorities = (payload or {}).get("authorities") or {}
    missing = [
        kind
        for kind in ("gold_private", "scoring")
        if not authorities.get(kind)
    ]
    if missing:
        return operation_failed(
            "formal scoring needs the private gold store and scoring authority",
            kind="authority",
            blockers=missing,
        )
    gold_dir = os.environ.get("STELLA_GOLD_DIR", "")
    if not gold_dir:
        return operation_failed(
            "scoring reads the external private gold repository (STELLA_GOLD_DIR)",
            kind="precondition",
        )
    run_id = (payload or {}).get("run_id") or ""
    run_dir = Path(root) / "runs" / "benchmark" / run_id
    if not run_id or not run_dir.is_dir():
        return operation_failed(
            "scoring requires an existing benchmark run",
            kind="precondition",
            next_action="score a real run id",
        )
    finalized_path = run_dir / "finalized.json"
    if not finalized_path.is_file():
        return operation_failed(
            "scoring requires a finalized benchmark run",
            kind="precondition",
            next_action="finalize the selected run before scoring",
        )
    try:
        final_status = json.loads(
            finalized_path.read_text(encoding="utf-8")
        ).get("final_status")
    except (OSError, ValueError) as error:
        return operation_failed(
            f"invalid finalization marker: {error}", kind="validation"
        )
    if final_status not in ("complete", "partial"):
        return operation_failed(
            f"invalid finalized run status: {final_status!r}", kind="validation"
        )
    try:
        frozen_run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        frozen_request = frozen_run.get("request") or {}
        expected_papers = list(frozen_request.get("papers") or [])
        campaign_path = run_dir / "campaign.json"
        if not expected_papers and campaign_path.is_file():
            campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
            expected_papers = [
                str(item.get("arxiv_id"))
                for item in campaign.get("papers") or []
                if item.get("arxiv_id")
            ]
    except (OSError, ValueError) as error:
        return operation_failed(
            f"invalid frozen benchmark run: {error}", kind="validation"
        )
    from stella.benchmark.gold_selection import contribution_selection_path

    profile = str(frozen_request.get("profile") or "dev10")
    selection_request = dict(frozen_request)
    if (payload or {}).get("gold_selection_id"):
        selection_request["gold_selection_id"] = payload["gold_selection_id"]
    try:
        selection_path = contribution_selection_path(
            root,
            selection_request,
            profile=profile,
        )
    except ValueError as error:
        return operation_failed(str(error), kind="validation")
    if not selection_path.is_file():
        return operation_failed(
            "a frozen public gold selection profile is required before scoring",
            kind="precondition",
            next_action="prepare the gold selection before the score phase",
        )
    try:
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
    except ValueError as error:
        return operation_failed(
            f"invalid gold selection: {error}", kind="validation"
        )
    try:
        require_schema(
            selection,
            "benchmark.hvs_contribution_gold_selection",
            require_current=True,
        )
    except ValueError as error:
        return operation_failed(
            f"invalid gold selection schema: {error}", kind="validation"
        )
    if selection.get("selection_id") != selection_path.stem:
        return operation_failed(
            "gold selection id does not match its immutable filename",
            kind="validation",
        )
    if selection.get("target_schema") != schema_ref(
        "benchmark.hvs_contribution_annotation"
    ):
        return operation_failed(
            "gold selection does not target contribution Gold v1",
            kind="validation",
        )
    selected_entries = selection.get("papers") if isinstance(selection, dict) else None
    if not isinstance(selected_entries, list) or not selected_entries:
        return operation_failed(
            "gold selection must contain at least one paper",
            kind="validation",
        )
    try:
        selected_papers = [
            validate_path_segment(
                str(entry.get("arxiv_id") or ""), "paper id"
            )
            if isinstance(entry, dict)
            else ""
            for entry in selected_entries
        ]
    except ValueError as error:
        return operation_failed(
            f"invalid gold selection paper id: {error}", kind="validation"
        )
    if expected_papers and selected_papers != expected_papers:
        return operation_failed(
            "gold selection papers do not match the frozen run order",
            kind="validation",
        )
    details_dir = Path(gold_dir).parent / "scoring-details"
    details_path = details_dir / f"{run_id}.json"
    retired_details_path = Path(gold_dir) / "scoring_details" / f"{run_id}.json"
    public_path = run_dir / "scoring" / "scored_run.json"
    if retired_details_path.exists():
        return operation_failed(
            "private scoring details exist at the retired Gold-local path",
            kind="precondition",
            next_action="move the existing details beside the private Gold root",
        )
    if details_path.exists() or public_path.exists():
        return operation_failed(
            "scoring outputs already exist and are immutable for this run id",
            kind="precondition",
            next_action="use the existing score or create a new benchmark run",
        )
    gold_payloads: list[dict[str, Any]] = []
    ai_documents: dict[str, dict[str, Any] | None] = {}
    delivery: dict[str, str] = {}
    l0: dict[str, Any] = {"schema_valid": 0, "schema_invalid": 0}
    for entry in selected_entries:
        if not isinstance(entry, dict):
            return operation_failed(
                "gold selection entries must be objects", kind="validation"
            )
        arxiv_id = str(entry.get("arxiv_id"))
        try:
            expert = validate_annotator_handle(
                str(entry.get("selected_expert") or "")
            )
        except ValueError as error:
            return operation_failed(
                f"invalid selected expert for {arxiv_id}: {error}",
                kind="validation",
            )
        expected_file = f"annotation_{expert}.json"
        if entry.get("annotation_file") != expected_file:
            return operation_failed(
                f"invalid selected annotation path for {arxiv_id}/{expert}",
                kind="validation",
            )
        try:
            from stella.benchmark.contribution_gold_revision import (
                load_selected_contribution_annotation,
            )

            gold_document = load_selected_contribution_annotation(
                Path(gold_dir), entry
            )
        except Exception as error:  # noqa: BLE001
            return operation_failed(
                f"invalid selected gold for {arxiv_id}/{expert}: {error}",
                kind="validation",
            )
        gold_payloads.append(gold_document)
        paper_record = run_dir / "papers" / arxiv_id / "paper_result.json"
        ai_document: dict[str, Any] | None = None
        if paper_record.is_file():
            record = json.loads(paper_record.read_text(encoding="utf-8"))
            canonical = record.get("canonical_path")
            if canonical and Path(canonical).is_file():
                ai_document = json.loads(
                    Path(canonical).read_text(encoding="utf-8")
                )
        status_path = run_dir / "papers" / arxiv_id / "status.json"
        delivery[arxiv_id] = (
            json.loads(status_path.read_text(encoding="utf-8")).get("status")
            if status_path.is_file()
            else "pending"
        )
        if ai_document is None:
            l0["schema_invalid"] += 1
        else:
            l0["schema_valid" if ai_document else "schema_invalid"] += 1
        ai_documents[arxiv_id] = ai_document
    suite = score_contribution_suite(gold_payloads, ai_documents)
    input_hashes = {
        "gold_selection": _sha256_path(selection_path),
        "method_config": _sha256_path(run_dir / "method_config.json"),
    }
    private = build_private_details(suite, input_hashes=input_hashes)
    details_dir.mkdir(parents=True, exist_ok=True)
    try:
        with details_path.open("x", encoding="utf-8") as stream:
            stream.write(
                json.dumps(private, indent=2, sort_keys=True, default=str) + "\n"
            )
    except FileExistsError:
        return operation_failed(
            "private scoring details already exist for this run id",
            kind="precondition",
        )
    public_data = {
        "run_id": run_id,
        "delivery": delivery_counts(delivery),
        "l0": l0,
        "l1": suite["aggregate"]["l1a"],
        "l1b": suite["aggregate"]["l1b"],
        "l2": {
            "l2a": suite["aggregate"]["l2a"],
            "l2b": suite["aggregate"]["l2b"],
        },
        "papers_scored": suite["aggregate"]["papers"],
        "input_hashes": input_hashes,
    }
    scoring_dir = run_dir / "scoring"
    scoring_dir.mkdir(parents=True, exist_ok=True)
    try:
        with public_path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(public_data, indent=2, sort_keys=True) + "\n")
    except FileExistsError:
        return operation_failed(
            "public scored-run record already exists for this run id",
            kind="precondition",
        )
    return operation_complete(
        artifacts=[str(details_path), str(public_path)],
        delivery=public_data["delivery"],
        l0=l0,
        l1=public_data["l1"],
        l2=public_data["l2"],
        papers_scored=public_data["papers_scored"],
    )


def _sha256_path(path: Path) -> str:
    import hashlib

    return (
        hashlib.sha256(path.read_bytes()).hexdigest()
        if path.is_file()
        else ""
    )


def validate_score_inputs(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed score must report its layered metrics without a composite."""

    if result.get("status") != "complete":
        return []
    detail = result.get("detail") or {}
    missing = [
        layer
        for layer in ("delivery", "l0", "l1", "l2")
        if layer not in detail
    ]
    if missing:
        return [f"score result is missing its layers: {missing}"]
    fused = [key for key in detail if key in ("overall", "composite", "pass")]
    if fused:
        return [f"score result must not fuse layers: {fused}"]
    return []


def emit_scorecard(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.emit_scorecard adapter: value-free public scorecard.

    Emits the aggregate scorecard for a scored run: configuration,
    hashes, and layered aggregates only - no identities, notes, gold
    values, or fused overall score.
    """

    from stella.workflows import operation_complete, operation_failed

    authorities = (payload or {}).get("authorities") or {}
    if not authorities.get("scoring"):
        return operation_failed(
            "emitting a public scorecard requires scoring authority",
            kind="authority",
            blockers=["scoring"],
        )
    run_id = (payload or {}).get("run_id") or ""
    run_dir = Path(root) / "runs" / "benchmark" / run_id
    scored = run_dir / "scoring" / "scored_run.json"
    if not run_id or not scored.is_file():
        return operation_failed(
            "no scored run found; run the score phase first",
            kind="precondition",
            next_action="score a run before emitting its scorecard",
        )
    try:
        scored_run = json.loads(scored.read_text(encoding="utf-8"))
    except ValueError as error:
        return operation_failed(
            f"invalid scored-run record: {error}", kind="validation"
        )
    from stella.schema_registry import schema_ref

    scorecard = {
        "schema": schema_ref("benchmark.hvs_contribution_scorecard"),
        "run_id": run_id,
        "delivery": scored_run.get("delivery"),
        "l0": scored_run.get("l0"),
        "l1": scored_run.get("l1"),
        "l1b": scored_run.get("l1b"),
        "l2": scored_run.get("l2"),
        "papers_scored": scored_run.get("papers_scored"),
        "input_hashes": scored_run.get("input_hashes"),
        "contract_note": (
            "layered aggregates and configuration only; no fused score"
        ),
    }
    scorecards_dir = Path(root) / "benchmark" / "scorecards"
    scorecards_dir.mkdir(parents=True, exist_ok=True)
    card_path = scorecards_dir / f"{run_id}.json"
    try:
        with card_path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(scorecard, indent=2, sort_keys=True) + "\n")
    except FileExistsError:
        return operation_failed(
            "public scorecard already exists and is immutable for this run id",
            kind="precondition",
            next_action="use the existing scorecard or create a new benchmark run",
        )
    return operation_complete(
        artifacts=[str(card_path)], scorecard=scorecard
    )


def validate_scorecard(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed scorecard emission must point at a parseable artifact."""

    if result.get("status") != "complete":
        return []
    errors: list[str] = []
    for reported in result.get("artifacts") or []:
        path = Path(reported)
        if not path.is_file():
            errors.append(f"scorecard emission reported {reported} but it is missing")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            errors.append(f"scorecard {reported} is not parseable: {error}")
    return errors
