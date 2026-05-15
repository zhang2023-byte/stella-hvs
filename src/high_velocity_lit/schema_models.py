"""Pydantic schema models for Stella JSON fact sources."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .schema_specs import (
    CATALOG_EXTRACTION_SCHEMA_VERSION,
    CATALOG_REVIEW_SCHEMA_VERSION,
    LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION,
)


class StrictModel(BaseModel):
    """Base model that rejects schema drift."""

    model_config = ConfigDict(extra="forbid")


class LinkSet(StrictModel):
    abs: str = ""
    pdf: str = ""


class ReviewPaper(StrictModel):
    arxiv_id: str
    title: str
    month: str
    source_note_json: str
    links: LinkSet


class ReviewSource(StrictModel):
    paper_dir: str
    audit_path: str
    source_dir: str
    tex_root: str
    source_available: bool


class ReviewMeta(StrictModel):
    status: Literal["reviewed", "partial", "needs_review", "source_missing"]
    reviewed_at: str
    reviewer: str
    summary: str


class ReviewTableSourceRef(StrictModel):
    path: str
    start_line: int
    end_line: int
    caption: str = ""
    label: str = ""


class ReviewColumn(StrictModel):
    name: str
    meaning: str
    unit_text: str = ""
    source_of_definition: str = ""
    confidence: float = 0.0


class InternalTable(StrictModel):
    id: str
    kind: str
    asset_type: str
    role_in_paper: str
    source_refs: list[ReviewTableSourceRef]
    columns: list[ReviewColumn]
    evidence: str
    comments: str


class ExternalResourceSourceRef(StrictModel):
    path: str
    start_line: int
    end_line: int
    context: str


class ExternalResource(StrictModel):
    id: str
    kind: str
    url: str
    local_path: str
    description: str
    source_refs: list[ExternalResourceSourceRef]
    evidence: str
    comments: str


class CatalogReviewRecord(StrictModel):
    schema_version: Literal["stella.article_data_assets.review.v1"]
    paper: ReviewPaper
    source: ReviewSource
    review: ReviewMeta
    internal_tables: list[InternalTable]
    external_resources: list[ExternalResource]


class ExtractionPaper(StrictModel):
    arxiv_id: str
    title: str
    month: str


class ExtractionReviewRef(StrictModel):
    path: str
    schema_version: str
    review_status: str


class ExtractionOptions(StrictModel):
    arxiv_id: str
    internal_table_id: str | None
    dry_run: bool
    overwrite: bool


class ExtractionSummary(StrictModel):
    internal_table_count: int
    work_count: int
    table_count: int
    success_count: int
    failed_count: int
    deferred_count: int
    file_count: int
    file_success_count: int
    file_failed_count: int


class ExtractionRun(StrictModel):
    run_id: str
    started_at: str
    tool: str
    options: ExtractionOptions
    summary: ExtractionSummary
    status: Literal["success", "partial", "failed", "skipped"]


class ExtractionFileSourceRef(StrictModel):
    path: str = ""
    start_line: int = 0
    end_line: int = 0
    caption: str = ""
    label: str = ""


class ExtractionFileRecord(StrictModel):
    id: str
    internal_table_id: str
    kind: str
    status: Literal["written", "skipped_existing", "would_write", "failed", "deferred"]
    source_ref: ExtractionFileSourceRef
    source_path: str
    excerpt_path: str
    sha256: str
    line_count: int
    error: str


class ExtractionColumn(StrictModel):
    name: str
    original_header: str
    unit_text: str
    data_type: str
    null_values: list[str]


class ConversionAttempt(StrictModel):
    method: str
    status: Literal["success", "failed", "skipped"]
    command: list[str]
    error: str
    artifacts: dict[str, str]


class ExtractionTableRecord(StrictModel):
    id: str
    internal_table_id: str
    status: Literal["success", "would_write", "skipped_existing", "failed", "deferred"]
    ecsv_path: str
    caption: str
    label: str
    row_count: int
    column_count: int
    environment: str
    header_rows: list[list[str]]
    columns: list[ExtractionColumn]
    warnings: list[str]
    error: str
    extraction_method: str
    conversion_attempts: list[ConversionAttempt]
    source_sha256: str


class CatalogExtractionRecord(StrictModel):
    schema_version: Literal["stella.article_data_assets.extraction.v2"]
    generated_at: str
    paper: ExtractionPaper
    review: ExtractionReviewRef
    run: ExtractionRun
    files: list[ExtractionFileRecord]
    tables: list[ExtractionTableRecord]


class HvsPaper(StrictModel):
    arxiv_id: str
    bibcode: str | None = None
    title: str
    month: str
    source_note_json: str
    links: LinkSet

    @field_validator("bibcode")
    @classmethod
    def non_empty_bibcode(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("bibcode must be non-empty when present")
        return value


class HvsInputs(StrictModel):
    paper_dir: str
    audit_path: str
    catalog_review_path: str
    catalog_extraction_path: str
    ecsv_paths: list[str]


class HvsExtractionMeta(StrictModel):
    status: Literal["candidates_found", "no_candidates", "partial", "needs_review", "source_missing"]
    extracted_at: str
    extractor: str
    summary: str


class TextSourceRef(StrictModel):
    kind: Literal["text"]
    path: str
    start_line: int
    end_line: int
    context: str


class EcsvCellSourceRef(StrictModel):
    kind: Literal["ecsv_cell"]
    path: str
    line: int
    column: str
    column_header: str
    raw_value: str


SourceRef = TextSourceRef | EcsvCellSourceRef


class MethodStep(StrictModel):
    id: str
    step_type: str
    summary: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)


class AliasRecord(StrictModel):
    value: str
    source_refs: list[SourceRef] = Field(default_factory=list)


class CandidateIdentifiers(StrictModel):
    primary: str
    paper_id: str = ""
    gaia_dr2_source_id: str = ""
    gaia_edr3_source_id: str = ""
    gaia_dr3_source_id: str = ""
    aliases: list[AliasRecord] = Field(default_factory=list)

    @field_validator("primary")
    @classmethod
    def primary_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("primary identifier is required")
        return value


class CandidateAssessment(StrictModel):
    summary: str
    candidate_status: Literal[
        "hvs_candidate",
        "unbound_candidate",
        "hyper_runaway_candidate",
        "escaping_galaxy_candidate",
    ]
    confidence: str
    source_refs: list[SourceRef]


class CandidateCitation(StrictModel):
    bibkey: str
    title: str = ""
    year: str = ""
    authors: list[str] = Field(default_factory=list)
    bibcode: str = ""
    doi: str = ""
    arxiv_id: str = ""
    source_refs: list[SourceRef]


class CandidateOrigin(StrictModel):
    origin_type: Literal["introduced_by_this_paper", "cited_from_literature"]
    paper_reassesses_unbound_status: bool
    source_refs: list[SourceRef]
    citation: CandidateCitation | None = None


class QuantityRecord(StrictModel):
    raw_value: str
    value: str
    error: str = ""
    lower_error: str = ""
    upper_error: str = ""
    unit: str = ""
    kind: str = ""
    description: str = ""
    source_refs: list[SourceRef]


class ObservedPhaseSpace(StrictModel):
    ra: QuantityRecord | None = None
    dec: QuantityRecord | None = None
    distance: QuantityRecord | None = None
    parallax: QuantityRecord | None = None
    proper_motion_ra: QuantityRecord | None = None
    proper_motion_dec: QuantityRecord | None = None
    radial_velocity: QuantityRecord | None = None


class DerivedKinematics(StrictModel):
    galactocentric_x: QuantityRecord | None = None
    galactocentric_y: QuantityRecord | None = None
    galactocentric_z: QuantityRecord | None = None
    galactocentric_vx: QuantityRecord | None = None
    galactocentric_vy: QuantityRecord | None = None
    galactocentric_vz: QuantityRecord | None = None
    tangential_velocity: QuantityRecord | None = None
    galactocentric_tangential_velocity: QuantityRecord | None = None
    total_velocity: QuantityRecord | None = None
    galactic_rest_frame_velocity: QuantityRecord | None = None
    escape_velocity: QuantityRecord | None = None
    escape_velocity_ratio: QuantityRecord | None = None


class Probabilities(StrictModel):
    bound_probability: QuantityRecord | None = None
    unbound_probability: QuantityRecord | None = None
    classification_probability: QuantityRecord | None = None


class CandidateCore(StrictModel):
    observed_phase_space: ObservedPhaseSpace
    derived_kinematics: DerivedKinematics
    probabilities: Probabilities


class ExtraQuantityRecord(QuantityRecord):
    name: str


class CandidateRecord(StrictModel):
    candidate_id: str
    identifiers: CandidateIdentifiers
    candidate_assessment: CandidateAssessment
    candidate_origin: CandidateOrigin
    method_chain_refs: list[str]
    core: CandidateCore
    extra: list[ExtraQuantityRecord]


class CandidateGroupConsidered(StrictModel):
    group_id: str
    description: str
    decision: str
    reason: str
    source_refs: list[SourceRef]


class LiteratureHvsCandidatesRecord(StrictModel):
    schema_version: Literal["stella.literature_hvs_candidates.v2"]
    generated_at: str
    paper: HvsPaper
    inputs: HvsInputs
    extraction: HvsExtractionMeta
    method_chain: list[MethodStep]
    candidates: list[CandidateRecord]
    candidate_groups_considered: list[CandidateGroupConsidered]


MODEL_BY_SCHEMA_VERSION: dict[str, type[StrictModel]] = {
    CATALOG_REVIEW_SCHEMA_VERSION: CatalogReviewRecord,
    CATALOG_EXTRACTION_SCHEMA_VERSION: CatalogExtractionRecord,
    LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION: LiteratureHvsCandidatesRecord,
}


def dump_template(model: StrictModel) -> dict[str, Any]:
    """Return a JSON-ready template, preserving empty strings and lists."""

    return model.model_dump(mode="json", exclude_none=True)
