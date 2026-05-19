"""Lightweight schema facts shared by generators, validators, and skill docs."""

from __future__ import annotations

from dataclasses import dataclass


CATALOG_REVIEW_SCHEMA_VERSION = "stella.article_data_assets.review.v1"
CATALOG_EXTRACTION_SCHEMA_VERSION = "stella.article_data_assets.extraction.v2"
CATALOG_INVENTORY_SCHEMA_VERSION = "stella.article_data_assets.inventory.v1"
CATALOG_INDEX_SCHEMA_VERSION = "stella.article_data_assets.index.v1"
LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION = "stella.literature_hvs_candidates.v5"
LITERATURE_HVS_CANDIDATES_INDEX_SCHEMA_VERSION = "stella.literature_hvs_candidates.index.v2"

CATALOG_REVIEW_STATUSES = ("reviewed", "partial", "needs_review", "source_missing")
CATALOG_EXTRACTION_RUN_STATUSES = ("success", "partial", "failed", "skipped")
CATALOG_EXTRACTION_FILE_STATUSES = ("written", "skipped_existing", "would_write", "failed", "deferred")
CATALOG_EXTRACTION_TABLE_STATUSES = ("success", "would_write", "skipped_existing", "failed", "deferred")
LITERATURE_HVS_CANDIDATE_STATUSES = (
    "candidates_found",
    "no_candidates",
    "partial",
    "needs_review",
    "source_missing",
)
LITERATURE_HVS_CANDIDATE_ASSESSMENT_STATUSES = (
    "hvs_candidate",
    "unbound_candidate",
    "hyper_runaway_candidate",
    "escaping_galaxy_candidate",
)
LITERATURE_HVS_CANDIDATE_ORIGIN_TYPES = (
    "introduced_by_this_paper",
    "cited_from_literature",
)
LITERATURE_HVS_METHOD_STEP_TYPES = (
    "input_catalog",
    "sample_selection",
    "cross_match",
    "quality_filter",
    "astrometric_calibration",
    "distance_estimation",
    "radial_velocity_measurement",
    "stellar_parameter_inference",
    "photometric_or_sed_modeling",
    "velocity_calculation",
    "galactic_potential_model",
    "escape_or_bound_assessment",
    "orbit_integration",
    "origin_assessment",
    "candidate_classification",
    "follow_up_validation",
    "reported_value_adoption",
    "other",
)


@dataclass(frozen=True)
class SchemaSpec:
    """Minimal facts that must stay synchronized with skill schema docs."""

    version: str
    reference_path: str
    top_level_fields: tuple[str, ...]
    status_values: dict[str, tuple[str, ...]]


CATALOG_REVIEW_SPEC = SchemaSpec(
    version=CATALOG_REVIEW_SCHEMA_VERSION,
    reference_path="skills/hvs-catalog-review/references/schema.md",
    top_level_fields=(
        "schema_version",
        "paper",
        "source",
        "review",
        "internal_tables",
        "external_resources",
    ),
    status_values={"review.status": CATALOG_REVIEW_STATUSES},
)

CATALOG_EXTRACTION_SPEC = SchemaSpec(
    version=CATALOG_EXTRACTION_SCHEMA_VERSION,
    reference_path="skills/hvs-catalog-extraction/references/schema.md",
    top_level_fields=(
        "schema_version",
        "generated_at",
        "paper",
        "review",
        "run",
        "files",
        "tables",
    ),
    status_values={
        "run.status": CATALOG_EXTRACTION_RUN_STATUSES,
        "files[].status": CATALOG_EXTRACTION_FILE_STATUSES,
        "tables[].status": CATALOG_EXTRACTION_TABLE_STATUSES,
    },
)

LITERATURE_HVS_CANDIDATES_SPEC = SchemaSpec(
    version=LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION,
    reference_path="skills/hvs-candidates-extraction/references/schema.md",
    top_level_fields=(
        "schema_version",
        "generated_at",
        "paper",
        "inputs",
        "extraction",
        "method_chain",
        "candidates",
        "candidate_groups_considered",
    ),
    status_values={
        "extraction.status": LITERATURE_HVS_CANDIDATE_STATUSES,
        "candidate_assessment.candidate_status": LITERATURE_HVS_CANDIDATE_ASSESSMENT_STATUSES,
        "candidate_origin.origin_type": LITERATURE_HVS_CANDIDATE_ORIGIN_TYPES,
        "method_chain.step_type": LITERATURE_HVS_METHOD_STEP_TYPES,
    },
)

SKILL_SCHEMA_SPECS = (
    CATALOG_REVIEW_SPEC,
    CATALOG_EXTRACTION_SPEC,
    LITERATURE_HVS_CANDIDATES_SPEC,
)
