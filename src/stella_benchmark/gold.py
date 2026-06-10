"""Assemble gold v7 candidate records from alignment plus expert adjudication."""

from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime
from typing import Any

from .field_specs import FIELD_SPECS, get_by_path
from .models import (
    BENCHMARK_GOLD_PROVENANCE_SCHEMA_VERSION,
    AdjudicationItem,
    AdjudicationRecord,
    AlignmentRecord,
    GoldProvenance,
    GoldProvenanceEntry,
)

_SPEC_BY_PATH = {spec.path: spec for spec in FIELD_SPECS}
# reject_field empties a field; only fields that the v7 schema allows to be
# empty can take it.
_REJECTABLE_EMPTY_VALUES = {
    "quantity": None,
    "coordinate": None,
    "identifier": "",
    "identifier_set": [],
}


class GoldAssemblyError(ValueError):
    pass


def _set_by_path(candidate: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = candidate
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    if value is None:
        node[parts[-1]] = None
    else:
        node[parts[-1]] = value


def _member_candidates(
    alignment: AlignmentRecord, variant_payloads: dict[str, dict[str, Any]]
) -> dict[str, dict[str, dict[str, Any]]]:
    """cluster_id -> variant_id -> candidate dict (resolved via record ids)."""
    by_record_id: dict[str, dict[str, dict[str, Any]]] = {}
    for variant_id, payload in variant_payloads.items():
        for index, candidate in enumerate(payload.get("candidates") or []):
            if not isinstance(candidate, dict):
                continue
            identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
            record_id = str(identifiers.get("record_id") or "").strip() or f"{variant_id}#{index}"
            by_record_id.setdefault(variant_id, {})[record_id] = candidate
    members: dict[str, dict[str, dict[str, Any]]] = {}
    for cluster in alignment.clusters:
        cluster_members: dict[str, dict[str, Any]] = {}
        for variant_id, record_id in cluster.members.items():
            candidate = by_record_id.get(variant_id, {}).get(record_id)
            if candidate is None:
                raise GoldAssemblyError(
                    f"alignment references unknown candidate {record_id!r} in variant {variant_id!r}; "
                    "re-run alignment"
                )
            cluster_members[variant_id] = candidate
        members[cluster.cluster_id] = cluster_members
    return members


def _verdict_maps(
    adjudication: AdjudicationRecord,
) -> tuple[dict[str, AdjudicationItem], dict[str, dict[str, AdjudicationItem]], list[AdjudicationItem]]:
    presence: dict[str, AdjudicationItem] = {}
    fields: dict[str, dict[str, AdjudicationItem]] = {}
    additions: list[AdjudicationItem] = []
    for item in adjudication.items:
        if item.kind == "candidate_presence":
            presence[item.item_id] = item
        elif item.kind == "field_value":
            cluster_id = item.cluster_id or item.item_id.split(":", 1)[0]
            fields.setdefault(cluster_id, {})[item.field_path] = item
        elif item.kind == "candidate_addition":
            additions.append(item)
    return presence, fields, additions


def _primary_base_variant(
    alignment: AlignmentRecord, presence: dict[str, AdjudicationItem]
) -> str:
    votes: Counter[str] = Counter()
    for cluster in alignment.clusters:
        verdict = presence.get(cluster.cluster_id)
        if verdict is not None and verdict.verdict == "accept":
            base = verdict.base_variant or min(cluster.members)
            votes[base] += 1
    if votes:
        best_count = max(votes.values())
        return sorted(vid for vid, count in votes.items() if count == best_count)[0]
    return sorted(variant.variant_id for variant in alignment.variants)[0]


def _apply_field_verdict(
    candidate: dict[str, Any],
    item: AdjudicationItem,
    cluster_members: dict[str, dict[str, Any]],
) -> None:
    spec = _SPEC_BY_PATH.get(item.field_path)
    if spec is None:
        raise GoldAssemblyError(f"{item.item_id}: unknown field path {item.field_path!r}")
    if item.verdict == "accept":
        return
    if item.verdict == "accept_variant":
        source = cluster_members.get(item.accepted_from_variant)
        if source is None:
            raise GoldAssemblyError(
                f"{item.item_id}: variant {item.accepted_from_variant!r} has no candidate in this cluster"
            )
        value = get_by_path(source, item.field_path)
        if value is None:
            raise GoldAssemblyError(
                f"{item.item_id}: variant {item.accepted_from_variant!r} has no value for {item.field_path!r}"
            )
        _set_by_path(candidate, item.field_path, copy.deepcopy(value))
        return
    if item.verdict == "fix":
        if item.fixed_payload is None:
            raise GoldAssemblyError(f"{item.item_id}: fix verdict requires fixed_payload")
        _set_by_path(candidate, item.field_path, copy.deepcopy(item.fixed_payload))
        return
    if item.verdict == "reject_field":
        if spec.kind not in _REJECTABLE_EMPTY_VALUES:
            raise GoldAssemblyError(
                f"{item.item_id}: reject_field is not allowed for required field kind {spec.kind!r}"
            )
        _set_by_path(candidate, item.field_path, copy.deepcopy(_REJECTABLE_EMPTY_VALUES[spec.kind]))
        return
    raise GoldAssemblyError(f"{item.item_id}: verdict {item.verdict!r} is not valid for field items")


def assemble_gold(
    alignment: AlignmentRecord,
    adjudication: AdjudicationRecord,
    variant_payloads: dict[str, dict[str, Any]],
    *,
    adjudication_path: str,
) -> tuple[dict[str, Any], GoldProvenance]:
    if adjudication.alignment_digest != alignment.alignment_digest:
        raise GoldAssemblyError(
            "adjudication was made against a different alignment digest; re-run alignment "
            "and re-adjudicate the affected items"
        )
    if adjudication.paper_status_verdict is None:
        raise GoldAssemblyError("paper status verdict is missing")

    presence, field_items, additions = _verdict_maps(adjudication)
    members = _member_candidates(alignment, variant_payloads)
    primary_variant = _primary_base_variant(alignment, presence)
    primary_payload = variant_payloads.get(primary_variant)
    if primary_payload is None:
        raise GoldAssemblyError(f"primary base variant {primary_variant!r} has no payload")

    entries: list[GoldProvenanceEntry] = []
    gold_candidates: list[dict[str, Any]] = []
    for cluster in alignment.clusters:
        verdict = presence.get(cluster.cluster_id)
        if verdict is None:
            raise GoldAssemblyError(f"missing presence verdict for {cluster.cluster_id}")
        if verdict.verdict == "reject":
            entries.append(
                GoldProvenanceEntry(
                    target=cluster.cluster_id, source="verdict", item_id=verdict.item_id
                )
            )
            continue
        if verdict.verdict != "accept":
            raise GoldAssemblyError(
                f"{cluster.cluster_id}: verdict {verdict.verdict!r} is not valid for presence items"
            )
        base_variant = verdict.base_variant or min(cluster.members)
        base = members[cluster.cluster_id].get(base_variant)
        if base is None:
            raise GoldAssemblyError(
                f"{cluster.cluster_id}: base variant {base_variant!r} has no candidate in this cluster"
            )
        candidate = copy.deepcopy(base)
        cluster_verdicts = field_items.get(cluster.cluster_id, {})
        for field in cluster.fields:
            item = cluster_verdicts.get(field.field_path)
            target = f"{cluster.cluster_id}:{field.field_path}"
            if item is None:
                entries.append(
                    GoldProvenanceEntry(
                        target=target, source="auto_consensus", base_variant=base_variant
                    )
                )
                continue
            _apply_field_verdict(candidate, item, members[cluster.cluster_id])
            entries.append(
                GoldProvenanceEntry(target=target, source="verdict", item_id=item.item_id)
            )
        entries.append(
            GoldProvenanceEntry(
                target=cluster.cluster_id,
                source="verdict",
                item_id=verdict.item_id,
                base_variant=base_variant,
            )
        )
        gold_candidates.append(candidate)

    for item in additions:
        if item.verdict != "add_missing":
            raise GoldAssemblyError(
                f"{item.item_id}: verdict {item.verdict!r} is not valid for addition items"
            )
        if item.added_payload is None:
            raise GoldAssemblyError(f"{item.item_id}: add_missing verdict requires added_payload")
        gold_candidates.append(copy.deepcopy(item.added_payload))
        entries.append(GoldProvenanceEntry(target=item.item_id, source="verdict", item_id=item.item_id))

    for index, candidate in enumerate(gold_candidates, start=1):
        identifiers = candidate.setdefault("identifiers", {})
        if isinstance(identifiers, dict):
            identifiers["record_id"] = f"{alignment.arxiv_id}:cand-{index:03d}"

    status = adjudication.paper_status_verdict.gold_status
    if status == "candidates_found" and not gold_candidates:
        raise GoldAssemblyError("gold status is candidates_found but every cluster was rejected")
    if status == "no_candidates" and gold_candidates:
        raise GoldAssemblyError("gold status is no_candidates but accepted candidates exist")

    now = datetime.now().isoformat(timespec="seconds")
    gold_payload: dict[str, Any] = {
        "schema_version": primary_payload.get("schema_version"),
        "generated_at": now,
        "paper": copy.deepcopy(primary_payload.get("paper")),
        "inputs": copy.deepcopy(primary_payload.get("inputs")),
        "extraction": {
            "status": status,
            "extracted_at": now,
            "extractor": f"stella-benchmark-gold (expert: {adjudication.expert.id})",
            "summary": (
                "Gold standard assembled from expert adjudication "
                f"({adjudication_path}); see gold_provenance.json for item-level provenance."
            ),
        },
        "method_chain": copy.deepcopy(primary_payload.get("method_chain") or []),
        "candidates": gold_candidates,
        "candidate_groups_considered": copy.deepcopy(
            primary_payload.get("candidate_groups_considered") or []
        ),
    }
    provenance = GoldProvenance(
        schema_version=BENCHMARK_GOLD_PROVENANCE_SCHEMA_VERSION,
        arxiv_id=alignment.arxiv_id,
        generated_at=now,
        adjudication_path=adjudication_path,
        alignment_digest=alignment.alignment_digest,
        expert=adjudication.expert,
        entries=entries,
    )
    return gold_payload, provenance
