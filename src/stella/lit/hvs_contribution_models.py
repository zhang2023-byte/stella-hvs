"""Pydantic models for the contribution-first HVS literature artifact.

The canonical unit is one current-paper/object contribution record: what the
current paper actually did to each identifiable HVS-related object. This
artifact family is parallel to ``literature_hvs_candidates`` (V6) and does
not replace it; V6 readers and writers stay unchanged.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Union

from pydantic import Field, model_validator

from .schema_models import StrictModel
from .schema_specs import (
    HVS_CONTRIBUTION_MEASUREMENT_FIELDS,
    HVS_CONTRIBUTION_TYPES,
    HVS_PAPER_BOUNDNESS_STATUSES,
)
from stella.schema_registry import require_schema

# Evidence locators point into the frozen current-paper source graph. The
# contribution contract owns its locator shapes (TeX line ranges and ECSV
# cells, with an optional raw-value fragment for direct numeric evidence);
# hydration detail such as resolved_text stays in the operational run
# artifacts, never in the canonical document.
class TextEvidence(StrictModel):
    kind: Literal["text"] = "text"
    path: str
    start_line: int
    end_line: int
    context: str = ""
    raw_value: str | None = None


class EcsvCellEvidence(StrictModel):
    kind: Literal["ecsv_cell"]
    path: str
    line: int
    column: str
    component_raw_value: str | None = None


ContributionEvidenceRef = Union[TextEvidence, EcsvCellEvidence]

CoordinateFormat = Literal[
    "decimal_degrees",
    "sexagesimal_hms",
    "sexagesimal_dms",
    "sexagesimal_colon",
]


class HvsContributionsSchema(StrictModel):
    name: Literal["literature_hvs_contributions"]
    version: Literal[1]


class ContributionPaper(StrictModel):
    arxiv_id: str


class ContributionInputs(StrictModel):
    source_run_id: str
    paper_context_sha256: str


class ContributionProduction(StrictModel):
    producer: Literal["hvs_contribution_extraction"]
    method_fingerprint: str
    component_hashes: dict[str, dict[str, str]] = Field(default_factory=dict)


class ContributionExtraction(StrictModel):
    status: Literal["complete", "partial", "failed"]
    roster_status: Literal["contributions_found", "no_contributions"] | None = None


class ContributionIdentifierItem(StrictModel):
    value: str
    evidence: list[ContributionEvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def value_required(self) -> "ContributionIdentifierItem":
        if not self.value.strip():
            raise ValueError("identifier value is required")
        return self


class ContributionIdentifiers(StrictModel):
    gaia_source_id: str = ""
    all: list[ContributionIdentifierItem] = Field(min_length=1)

    @model_validator(mode="after")
    def at_least_one_identifier(self) -> "ContributionIdentifiers":
        if not (
            self.gaia_source_id.strip()
            or any(item.value.strip() for item in self.all)
        ):
            raise ValueError(
                "contribution needs at least one paper-visible identifier"
            )
        return self


class PaperBoundness(StrictModel):
    """The current paper's own object-level boundness summary.

    The status is never derived from a probability, threshold, or a model
    chosen by Stella. ``not_assessed`` describes the absence of a new
    boundness assessment and needs no dedicated positive quote.
    """

    status: Literal[HVS_PAPER_BOUNDNESS_STATUSES]
    evidence: list[ContributionEvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def assessed_statuses_need_evidence(self) -> "PaperBoundness":
        if self.status != "not_assessed" and not self.evidence:
            raise ValueError(
                "paper_boundness evidence is required unless status is not_assessed"
            )
        return self


class MeasurementSource(StrictModel):
    kind: Literal["this_paper", "prior_work", "unclear"]
    paper_visible_citation: str | None = None
    bibkey: str | None = None
    citation_evidence: list[ContributionEvidenceRef] = Field(default_factory=list)


class MeasurementDirectEvidence(StrictModel):
    """One part-labelled direct source for one numeric component."""

    part: Literal["value", "error", "lower_error", "upper_error", "range_lower", "range_upper"]
    source: ContributionEvidenceRef


class MeasurementValue(StrictModel):
    """One explicitly object-attributed value of one structured field.

    ``condition_note`` records the potential, prior, method, epoch, or data
    release the value belongs to. ``paper_preferred`` is the paper's explicit
    preference only; null means the paper states none. ``source`` is
    provenance and is orthogonal to preference.
    """

    value: str | None = None
    error: str | None = None
    lower_error: str | None = None
    upper_error: str | None = None
    unit: str | None = None
    limit_kind: Literal["none", "lower_limit", "upper_limit", "range"] = "none"
    range_lower: str | None = None
    range_upper: str | None = None
    coordinate_format: CoordinateFormat | None = None
    condition_note: str
    paper_preferred: bool | None = Field(strict=True)
    source: MeasurementSource
    direct_evidence: list[MeasurementDirectEvidence] = Field(default_factory=list)
    context_evidence: list[TextEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def value_and_limit_shape(self) -> "MeasurementValue":
        if self.limit_kind == "range":
            if self.value is not None and self.value.strip():
                raise ValueError("range values keep value empty")
            if (
                self.range_lower is None
                or not self.range_lower.strip()
                or self.range_upper is None
                or not self.range_upper.strip()
            ):
                raise ValueError("range values need both range bounds")
        else:
            if self.value is None or not self.value.strip():
                raise ValueError("non-range values need a value")
            if (self.range_lower is not None and self.range_lower.strip()) or (
                self.range_upper is not None and self.range_upper.strip()
            ):
                raise ValueError("range bounds require limit_kind 'range'")
        return self


class MeasurementFieldGroup(StrictModel):
    """All reported values of one structured field, as an unordered multiset.

    Array order and any display-only ordinal are not canonical and are never
    scored. Values are deduplicated only when the complete record (value,
    condition, provenance, and evidence) is identical.
    """

    field: Literal[HVS_CONTRIBUTION_MEASUREMENT_FIELDS]
    values: list[MeasurementValue] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_exact_duplicate_values(self) -> "MeasurementFieldGroup":
        seen: set[str] = set()
        for item in self.values:
            key = json.dumps(
                item.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
            )
            if key in seen:
                raise ValueError(
                    f"duplicate measurement value in field {self.field}"
                )
            seen.add(key)
        return self


class MeasurementExtractionFailure(StrictModel):
    """Explicit delivery failure for the measurement stage of one object."""

    code: str
    detail: str = ""

    @model_validator(mode="after")
    def error_required(self) -> "MeasurementExtractionFailure":
        if not self.code.strip():
            raise ValueError("failure code is required")
        return self


class ObjectContribution(StrictModel):
    """One current-paper/object contribution record.

    ``record_id`` and ``display_name`` are program-generated after
    validation; they are never model-authored and never matching or scoring
    keys. A roster-success/measurement-failure object survives with its
    contribution identity intact, empty measurements, and
    ``measurement_extraction_failed``.
    """

    record_id: str
    display_name: str
    identifiers: ContributionIdentifiers
    contribution_type: Literal[HVS_CONTRIBUTION_TYPES]
    contribution_note: str
    contribution_evidence: list[ContributionEvidenceRef] = Field(min_length=1)
    paper_boundness: PaperBoundness
    measurement_status: Literal["measurements_complete", "measurement_extraction_failed"]
    measurements: list[MeasurementFieldGroup] = Field(default_factory=list)
    failure: MeasurementExtractionFailure | None = None

    @model_validator(mode="after")
    def check_contribution(self) -> "ObjectContribution":
        if not self.record_id.strip():
            raise ValueError("record_id is required")
        if not self.display_name.strip():
            raise ValueError("display_name is required")
        if not self.contribution_note.strip():
            raise ValueError("contribution_note is required")
        if self.contribution_type == "candidates_found" and self.paper_boundness.status in (
            "bound",
            "not_assessed",
        ):
            raise ValueError(
                "candidates_found cannot use paper_boundness bound or not_assessed"
            )
        fields = [group.field for group in self.measurements]
        if len(fields) != len(set(fields)):
            raise ValueError("each measurement field occurs at most once")
        if self.measurement_status == "measurements_complete":
            if self.failure is not None:
                raise ValueError(
                    "failure is only allowed when measurement extraction failed"
                )
        else:
            if self.measurements:
                raise ValueError(
                    "measurement_extraction_failed contributions emit no measurements"
                )
            if self.failure is None:
                raise ValueError(
                    "measurement_extraction_failed requires a failure object"
                )
        return self


class ReviewedExclusion(StrictModel):
    """Paper-level exclusion preserved for scientific transparency."""

    note: str
    evidence: list[ContributionEvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def note_required(self) -> "ReviewedExclusion":
        if not self.note.strip():
            raise ValueError("reviewed exclusion note is required")
        return self


class LiteratureHvsContributionsRecord(StrictModel):
    """Canonical contribution-first literature artifact (v1, pre-gold)."""

    schema_: HvsContributionsSchema = Field(alias="schema")
    generated_at: str
    paper: ContributionPaper
    inputs: ContributionInputs
    production: ContributionProduction
    extraction: ContributionExtraction
    reviewed_exclusions: list[ReviewedExclusion] = Field(default_factory=list)
    object_contributions: list[ObjectContribution] = Field(default_factory=list)

    @model_validator(mode="after")
    def roster_status_matches_contributions(self) -> "LiteratureHvsContributionsRecord":
        roster_status = self.extraction.roster_status
        if self.extraction.status == "complete" and roster_status is None:
            raise ValueError("a complete extraction must state its roster_status")
        if roster_status == "contributions_found" and not self.object_contributions:
            raise ValueError(
                "roster_status contributions_found requires object contributions"
            )
        if roster_status == "no_contributions" and self.object_contributions:
            raise ValueError(
                "roster_status no_contributions forbids object contributions"
            )
        if roster_status is None and self.object_contributions:
            raise ValueError(
                "contributions require a successful roster_status"
            )
        record_ids = [item.record_id for item in self.object_contributions]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("record_id values must be unique within the paper")
        return self


def validate_literature_hvs_contributions_document(payload: Any) -> StrictModel:
    """Validate a literature_hvs_contributions document."""

    require_schema(payload, "literature_hvs_contributions")
    return LiteratureHvsContributionsRecord.model_validate(payload)
