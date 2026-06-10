"""Cross-variant candidate alignment and field diffing."""

from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import datetime
from typing import Any

from .evidence import EvidenceResolver
from .field_specs import (
    FIELD_SPECS,
    FieldSpec,
    evidence_refs,
    get_by_path,
    snapshots_agree,
    value_snapshot,
)
from .models import (
    BENCHMARK_ALIGNMENT_SCHEMA_VERSION,
    AlignmentCluster,
    AlignmentField,
    AlignmentPaperInfo,
    AlignmentPaperStatus,
    AlignmentRecord,
    AlignmentVariantSummary,
    IdentifierSummary,
    RecallAssists,
    ResolvedEvidence,
    UncoveredEcsvRow,
)

MAX_UNCOVERED_ROWS = 50
_BRACKET_RE = re.compile(r"^[\[\(]|[\]\)]$")


def normalize_identifier(value: str) -> str:
    text = " ".join(str(value).split()).casefold().lstrip("*").strip()
    return _BRACKET_RE.sub("", text).strip()


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def add(self, node: int) -> None:
        self.parent.setdefault(node, node)

    def find(self, node: int) -> int:
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[max(root_a, root_b)] = min(root_a, root_b)


def _candidate_keys(candidate: dict[str, Any]) -> tuple[set[str], set[str]]:
    """(gaia keys, identifier keys) used for cluster matching."""
    identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
    gaia_keys: set[str] = set()
    ident_keys: set[str] = set()
    gaia = normalize_identifier(str(identifiers.get("gaia_source_id") or ""))
    if gaia:
        gaia_keys.add(gaia)
    for item in identifiers.get("all") or []:
        if isinstance(item, dict):
            value = normalize_identifier(str(item.get("value") or ""))
            if value:
                ident_keys.add(value)
    return gaia_keys, ident_keys


def compute_alignment_digest(variant_payloads: dict[str, dict[str, Any]]) -> str:
    canonical = json.dumps(
        {variant_id: variant_payloads[variant_id] for variant_id in sorted(variant_payloads)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_id(candidate: dict[str, Any], variant_id: str, index: int) -> str:
    identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
    record_id = str(identifiers.get("record_id") or "").strip()
    return record_id or f"{variant_id}#{index}"


def align_candidates(variant_payloads: dict[str, dict[str, Any]]) -> list[AlignmentCluster]:
    variant_order = sorted(variant_payloads)
    nodes: list[tuple[str, int, dict[str, Any]]] = []
    for variant_id in variant_order:
        candidates = variant_payloads[variant_id].get("candidates") or []
        for index, candidate in enumerate(candidates):
            if isinstance(candidate, dict):
                nodes.append((variant_id, index, candidate))

    uf = _UnionFind()
    gaia_map: dict[str, list[int]] = {}
    ident_map: dict[str, list[int]] = {}
    for node_id, (_, _, candidate) in enumerate(nodes):
        uf.add(node_id)
        gaia_keys, ident_keys = _candidate_keys(candidate)
        for key in gaia_keys:
            gaia_map.setdefault(key, []).append(node_id)
        for key in ident_keys:
            ident_map.setdefault(key, []).append(node_id)
    for grouped in list(gaia_map.values()) + list(ident_map.values()):
        for other in grouped[1:]:
            uf.union(grouped[0], other)

    components: dict[int, list[int]] = {}
    for node_id in range(len(nodes)):
        components.setdefault(uf.find(node_id), []).append(node_id)

    ordered_components = sorted(components.values(), key=lambda member_ids: min(member_ids))
    clusters: list[AlignmentCluster] = []
    for cluster_index, member_ids in enumerate(ordered_components, start=1):
        members: dict[str, str] = {}
        member_candidates: dict[str, dict[str, Any]] = {}
        conflict = False
        gaia_values: set[str] = set()
        all_values: list[str] = []
        for node_id in sorted(member_ids):
            variant_id, index, candidate = nodes[node_id]
            if variant_id in members:
                conflict = True
                continue
            members[variant_id] = _record_id(candidate, variant_id, index)
            member_candidates[variant_id] = candidate
            identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
            gaia = str(identifiers.get("gaia_source_id") or "").strip()
            if gaia:
                gaia_values.add(gaia)
            for item in identifiers.get("all") or []:
                if isinstance(item, dict):
                    value = str(item.get("value") or "").strip()
                    if value and value not in all_values:
                        all_values.append(value)

        matched_by = "unmatched"
        if len(members) > 1:
            shared_gaia = len(gaia_values) == 1 and sum(
                1
                for candidate in member_candidates.values()
                if str((candidate.get("identifiers") or {}).get("gaia_source_id") or "").strip()
            ) == len(members)
            matched_by = "gaia_source_id" if shared_gaia else "identifier_overlap"

        first_candidate = member_candidates[min(member_candidates)]
        first_identifiers = (
            first_candidate.get("identifiers")
            if isinstance(first_candidate.get("identifiers"), dict)
            else {}
        )
        display = str(first_identifiers.get("paper_candidate_id") or "") or (
            sorted(gaia_values)[0] if gaia_values else ""
        )
        clusters.append(
            AlignmentCluster(
                cluster_id=f"cluster-{cluster_index:03d}",
                matched_by=matched_by,
                members=members,
                missing_in=[vid for vid in variant_order if vid not in members],
                conflict=conflict,
                identifier_summary=IdentifierSummary(
                    gaia_source_id=sorted(gaia_values)[0] if len(gaia_values) == 1 else "",
                    display=display,
                    all_values=all_values,
                ),
                fields=[],
            )
        )
    return clusters


def diff_cluster_fields(
    member_candidates: dict[str, dict[str, Any]],
    resolver: EvidenceResolver,
    *,
    specs: tuple[FieldSpec, ...] = FIELD_SPECS,
) -> list[AlignmentField]:
    fields: list[AlignmentField] = []
    for spec in specs:
        snapshots = {
            variant_id: value_snapshot(spec, get_by_path(candidate, spec.path))
            for variant_id, candidate in member_candidates.items()
        }
        if all(snapshot is None for snapshot in snapshots.values()):
            continue
        agreement = snapshots_agree(spec, list(snapshots.values()))
        evidence: dict[str, list[ResolvedEvidence]] = {}
        for variant_id, candidate in member_candidates.items():
            if snapshots[variant_id] is None:
                continue
            refs = evidence_refs(spec, candidate)
            if refs:
                evidence[variant_id] = [resolver.resolve(ref) for ref in refs[:4]]
        fields.append(
            AlignmentField(
                field_path=spec.path,
                kind=spec.kind,  # type: ignore[arg-type]
                values=snapshots,
                agreement=agreement,
                evidence=evidence,
            )
        )
    return fields


def _collect_ref_lines(candidate: dict[str, Any], coverage: dict[str, set[int]]) -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("kind") == "ecsv_cell" and node.get("path"):
                try:
                    coverage.setdefault(str(node["path"]), set()).add(int(node.get("line") or 0))
                except (TypeError, ValueError):
                    pass
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(candidate)


def uncovered_ecsv_rows(
    variant_payloads: dict[str, dict[str, Any]],
    resolver: EvidenceResolver,
) -> list[UncoveredEcsvRow]:
    """ECSV data rows in candidate-referenced tables that no candidate cites."""
    coverage: dict[str, set[int]] = {}
    for payload in variant_payloads.values():
        for candidate in payload.get("candidates") or []:
            if isinstance(candidate, dict):
                _collect_ref_lines(candidate, coverage)

    uncovered: list[UncoveredEcsvRow] = []
    for rel_path in sorted(coverage):
        covered_lines = coverage[rel_path]
        for line in resolver.data_row_lines(rel_path):
            if line in covered_lines:
                continue
            cells = resolver.row_cells(rel_path, line)
            preview = " | ".join(list(cells.values())[:6])
            guess = next(iter(cells.values()), "")
            uncovered.append(
                UncoveredEcsvRow(path=rel_path, line=line, identifier_guess=guess, row_preview=preview)
            )
            if len(uncovered) >= MAX_UNCOVERED_ROWS:
                return uncovered
    return uncovered


def sample_spot_checks(clusters: list[AlignmentCluster], *, fraction: float, seed: int) -> list[str]:
    agreeing_items = [
        f"{cluster.cluster_id}:{field.field_path}"
        for cluster in clusters
        for field in cluster.fields
        if field.agreement and len(cluster.members) > 1
    ]
    if not agreeing_items or fraction <= 0:
        return []
    count = max(1, round(fraction * len(agreeing_items)))
    rng = random.Random(seed)
    return sorted(rng.sample(agreeing_items, min(count, len(agreeing_items))))


def build_alignment_record(
    arxiv_id: str,
    variant_payloads: dict[str, dict[str, Any]],
    resolver: EvidenceResolver,
    *,
    spot_check_fraction: float = 0.1,
    seed: int = 0,
) -> AlignmentRecord:
    variant_order = sorted(variant_payloads)
    clusters = align_candidates(variant_payloads)

    record_by_id: dict[str, dict[str, dict[str, Any]]] = {}
    for variant_id in variant_order:
        for index, candidate in enumerate(variant_payloads[variant_id].get("candidates") or []):
            if isinstance(candidate, dict):
                record_by_id.setdefault(variant_id, {})[_record_id(candidate, variant_id, index)] = candidate
    for cluster in clusters:
        member_candidates = {
            variant_id: record_by_id[variant_id][record_id]
            for variant_id, record_id in cluster.members.items()
        }
        cluster.fields = diff_cluster_fields(member_candidates, resolver)

    status_values = {
        variant_id: str((variant_payloads[variant_id].get("extraction") or {}).get("status") or "")
        for variant_id in variant_order
    }
    first_paper = variant_payloads[variant_order[0]].get("paper") or {}
    links = first_paper.get("links") if isinstance(first_paper.get("links"), dict) else {}

    return AlignmentRecord(
        schema_version=BENCHMARK_ALIGNMENT_SCHEMA_VERSION,
        arxiv_id=arxiv_id,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        alignment_digest=compute_alignment_digest(variant_payloads),
        paper=AlignmentPaperInfo(
            title=str(first_paper.get("title") or ""),
            month=str(first_paper.get("month") or ""),
            links={key: str(value) for key, value in links.items() if value},
        ),
        variants=[
            AlignmentVariantSummary(
                variant_id=variant_id,
                status=status_values[variant_id],
                candidate_count=len(variant_payloads[variant_id].get("candidates") or []),
            )
            for variant_id in variant_order
        ],
        paper_status=AlignmentPaperStatus(
            values=status_values, agreement=len(set(status_values.values())) == 1
        ),
        clusters=clusters,
        recall_assists=RecallAssists(
            uncovered_ecsv_rows=uncovered_ecsv_rows(variant_payloads, resolver)
        ),
        consensus_spot_checks=sample_spot_checks(
            clusters, fraction=spot_check_fraction, seed=seed
        ),
    )
