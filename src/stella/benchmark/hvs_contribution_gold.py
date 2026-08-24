"""Expert gold-annotation schema for contribution-first HVS benchmarking.

The gold record mirrors the scientific shape of
``literature_hvs_contributions``. Its normative scientific evidence is the
paper PDF, so every evidence locator is a PDF location plus an optional
verbatim quote (reusing the V6 gold evidence discipline). The original
50-paper migration is AI-assisted but expert-approved at paper level; the
production extractor under evaluation is never a gold input.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from stella.benchmark.gold import (
    GoldEvidence,
    GoldQuantity,
    validate_annotator_handle,
)
from stella.lit.identity import normalize_name
from stella.lit.hvs_contribution_models import (
    derived_identifier_display_name,
    validate_contribution_probability_representation,
)
from stella.lit.schema_models import StrictModel
from stella.lit.schema_specs import (
    HVS_CONTRIBUTION_TYPES,
    HVS_PAPER_BOUNDNESS_STATUSES,
    HVS_CONTRIBUTION_QUANTITIES,
)


class HvsContributionGoldSchema(StrictModel):
    name: Literal["benchmark.hvs_contribution_annotation"]
    version: Literal[1]


CONTRIBUTION_MIGRATION_PROTOCOL = "contribution_migration_ai_assisted_v1"


class GoldContributionAnnotationProcess(StrictModel):
    """Auditable creation process for one expert-approved gold annotation."""

    protocol: str
    preannotation_agent: str = ""
    preannotation_model: str = ""
    reconciliation_agent: str = ""
    reconciliation_model: str = ""
    expert_review_scope: Literal["paper_level"] = "paper_level"
    process_note: str = ""

    @model_validator(mode="after")
    def migration_process_is_complete(self) -> "GoldContributionAnnotationProcess":
        if not self.protocol.strip():
            raise ValueError("annotation_process.protocol is required")
        if self.protocol == CONTRIBUTION_MIGRATION_PROTOCOL:
            for field in (
                "preannotation_agent",
                "preannotation_model",
                "reconciliation_agent",
                "reconciliation_model",
            ):
                if not getattr(self, field).strip():
                    raise ValueError(
                        f"annotation_process.{field} is required for the migration protocol"
                    )
        return self


class GoldReviewedExclusion(StrictModel):
    reason: str
    evidence: list[GoldEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def reason_required(self) -> "GoldReviewedExclusion":
        if not self.reason.strip():
            raise ValueError("reviewed exclusion reason is required")
        return self


class GoldIdentifier(StrictModel):
    value: str
    evidence: list[GoldEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def value_required(self) -> "GoldIdentifier":
        if not self.value.strip():
            raise ValueError("identifier value is required")
        return self


class GoldReportedValue(StrictModel):
    value: str = ""
    error: str = ""
    lower_error: str = ""
    upper_error: str = ""
    unit: str = ""
    limit_kind: Literal["none", "lower_limit", "upper_limit", "range"] = "none"
    range_lower: str = ""
    range_upper: str = ""
    coordinate_format: (
        Literal[
            "decimal_degrees",
            "sexagesimal_hms",
            "sexagesimal_dms",
            "sexagesimal_colon",
        ]
        | None
    ) = None
    condition: str = ""
    paper_preferred: bool | None = Field(strict=True)
    source: Literal["this_paper", "prior_work", "unclear"]
    evidence: list[GoldEvidence] = Field(min_length=1)
    context_evidence: list[GoldEvidence] = Field(default_factory=list)
    source_note: str = ""

    @model_validator(mode="after")
    def value_and_limit_shape(self) -> "GoldReportedValue":
        if self.error.strip() and (self.lower_error.strip() or self.upper_error.strip()):
            raise ValueError("symmetric and asymmetric uncertainties cannot be mixed")
        if bool(self.lower_error.strip()) != bool(self.upper_error.strip()):
            raise ValueError("asymmetric uncertainty requires both lower and upper errors")
        if self.limit_kind == "range":
            if self.value.strip():
                raise ValueError("range values keep value empty")
            if not (self.range_lower.strip() and self.range_upper.strip()):
                raise ValueError("range values need both range bounds")
        else:
            if not self.value.strip():
                raise ValueError("non-range values need a value")
            if self.range_lower.strip() or self.range_upper.strip():
                raise ValueError("range bounds require limit_kind 'range'")
        return self


class GoldQuantityGroup(StrictModel):
    quantity: str
    values: list[GoldReportedValue] = Field(min_length=1)

    @model_validator(mode="after")
    def check_group(self) -> "GoldQuantityGroup":
        if self.quantity not in HVS_CONTRIBUTION_QUANTITIES:
            raise ValueError(f"unknown structured quantity: {self.quantity!r}")
        seen: set[str] = set()
        for item in self.values:
            GoldQuantity.model_validate(
                {
                    "field": self.quantity,
                    "value": item.value,
                    "error": item.error,
                    "lower_error": item.lower_error,
                    "upper_error": item.upper_error,
                    "unit": item.unit,
                    "limit_kind": "" if item.limit_kind == "none" else item.limit_kind,
                    "range_lower": item.range_lower,
                    "range_upper": item.range_upper,
                    "evidence": [entry.model_dump(mode="json") for entry in item.evidence],
                }
            )
            coordinate_quantity = self.quantity in (
                "observed_phase_space.ra",
                "observed_phase_space.dec",
            )
            if coordinate_quantity and item.coordinate_format is None:
                raise ValueError("coordinate values require coordinate_format")
            if not coordinate_quantity and item.coordinate_format is not None:
                raise ValueError("coordinate_format is only valid for RA and Dec")
            if self.quantity.endswith(".ra") and item.coordinate_format == "sexagesimal_dms":
                raise ValueError("RA cannot use sexagesimal_dms")
            if self.quantity.endswith(".dec") and item.coordinate_format == "sexagesimal_hms":
                raise ValueError("Dec cannot use sexagesimal_hms")
            validate_contribution_probability_representation(
                self.quantity,
                unit=item.unit,
                value=item.value,
                range_lower=item.range_lower,
                range_upper=item.range_upper,
            )
            key = json.dumps(
                item.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
            )
            if key in seen:
                raise ValueError(
                    f"duplicate reported value for quantity {self.quantity}"
                )
            seen.add(key)
        return self


class GoldPaperBoundness(StrictModel):
    status: Literal[HVS_PAPER_BOUNDNESS_STATUSES]
    evidence: list[GoldEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def assessed_statuses_need_evidence(self) -> "GoldPaperBoundness":
        if self.status != "not_assessed" and not self.evidence:
            raise ValueError(
                "paper_boundness evidence is required unless status is not_assessed"
            )
        return self


class GoldContribution(StrictModel):
    identifiers: list[GoldIdentifier] = Field(min_length=1)
    contribution_type: Literal[HVS_CONTRIBUTION_TYPES]
    contribution_summary: str
    contribution_evidence: list[GoldEvidence] = Field(min_length=1)
    paper_boundness: GoldPaperBoundness
    quantities: list[GoldQuantityGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_contribution(self) -> "GoldContribution":
        normalized_identifiers = [normalize_name(item.value) for item in self.identifiers]
        if len(normalized_identifiers) != len(set(normalized_identifiers)):
            raise ValueError("identifiers must be unique within one contribution")
        if not self.contribution_summary.strip():
            raise ValueError("contribution_summary is required")
        if self.contribution_type == "candidates_found" and self.paper_boundness.status in (
            "bound",
            "not_assessed",
        ):
            raise ValueError(
                "candidates_found cannot use paper_boundness bound or not_assessed"
            )
        quantities = [group.quantity for group in self.quantities]
        if len(quantities) != len(set(quantities)):
            raise ValueError("each structured quantity occurs at most once")
        return self


class HvsContributionGoldAnnotation(StrictModel):
    schema_: HvsContributionGoldSchema = Field(alias="schema")
    arxiv_id: str
    annotator: str
    annotated_at: str
    guideline_version: str
    evidence_basis: Literal["pdf"] = "pdf"
    annotation_process: GoldContributionAnnotationProcess
    canary: str = ""
    status: Literal["contributions_found", "no_contributions"]
    contributions: list[GoldContribution] = Field(default_factory=list)
    reviewed_exclusions: list[GoldReviewedExclusion] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_document(self) -> "HvsContributionGoldAnnotation":
        for name in ("arxiv_id", "annotator", "annotated_at", "guideline_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        validate_annotator_handle(self.annotator)
        if self.status == "no_contributions" and self.contributions:
            raise ValueError(
                "no_contributions documents must not list contributions"
            )
        if self.status == "contributions_found" and not self.contributions:
            raise ValueError(
                "contributions_found documents need contributions"
            )
        first_owner: dict[str, int] = {}
        for contribution_index, contribution in enumerate(self.contributions):
            for identifier in contribution.identifiers:
                key = normalize_name(identifier.value)
                if key in first_owner:
                    raise ValueError(
                        "identifier values must be unique across contributions: "
                        f"{identifier.value!r}"
                    )
                first_owner[key] = contribution_index
        return self


def _omit_empty_annotation_values(value: object) -> object:
    """Recursively remove empty optional fields from a formal gold document."""

    if isinstance(value, dict):
        compact = {
            key: _omit_empty_annotation_values(item)
            for key, item in value.items()
        }
        return {
            key: item
            for key, item in compact.items()
            if not (
                item is None
                and key != "paper_preferred"
                or
                isinstance(item, str)
                and not item
                or isinstance(item, (dict, list))
                and not item
            )
        }
    if isinstance(value, list):
        return [_omit_empty_annotation_values(item) for item in value]
    return value


def compact_contribution_annotation_document(
    annotation: HvsContributionGoldAnnotation,
) -> dict:
    """Serialize a validated annotation without empty optional fields."""

    document = _omit_empty_annotation_values(
        annotation.model_dump(mode="json", by_alias=True)
    )
    if not isinstance(document, dict):
        raise TypeError("gold annotation document must be a mapping")
    return document


def contribution_annotation_canary(document: dict) -> str:
    """Return a deterministic leak-audit marker for a formal gold JSON twin."""

    payload = dict(document)
    payload.pop("canary", None)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return f"stella-contribution-gold-canary-v0.1-{digest}"


def contribution_gold_json_document(
    annotation: HvsContributionGoldAnnotation,
) -> dict:
    """Serialize a validated annotation for the generated JSON twin."""

    document = compact_contribution_annotation_document(annotation)
    document["canary"] = contribution_annotation_canary(document)
    return document


def upgrade_contribution_annotation(payload: dict) -> dict:
    """Validate a parsed contribution annotation YAML; return the JSON twin."""

    annotation = HvsContributionGoldAnnotation.model_validate(payload)
    return contribution_gold_json_document(annotation)


def lint_contribution_annotation(
    annotation: HvsContributionGoldAnnotation,
) -> list[str]:
    """Content-level warnings that need a human eye but are not errors."""

    warnings: list[str] = []
    for contribution in annotation.contributions:
        if (
            contribution.contribution_type == "follow_up"
            and contribution.paper_boundness.status == "not_assessed"
            and "no new boundness" not in contribution.contribution_summary.lower()
            and "not assess" not in contribution.contribution_summary.lower()
            and "does not assess" not in contribution.contribution_summary.lower()
        ):
            warnings.append(
                f"{derived_identifier_display_name(contribution.identifiers, fallback='contribution')}: "
                "not_assessed contributions should state in the summary that no new boundness "
                "conclusion was reported"
            )
    return warnings
