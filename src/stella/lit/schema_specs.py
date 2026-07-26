"""Lightweight schema facts shared by generators, validators, and skill docs."""

from __future__ import annotations

from dataclasses import dataclass

from stella.schema_registry import schema_ref


CATALOG_REVIEW_SCHEMA = schema_ref("article_data_assets.review")
CATALOG_EXTRACTION_SCHEMA = schema_ref("article_data_assets.extraction")
CATALOG_INVENTORY_SCHEMA = schema_ref("article_data_assets.inventory")
CATALOG_INDEX_SCHEMA = schema_ref("article_data_assets.index")
LITERATURE_HVS_CANDIDATES_SCHEMA = schema_ref("literature_hvs_candidates")
# The v0.1 corpus (validated historical data) stays readable without
# re-extraction; readers dispatch on the declared version. v0.2 landed in
# two same-day batches (2026-07-06) before any extraction instantiated it.
LITERATURE_HVS_CANDIDATES_READ_V1_SCHEMA = schema_ref("literature_hvs_candidates", 1)
LITERATURE_HVS_CANDIDATES_READ_V2_SCHEMA = schema_ref("literature_hvs_candidates", 2)
LITERATURE_HVS_CANDIDATES_INDEX_SCHEMA = schema_ref("literature_hvs_candidates.index")

CATALOG_REVIEW_STATUSES = ("reviewed", "partial", "needs_review", "source_missing")
CATALOG_EXTRACTION_RUN_STATUSES = ("success", "partial", "failed", "skipped")
CATALOG_EXTRACTION_FILE_STATUSES = ("written", "skipped_existing", "would_write", "failed", "deferred")
CATALOG_EXTRACTION_TABLE_STATUSES = ("success", "would_write", "skipped_existing", "failed", "deferred")
LITERATURE_HVS_EXTRACTION_STATUSES = (
    "candidates_found",
    "no_candidates",
    "partial",
    "needs_review",
    "source_missing",
)
LITERATURE_HVS_PAPER_LABELS = (
    "hvs_candidate",
    "hyper_runaway_candidate",
    "escaping_star",
    "unbound_star",
    "high_velocity_star",
    "runaway_candidate",
    "candidate_group_member",
    "other",
)
LITERATURE_HVS_GALACTIC_BOUND_CLAIMS = (
    "unbound",
    "likely_unbound",
    "possibly_unbound",
    "escaping",
    "not_reported",
)
LITERATURE_HVS_INCLUSION_BASES = (
    "explicit_candidate_text",
    "explicit_unbound_text",
    "cited_prior_candidate_reassessed",
    "candidate_table_with_text_anchor",
)
LITERATURE_HVS_EXTRACTION_CONFIDENCE = (
    "high",
    "medium",
    "low",
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
    "solar_position_and_motion",
    "galactic_potential_model",
    "escape_or_bound_assessment",
    "orbit_integration",
    "origin_assessment",
    "candidate_classification",
    "follow_up_validation",
    "reported_value_adoption",
    "other",
)
LITERATURE_HVS_METHOD_PARAMETER_NAMES = (
    "R0",
    "z0",
    "v_circ_sun",
    "solar_motion_u",
    "solar_motion_v",
    "solar_motion_w",
    "potential_name",
    "escape_velocity_definition",
    "other",
)
LITERATURE_HVS_LIMIT_KINDS = (
    "",
    "lower_limit",
    "upper_limit",
    "range",
)


@dataclass(frozen=True)
class SchemaSpec:
    """Minimal facts that must stay synchronized with skill schema docs."""

    name: str
    version: int
    reference_path: str
    top_level_fields: tuple[str, ...]
    status_values: dict[str, tuple[str, ...]]


CATALOG_REVIEW_SPEC = SchemaSpec(
    name=CATALOG_REVIEW_SCHEMA["name"],
    version=CATALOG_REVIEW_SCHEMA["version"],
    reference_path="skills/hvs-catalog-review/references/schema.md",
    top_level_fields=(
        "schema",
        "paper",
        "source",
        "review",
        "internal_tables",
        "external_resources",
    ),
    status_values={"review.status": CATALOG_REVIEW_STATUSES},
)

CATALOG_EXTRACTION_SPEC = SchemaSpec(
    name=CATALOG_EXTRACTION_SCHEMA["name"],
    version=CATALOG_EXTRACTION_SCHEMA["version"],
    reference_path="skills/hvs-catalog-extraction/references/schema.md",
    top_level_fields=(
        "schema",
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
    name=LITERATURE_HVS_CANDIDATES_SCHEMA["name"],
    version=LITERATURE_HVS_CANDIDATES_SCHEMA["version"],
    reference_path="skills/hvs-candidates-extraction/references/schema.md",
    top_level_fields=(
        "schema",
        "generated_at",
        "paper",
        "inputs",
        "production",
        "extraction",
        "roster",
        "candidates",
    ),
    status_values={
        "extraction.status": ("complete", "partial", "failed"),
        "candidates[].field_status": (
            "fields_complete",
            "field_extraction_failed",
        ),
        "candidate_origin.origin_type": LITERATURE_HVS_CANDIDATE_ORIGIN_TYPES,
    },
)

SKILL_SCHEMA_SPECS = (
    CATALOG_REVIEW_SPEC,
    CATALOG_EXTRACTION_SPEC,
    LITERATURE_HVS_CANDIDATES_SPEC,
)
