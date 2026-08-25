"""Layered contribution-first benchmark scoring.

Layers, reported separately with no composite and no pass/fail verdict:

- L0: paper delivery, format validity, per-object quantity delivery.
- L1a: paper-object contribution identity precision/recall/F1.
- L1b: contribution_type accuracy and confusion on L1a-matched objects.
- L2a: paper_boundness status coverage/accuracy and confusion; L1 misses
  propagate every gold status to gold_only.
- L2b: multivalue quantity coverage and agreement via deterministic,
  order-independent bipartite multiset matching.
- Diagnostics on matched values: paper_preferred and source-category agreement.
- Required summary/evidence completeness audit (presence only, never text).

Public scorecards carry aggregates, rates, and hashes only; item rows live
in the private details artifact.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

from stella.lit.identity import (
    CandidateIdentity,
    _unique_coordinate_degrees,
    identity_from_contribution,
    normalize_name,
    parse_gaia_id,
)
from stella.benchmark.scoring import (
    _coordinate_value_degrees,
    compare_quantity,
    match_gold_to_ai,
)
from stella.lit.schema_specs import HVS_CONTRIBUTION_QUANTITIES

STRICT_STATUSES = ("value_match", "value_match_cross_format")
LENIENT_STATUSES = ("within_gold_error",)
CONTRIBUTION_TYPES = ("candidates_found", "follow_up")
BOUNDNESS_STATUSES = (
    "unbound",
    "possibly_unbound",
    "bound",
    "no_overall_conclusion",
    "not_assessed",
)
SOURCE_KINDS = ("this_paper", "prior_work", "unclear")

_VALUE_COMPONENTS = (
    "value",
    "error",
    "lower_error",
    "upper_error",
    "unit",
    "limit_kind",
    "range_lower",
    "range_upper",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rate(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _prf(tp: float, fp: float, fn: float) -> dict[str, float | None]:
    precision = _rate(tp, tp + fp)
    recall = _rate(tp, tp + fn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else None
    )
    return {"precision": precision, "recall": recall, "f1": f1}


# ---------------------------------------------------------------------------
# Identity adapters



def gold_contribution_identity(gold_contribution: dict[str, Any]) -> CandidateIdentity:
    return identity_from_contribution(gold_contribution)



def _value_fingerprint(value: dict[str, Any]) -> str:
    return json.dumps(
        {key: value.get(key) for key in _VALUE_COMPONENTS},
        ensure_ascii=False,
        sort_keys=True,
    )


def _value_tiebreak_fingerprint(value: dict[str, Any]) -> str:
    """Canonical full-record ordering only; never a scientific match key."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pair_outcome(quantity: str, gold_value: dict, ai_value: dict) -> dict[str, Any]:
    status = compare_quantity(quantity, gold_value, ai_value).get("status")
    strict = status in STRICT_STATUSES
    lenient = status in LENIENT_STATUSES
    return {
        "status": status,
        "strict": strict,
        "lenient": lenient,
        "gold_fingerprint": _value_fingerprint(gold_value),
        "ai_fingerprint": _value_fingerprint(ai_value),
        "gold_tiebreak": _value_tiebreak_fingerprint(gold_value),
        "ai_tiebreak": _value_tiebreak_fingerprint(ai_value),
    }


def match_value_multisets(
    quantity: str,
    gold_values: list[dict[str, Any]],
    ai_values: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic order-independent bipartite multiset matching.

    Optimizes lexicographically: maximum paired values, then maximum strict
    agreement, then maximum lenient agreement; ties break on the sorted
    sequence of (gold fingerprint, ai fingerprint) pair keys so the result is
    independent of array order and of any IDs.
    """

    gold_count, ai_count = len(gold_values), len(ai_values)
    size = max(gold_count, ai_count)
    outcomes = [
        [_pair_outcome(quantity, gold, ai) for ai in ai_values] for gold in gold_values
    ]
    padded = [row + [None] * (size - ai_count) for row in outcomes] + [
        [None] * size for _ in range(size - gold_count)
    ]

    memo: dict[int, tuple[int, int, int, tuple]] = {}

    def candidate_for(mask: int, ai_index: int) -> tuple[int, int, int, tuple]:
        gold_index = bin(mask).count("1")
        outcome = padded[gold_index][ai_index]
        rest = solve(mask | (1 << ai_index))
        if outcome is None:
            return rest
        pair_key = (outcome["gold_tiebreak"], outcome["ai_tiebreak"])
        return (
            rest[0] + 1,
            rest[1] + (1 if outcome["strict"] else 0),
            rest[2] + (1 if outcome["lenient"] else 0),
            tuple(sorted(rest[3] + (pair_key,))),
        )

    def solve(mask: int) -> tuple[int, int, int, tuple]:
        gold_index = bin(mask).count("1")
        if gold_index >= size:
            return (0, 0, 0, ())
        if mask in memo:
            return memo[mask]
        candidates = [
            candidate_for(mask, ai_index)
            for ai_index in range(size)
            if not mask & (1 << ai_index)
        ]
        best = max(item[:3] for item in candidates)
        winner = min(
            (item for item in candidates if item[:3] == best),
            key=lambda item: item[3],
        )
        memo[mask] = winner
        return winner

    winner = solve(0)
    pairs: list[dict[str, Any]] = []
    mask = 0
    while bin(mask).count("1") < size:
        target = solve(mask)
        gold_index = bin(mask).count("1")
        for ai_index in range(size):
            if mask & (1 << ai_index):
                continue
            if candidate_for(mask, ai_index) == target:
                outcome = padded[gold_index][ai_index]
                mask |= 1 << ai_index
                if outcome is not None:
                    pairs.append(
                        {
                            "gold_index": gold_index,
                            "ai_index": ai_index,
                            "status": outcome["status"],
                            "paper_preferred_gold": gold_values[gold_index].get("paper_preferred"),
                            "paper_preferred_ai": ai_values[ai_index].get("paper_preferred"),
                            "source_kind_gold": gold_values[gold_index].get("source"),
                            "source_kind_ai": ai_values[ai_index].get("source"),
                        }
                    )
                break
        else:  # pragma: no cover - the DP guarantees a reconstruction path
            break

    paired_gold = {pair["gold_index"] for pair in pairs}
    paired_ai = {pair["ai_index"] for pair in pairs}
    return {
        "pairs": pairs,
        "gold_only": [index for index in range(gold_count) if index not in paired_gold],
        "ai_only": [index for index in range(ai_count) if index not in paired_ai],
    }


# ---------------------------------------------------------------------------
# Paper scoring


def _confusion(pairs: list[tuple[str, str]], labels: tuple[str, ...]) -> dict[str, int]:
    counts = {f"{gold}|{ai}": 0 for gold in labels for ai in labels}
    for gold, ai in pairs:
        key = f"{gold}|{ai}"
        if key in counts:
            counts[key] += 1
    return counts


def score_contribution_paper(
    gold_payload: dict[str, Any],
    ai_document: dict[str, Any] | None,
) -> dict[str, Any]:
    """Score one paper's contribution document against its gold annotation."""

    gold_contributions = gold_payload.get("contributions") or []
    ai_contributions = (
        (ai_document or {}).get("object_contributions") or []
    )
    details: dict[str, Any] = {
        "arxiv_id": gold_payload.get("arxiv_id"),
        "l0": {
            "ai_document_delivered": ai_document is not None,
            "ai_schema_valid": False,
            "object_quantity_delivery": {
                "complete": 0,
                "failed": 0,
            },
        },
    }
    if ai_document is not None:
        try:
            from stella.lit.hvs_contribution_models import (
                validate_literature_hvs_contributions_document,
            )

            validate_literature_hvs_contributions_document(ai_document)
            details["l0"]["ai_schema_valid"] = True
        except Exception:
            details["l0"]["ai_schema_valid"] = False
        for contribution in ai_contributions:
            status = contribution.get("quantity_extraction_status")
            key = "complete" if status == "complete" else "failed"
            details["l0"]["object_quantity_delivery"][key] += 1

    gold_identities = [gold_contribution_identity(item) for item in gold_contributions]
    ai_identities = [identity_from_contribution(item) for item in ai_contributions]
    matching = match_gold_to_ai(gold_identities, ai_identities)
    pairs = {item["gold_index"]: item["ai_index"] for item in matching["pairs"]}
    unmatched_gold = set(matching["unmatched_gold"])
    unmatched_ai = set(matching["unmatched_ai"])

    type_pairs: list[tuple[str, str]] = []
    status_pairs: list[tuple[str, str]] = []
    value_rows: list[dict[str, Any]] = []
    preferred_gold: list[Any] = []
    preferred_ai: list[Any] = []
    source_gold: list[Any] = []
    source_ai: list[Any] = []
    summary_audit = {"required_summary_present": 0, "required_evidence_present": 0, "matched": 0}

    l2b_counts = {
        "gold_values": 0,
        "ai_values": 0,
        "paired": 0,
        "gold_only": 0,
        "ai_only": 0,
        "strict_agreement": 0,
        "lenient_agreement": 0,
        "mismatch": 0,
    }

    for gold_index, gold_contribution in enumerate(gold_contributions):
        gold_status = (gold_contribution.get("paper_boundness") or {}).get("status")
        if gold_index in unmatched_gold:
            status_pairs.append((gold_status, "gold_only"))
            for group in gold_contribution.get("quantities") or []:
                values = group.get("values") or []
                l2b_counts["gold_values"] += len(values)
                l2b_counts["gold_only"] += len(values)
            continue
        ai_contribution = ai_contributions[pairs[gold_index]]
        type_pairs.append(
            (
                gold_contribution.get("contribution_type") or "",
                ai_contribution.get("contribution_type") or "",
            )
        )
        status_pairs.append(
            (gold_status, (ai_contribution.get("paper_boundness") or {}).get("status"))
        )
        summary_audit["matched"] += 1
        if str(ai_contribution.get("contribution_summary") or "").strip():
            summary_audit["required_summary_present"] += 1
        if ai_contribution.get("contribution_evidence"):
            summary_audit["required_evidence_present"] += 1

        gold_groups = {item.get("quantity"): item for item in gold_contribution.get("quantities") or []}
        ai_groups = {item.get("quantity"): item for item in ai_contribution.get("quantities") or []}
        for quantity in HVS_CONTRIBUTION_QUANTITIES:
            gold_values = (gold_groups.get(quantity) or {}).get("values") or []
            ai_values = (ai_groups.get(quantity) or {}).get("values") or []
            if not gold_values and not ai_values:
                continue
            l2b_counts["gold_values"] += len(gold_values)
            l2b_counts["ai_values"] += len(ai_values)
            result = match_value_multisets(quantity, gold_values, ai_values)
            for pair in result["pairs"]:
                l2b_counts["paired"] += 1
                if pair["status"] in STRICT_STATUSES:
                    l2b_counts["strict_agreement"] += 1
                elif pair["status"] in LENIENT_STATUSES:
                    l2b_counts["lenient_agreement"] += 1
                else:
                    l2b_counts["mismatch"] += 1
                preferred_gold.append(pair["paper_preferred_gold"])
                preferred_ai.append(pair["paper_preferred_ai"])
                source_gold.append(pair["source_kind_gold"])
                source_ai.append(pair["source_kind_ai"])
                value_rows.append(
                    {
                        "quantity": quantity,
                        "status": pair["status"],
                        "paper_preferred_gold": pair["paper_preferred_gold"],
                        "paper_preferred_ai": pair["paper_preferred_ai"],
                        "source_kind_gold": pair["source_kind_gold"],
                        "source_kind_ai": pair["source_kind_ai"],
                    }
                )
            l2b_counts["gold_only"] += len(result["gold_only"])
            l2b_counts["ai_only"] += len(result["ai_only"])

    for ai_index in unmatched_ai:
        for group in ai_contributions[ai_index].get("quantities") or []:
            values = group.get("values") or []
            l2b_counts["ai_values"] += len(values)
            l2b_counts["ai_only"] += len(values)

    preferred_agreement = sum(
        1 for gold, ai in zip(preferred_gold, preferred_ai) if gold == ai
    )
    source_agreement = sum(
        1 for gold, ai in zip(source_gold, source_ai) if gold == ai
    )

    matched_count = len(gold_contributions) - len(unmatched_gold)
    type_correct = sum(1 for gold, ai in type_pairs if gold == ai)
    status_assigned = [pair for pair in status_pairs if pair[1] != "gold_only"]
    status_correct = sum(1 for gold, ai in status_assigned if gold == ai)

    details["l1a"] = {
        "gold_contributions": len(gold_contributions),
        "ai_contributions": len(ai_contributions),
        "matched": matched_count,
        "gold_only": len(unmatched_gold),
        "ai_only": len(unmatched_ai),
        "match_methods": {
            method: sum(
                1 for item in matching["pairs"] if item.get("method") == method
            )
            for method in sorted(
                {str(item.get("method") or "") for item in matching["pairs"]}
            )
            if method
        },
    }
    details["l1b"] = {
        "matched": len(type_pairs),
        "type_correct": type_correct,
        "confusion": _confusion(type_pairs, CONTRIBUTION_TYPES),
    }
    details["l2a"] = {
        "gold_statuses": len(status_pairs),
        "assigned": len(status_assigned),
        "status_correct": status_correct,
        "confusion": _confusion(status_pairs, (*BOUNDNESS_STATUSES, "gold_only")),
    }
    details["l2b"] = dict(l2b_counts)
    details["diagnostics"] = {
        "paper_preferred": {
            "compared": len(preferred_gold),
            "agreement": preferred_agreement,
        },
        "source_kind": {
            "compared": len(source_gold),
            "agreement": source_agreement,
        },
    }
    details["summary_evidence_audit"] = summary_audit
    details["value_rows"] = value_rows

    aggregate = {
        "l1a": _prf(matched_count, len(unmatched_ai), len(unmatched_gold)),
        "l1b": {
            "accuracy": _rate(type_correct, len(type_pairs)),
        },
        "l2a": {
            "coverage": _rate(len(status_assigned), len(status_pairs)),
            "accuracy": _rate(status_correct, len(status_assigned)),
        },
        "l2b": {
            "value_recall": _rate(l2b_counts["paired"], l2b_counts["gold_values"]),
            "value_precision": _rate(l2b_counts["paired"], l2b_counts["ai_values"]),
            "strict_agreement_rate": _rate(
                l2b_counts["strict_agreement"], l2b_counts["paired"]
            ),
        },
        "diagnostics": {
            "paper_preferred_agreement_rate": _rate(
                preferred_agreement, len(preferred_gold)
            ),
            "source_kind_agreement_rate": _rate(source_agreement, len(source_gold)),
        },
    }
    return {"details": details, "aggregate": aggregate}


def score_contribution_suite(
    gold_payloads: list[dict[str, Any]],
    ai_documents: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    """Score a suite; returns the aggregate view and per-paper details."""

    per_paper = []
    totals = {
        "papers": 0,
        "l1a": {"matched": 0, "ai_only": 0, "gold_only": 0},
        "l1b": {"matched": 0, "type_correct": 0},
        "l2a": {"gold_statuses": 0, "assigned": 0, "status_correct": 0},
        "l2b": dict.fromkeys(
            (
                "gold_values",
                "ai_values",
                "paired",
                "gold_only",
                "ai_only",
                "strict_agreement",
                "lenient_agreement",
                "mismatch",
            ),
            0,
        ),
        "diagnostics": {
            "paper_preferred": {"compared": 0, "agreement": 0},
            "source_kind": {"compared": 0, "agreement": 0},
        },
        "summary_evidence_audit": {
            "matched": 0,
            "required_summary_present": 0,
            "required_evidence_present": 0,
        },
    }
    for gold_payload in gold_payloads:
        arxiv_id = gold_payload.get("arxiv_id")
        ai_document = ai_documents.get(arxiv_id)
        result = score_contribution_paper(gold_payload, ai_document)
        per_paper.append(result["details"])
        totals["papers"] += 1
        totals["l1a"]["matched"] += result["details"]["l1a"]["matched"]
        totals["l1a"]["ai_only"] += result["details"]["l1a"]["ai_only"]
        totals["l1a"]["gold_only"] += result["details"]["l1a"]["gold_only"]
        totals["l1b"]["matched"] += result["details"]["l1b"]["matched"]
        totals["l1b"]["type_correct"] += result["details"]["l1b"]["type_correct"]
        totals["l2a"]["gold_statuses"] += result["details"]["l2a"]["gold_statuses"]
        totals["l2a"]["assigned"] += result["details"]["l2a"]["assigned"]
        totals["l2a"]["status_correct"] += result["details"]["l2a"]["status_correct"]
        for key in totals["l2b"]:
            totals["l2b"][key] += result["details"]["l2b"][key]
        for key in ("compared", "agreement"):
            totals["diagnostics"]["paper_preferred"][key] += result["details"]["diagnostics"]["paper_preferred"][key]
            totals["diagnostics"]["source_kind"][key] += result["details"]["diagnostics"]["source_kind"][key]
        for key in ("matched", "required_summary_present", "required_evidence_present"):
            totals["summary_evidence_audit"][key] += result["details"]["summary_evidence_audit"][key]

    aggregate = {
        "papers": totals["papers"],
        "l1a": _prf(
            totals["l1a"]["matched"],
            totals["l1a"]["ai_only"],
            totals["l1a"]["gold_only"],
        ),
        "l1b": {
            "accuracy": _rate(totals["l1b"]["type_correct"], totals["l1b"]["matched"]),
        },
        "l2a": {
            "coverage": _rate(totals["l2a"]["assigned"], totals["l2a"]["gold_statuses"]),
            "accuracy": _rate(totals["l2a"]["status_correct"], totals["l2a"]["assigned"]),
        },
        "l2b": {
            "value_recall": _rate(totals["l2b"]["paired"], totals["l2b"]["gold_values"]),
            "value_precision": _rate(totals["l2b"]["paired"], totals["l2b"]["ai_values"]),
            "strict_agreement_rate": _rate(
                totals["l2b"]["strict_agreement"], totals["l2b"]["paired"]
            ),
        },
        "diagnostics": {
            "paper_preferred_agreement_rate": _rate(
                totals["diagnostics"]["paper_preferred"]["agreement"],
                totals["diagnostics"]["paper_preferred"]["compared"],
            ),
            "source_kind_agreement_rate": _rate(
                totals["diagnostics"]["source_kind"]["agreement"],
                totals["diagnostics"]["source_kind"]["compared"],
            ),
        },
        "summary_evidence_audit": totals["summary_evidence_audit"],
    }
    return {"aggregate": aggregate, "totals": totals, "papers": per_paper}


def build_public_scorecard(
    suite_result: dict[str, Any],
    *,
    input_hashes: dict[str, str],
) -> dict[str, Any]:
    """Aggregates, rates, and hashes only — no identities, notes, or values."""

    from stella.schema_registry import schema_ref

    return {
        "schema": schema_ref("benchmark.hvs_contribution_scorecard"),
        "aggregate": suite_result["aggregate"],
        "totals": suite_result["totals"],
        "input_hashes": input_hashes,
        "contract_note": "contribution benchmark scoring; separate layers only",
    }


def build_private_details(
    suite_result: dict[str, Any],
    *,
    input_hashes: dict[str, str],
) -> dict[str, Any]:
    from stella.schema_registry import schema_ref

    return {
        "schema": schema_ref("benchmark.hvs_contribution_scoring_details"),
        "input_hashes": input_hashes,
        "papers": suite_result["papers"],
    }


def leak_guard(payload: dict[str, Any], forbidden_strings: set[str]) -> list[str]:
    """Return the JSON paths where any forbidden private string appears."""

    hits: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str) and value in forbidden_strings:
            hits.append(path)

    walk(payload, "$")
    return hits
