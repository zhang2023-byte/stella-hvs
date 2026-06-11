"""Expert gold-annotation schema and upgrade logic for the benchmark.

The expert's primary artifact is a slim annotation YAML (see
``benchmark/templates/``) capturing only judgments, at exactly the
granularity the benchmark scores: candidate identities (L1), normalized
quantity values (L2), evidence locations (L3), and method facts plus the
step-type checklist (L4). The upgrade step validates it and emits a JSON
document under ``benchmark/gold/``.

Gold deliberately does not impersonate a full extraction record: experts
annotate from the PDF (the normative evidence source, see AGENTS.md), so
their evidence is a PDF locator plus an optional verbatim quote — it cannot
honestly inhabit the extraction schema's TeX/ECSV source refs, and experts
state method facts rather than wiring a step DAG. Every controlled
vocabulary below is imported from the frozen extraction schema, so the two
sides stay comparable by construction.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from stella.lit.schema_models import (
    BoundAssessment,
    DerivedKinematics,
    ObservedPhaseSpace,
    StrictModel,
)
from stella.lit.schema_specs import (
    LITERATURE_HVS_LIMIT_KINDS,
    LITERATURE_HVS_METHOD_PARAMETER_NAMES,
    LITERATURE_HVS_METHOD_STEP_TYPES,
)

GOLD_SCHEMA_VERSION = "stella.benchmark_gold_annotation.v0.1"

# Quantity fields the benchmark scores at L2, derived from the frozen
# extraction models so the vocabulary cannot drift.
SCORED_QUANTITY_FIELDS: tuple[str, ...] = (
    tuple(f"observed_phase_space.{name}" for name in ObservedPhaseSpace.model_fields)
    + tuple(f"derived_kinematics.{name}" for name in DerivedKinematics.model_fields)
    + tuple(f"bound_assessment.{name}" for name in BoundAssessment.model_fields)
)

GOLD_BOUND_CLAIMS = (
    "unbound",
    "likely_unbound",
    "possibly_unbound",
    "escaping",
    "not_reported",
)
GOLD_ORIGIN_TYPES = ("introduced_by_this_paper", "cited_from_literature")


class GoldEvidence(StrictModel):
    """Where in the PDF the expert saw it."""

    location: str
    quote: str = ""

    @model_validator(mode="after")
    def location_required(self) -> "GoldEvidence":
        if not self.location.strip():
            raise ValueError("evidence location is required")
        return self


class GoldQuantity(StrictModel):
    field: str
    value: str = ""
    error: str = ""
    lower_error: str = ""
    upper_error: str = ""
    unit: str = ""
    limit_kind: str = ""
    range_lower: str = ""
    range_upper: str = ""
    evidence: list[GoldEvidence] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def check_vocabulary_and_limits(self) -> "GoldQuantity":
        if self.field not in SCORED_QUANTITY_FIELDS:
            raise ValueError(f"unknown scored quantity field: {self.field!r}")
        if self.limit_kind not in LITERATURE_HVS_LIMIT_KINDS:
            raise ValueError(f"unknown limit_kind: {self.limit_kind!r}")
        # Mirrors the frozen validator's limit semantics.
        if self.limit_kind == "range":
            if self.value.strip():
                raise ValueError("range quantities keep value empty")
            if not (self.range_lower.strip() and self.range_upper.strip()):
                raise ValueError("range quantities need both range bounds")
        else:
            if self.range_lower.strip() or self.range_upper.strip():
                raise ValueError("range bounds require limit_kind 'range'")
            if not self.value.strip():
                raise ValueError("non-range quantities need a value")
        return self


class GoldCandidate(StrictModel):
    record_id: str
    names: list[str] = Field(default_factory=list)
    gaia_source_id: str = ""
    ra_deg: float | None = None
    dec_deg: float | None = None
    pm_ra_masyr: float | None = None
    pm_dec_masyr: float | None = None
    epoch_year: float | None = None
    galactic_bound_claim: str = "not_reported"
    origin_type: str = ""
    quantities: list[GoldQuantity] = Field(default_factory=list)
    evidence: list[GoldEvidence] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def check_candidate(self) -> "GoldCandidate":
        if not self.record_id.strip():
            raise ValueError("record_id is required")
        if not (self.names or self.gaia_source_id.strip()):
            raise ValueError(
                "candidate needs at least one name or a gaia_source_id"
            )
        if self.galactic_bound_claim not in GOLD_BOUND_CLAIMS:
            raise ValueError(
                f"unknown galactic_bound_claim: {self.galactic_bound_claim!r}"
            )
        if self.origin_type not in GOLD_ORIGIN_TYPES:
            raise ValueError(f"unknown origin_type: {self.origin_type!r}")
        if not self.evidence:
            raise ValueError("candidate-level evidence is required")
        return self


class GoldMethodFact(StrictModel):
    name: str
    status: Literal["reported", "not_reported"]
    value: str = ""
    unit: str = ""
    evidence: list[GoldEvidence] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def check_fact(self) -> "GoldMethodFact":
        if self.name not in LITERATURE_HVS_METHOD_PARAMETER_NAMES:
            raise ValueError(f"unknown method fact name: {self.name!r}")
        if self.status == "reported" and not self.value.strip():
            raise ValueError("reported method facts need a value")
        if self.status == "not_reported" and self.value.strip():
            raise ValueError("not_reported method facts keep value empty")
        return self


class GoldAnnotation(StrictModel):
    schema_version: Literal["stella.benchmark_gold_annotation.v0.1"]
    arxiv_id: str
    annotator: str
    annotated_at: str
    guideline_version: str
    evidence_basis: Literal["pdf"] = "pdf"
    status: Literal["candidates_found", "no_candidates"]
    candidates: list[GoldCandidate] = Field(default_factory=list)
    method_facts: list[GoldMethodFact] = Field(default_factory=list)
    step_types_present: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def check_document(self) -> "GoldAnnotation":
        for name in ("arxiv_id", "annotator", "annotated_at", "guideline_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        if self.status == "no_candidates" and self.candidates:
            raise ValueError("no_candidates documents must not list candidates")
        if self.status == "candidates_found" and not self.candidates:
            raise ValueError("candidates_found documents need candidates")
        record_ids = [candidate.record_id for candidate in self.candidates]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("candidate record_id values must be unique")
        unknown = [
            step
            for step in self.step_types_present
            if step not in LITERATURE_HVS_METHOD_STEP_TYPES
        ]
        if unknown:
            raise ValueError(f"unknown step types: {unknown}")
        if len(self.step_types_present) != len(set(self.step_types_present)):
            raise ValueError("step_types_present must be unique")
        fact_names = [fact.name for fact in self.method_facts]
        duplicates = {name for name in fact_names if fact_names.count(name) > 1}
        # "other" may repeat; the controlled names may not.
        duplicates.discard("other")
        if duplicates:
            raise ValueError(f"duplicate method facts: {sorted(duplicates)}")
        return self


def upgrade_annotation(payload: dict) -> dict:
    """Validate a parsed annotation YAML and return the JSON-ready gold doc."""

    annotation = GoldAnnotation.model_validate(payload)
    return annotation.model_dump(mode="json")
