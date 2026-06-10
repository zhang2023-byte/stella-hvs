"""Pydantic schema models for Stella benchmark JSON sources."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from high_velocity_lit.schema_models import StrictModel

BENCHMARK_MANIFEST_SCHEMA_VERSION = "stella.hvs_benchmark.manifest.v1"
BENCHMARK_VARIANT_META_SCHEMA_VERSION = "stella.hvs_benchmark.variant_meta.v1"
BENCHMARK_ALIGNMENT_SCHEMA_VERSION = "stella.hvs_benchmark.alignment.v1"
BENCHMARK_ADJUDICATION_SCHEMA_VERSION = "stella.hvs_benchmark.adjudication.v1"
BENCHMARK_GOLD_PROVENANCE_SCHEMA_VERSION = "stella.hvs_benchmark.gold_provenance.v1"
BENCHMARK_REPORT_SCHEMA_VERSION = "stella.hvs_benchmark.report.v1"


class ManifestSelection(StrictModel):
    size: int
    strata_spec: str
    source_index_path: str
    source_index_generated_at: str = ""


class ManifestPaper(StrictModel):
    arxiv_id: str
    year: str
    stratum: str
    canonical_status: str
    canonical_candidate_count: int
    sample_round: int = 1


class BenchmarkManifest(StrictModel):
    schema_version: Literal["stella.hvs_benchmark.manifest.v1"]
    created_at: str
    seed: int
    frozen: bool
    selection: ManifestSelection
    papers: list[ManifestPaper]

    @field_validator("papers")
    @classmethod
    def unique_arxiv_ids(cls, value: list[ManifestPaper]) -> list[ManifestPaper]:
        seen: set[str] = set()
        for paper in value:
            if paper.arxiv_id in seen:
                raise ValueError(f"duplicate arxiv_id in manifest: {paper.arxiv_id}")
            seen.add(paper.arxiv_id)
        return value


class VariantMeta(StrictModel):
    schema_version: Literal["stella.hvs_benchmark.variant_meta.v1"]
    variant_id: str
    kind: Literal["canonical_snapshot", "fresh_rerun"]
    model: str
    created_at: str
    skill_digest: str = ""
    notes: str = ""

    @field_validator("variant_id")
    @classmethod
    def variant_id_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("variant_id is required")
        return value


class ResolvedTextEvidence(StrictModel):
    kind: Literal["text"]
    path: str
    start_line: int
    end_line: int
    context: str = ""
    lines: list[str] = Field(default_factory=list)
    error: str = ""


class ResolvedEcsvEvidence(StrictModel):
    kind: Literal["ecsv_cell"]
    path: str
    line: int
    column: str
    column_header: str
    raw_value: str
    row_cells: dict[str, str] = Field(default_factory=dict)
    error: str = ""


ResolvedEvidence = ResolvedTextEvidence | ResolvedEcsvEvidence


class AlignmentPaperInfo(StrictModel):
    title: str = ""
    month: str = ""
    links: dict[str, str] = Field(default_factory=dict)


class AlignmentVariantSummary(StrictModel):
    variant_id: str
    status: str
    candidate_count: int


class AlignmentPaperStatus(StrictModel):
    values: dict[str, str]
    agreement: bool


class IdentifierSummary(StrictModel):
    gaia_source_id: str = ""
    display: str = ""
    all_values: list[str] = Field(default_factory=list)


class AlignmentField(StrictModel):
    field_path: str
    kind: Literal[
        "categorical",
        "boolean",
        "label_set",
        "identifier",
        "identifier_set",
        "quantity",
        "coordinate",
    ]
    values: dict[str, Any]
    agreement: bool
    evidence: dict[str, list[ResolvedEvidence]] = Field(default_factory=dict)


class AlignmentCluster(StrictModel):
    cluster_id: str
    matched_by: Literal["gaia_source_id", "identifier_overlap", "unmatched"]
    members: dict[str, str]
    missing_in: list[str] = Field(default_factory=list)
    conflict: bool = False
    identifier_summary: IdentifierSummary
    fields: list[AlignmentField]


class UncoveredEcsvRow(StrictModel):
    path: str
    line: int
    identifier_guess: str = ""
    row_preview: str = ""


class RecallAssists(StrictModel):
    uncovered_ecsv_rows: list[UncoveredEcsvRow] = Field(default_factory=list)


class AlignmentRecord(StrictModel):
    schema_version: Literal["stella.hvs_benchmark.alignment.v1"]
    arxiv_id: str
    generated_at: str
    alignment_digest: str
    paper: AlignmentPaperInfo
    variants: list[AlignmentVariantSummary]
    paper_status: AlignmentPaperStatus
    clusters: list[AlignmentCluster]
    recall_assists: RecallAssists = Field(default_factory=RecallAssists)
    consensus_spot_checks: list[str] = Field(default_factory=list)


class ExpertIdentity(StrictModel):
    id: str
    name: str = ""

    @field_validator("id")
    @classmethod
    def expert_id_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("expert id is required")
        return value


class PaperStatusVerdict(StrictModel):
    verdict: Literal["accept", "fix"]
    gold_status: Literal[
        "candidates_found", "no_candidates", "partial", "needs_review", "source_missing"
    ]
    rationale: str = ""
    decided_at: str = ""


class AdjudicationItem(StrictModel):
    item_id: str
    kind: Literal["candidate_presence", "field_value", "candidate_addition"]
    cluster_id: str = ""
    field_path: str = ""
    verdict: Literal["accept", "accept_variant", "fix", "reject", "reject_field", "add_missing"]
    base_variant: str = ""
    accepted_from_variant: str = ""
    fixed_payload: dict[str, Any] | None = None
    added_payload: dict[str, Any] | None = None
    rationale: str = ""
    decided_at: str = ""

    @field_validator("item_id")
    @classmethod
    def item_id_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("item_id is required")
        return value


class AdjudicationRecord(StrictModel):
    schema_version: Literal["stella.hvs_benchmark.adjudication.v1"]
    arxiv_id: str
    alignment_digest: str
    expert: ExpertIdentity
    updated_at: str
    paper_status_verdict: PaperStatusVerdict | None = None
    items: list[AdjudicationItem]

    @field_validator("items")
    @classmethod
    def unique_item_ids(cls, value: list[AdjudicationItem]) -> list[AdjudicationItem]:
        seen: set[str] = set()
        for item in value:
            if item.item_id in seen:
                raise ValueError(f"duplicate item_id in adjudication: {item.item_id}")
            seen.add(item.item_id)
        return value


class GoldProvenanceEntry(StrictModel):
    target: str
    source: Literal["verdict", "auto_consensus"]
    item_id: str = ""
    base_variant: str = ""


class GoldProvenance(StrictModel):
    schema_version: Literal["stella.hvs_benchmark.gold_provenance.v1"]
    arxiv_id: str
    generated_at: str
    adjudication_path: str
    alignment_digest: str
    expert: ExpertIdentity
    entries: list[GoldProvenanceEntry]


class BenchmarkReport(StrictModel):
    schema_version: Literal["stella.hvs_benchmark.report.v1"]
    generated_at: str
    gold_dir: str
    variant_ids: list[str]
    paper_ids: list[str]
    tolerances: dict[str, Any]
    detection: dict[str, Any]
    paper_status: dict[str, Any]
    fields: dict[str, Any]
    adjudication_stats: dict[str, Any] = Field(default_factory=dict)
