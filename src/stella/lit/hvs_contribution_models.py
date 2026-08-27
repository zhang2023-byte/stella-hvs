"""Pydantic models for the contribution-first HVS literature artifact.

The canonical unit is one current-paper/object contribution record: what the
current paper actually did to each identifiable object with a paper-supported
Galactic-unbound anchor. This
artifact family is parallel to ``literature_hvs_candidates`` (V6) and does
not replace it; V6 readers and writers stay unchanged.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Union

from pydantic import Field, model_validator

from .schema_models import StrictModel
from .schema_specs import (
    HVS_CONTRIBUTION_TYPES,
    HVS_PAPER_BOUNDNESS_STATUSES,
    HVS_CONTRIBUTION_QUANTITIES,
)
from stella.schema_registry import require_schema

_PLAIN_NUMBER_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
_UNICODE_SIGN_TRANSLATION = str.maketrans(
    {"−": "-", "﹣": "-", "－": "-", "＋": "+"}
)


def _normalize_number(text: str) -> str:
    return str(text).translate(_UNICODE_SIGN_TRANSLATION).strip()


def _valid_sexagesimal(text: str) -> bool:
    normalized = _normalize_number(text)
    if not normalized:
        return False
    if normalized[0] in "+-":
        normalized = normalized[1:]
    for marker in ("h", "H", "d", "D", "m", "M", "°", "'"):
        normalized = normalized.replace(marker, ":")
    normalized = normalized.replace('"', "").replace("s", "").replace("S", "")
    normalized = re.sub(r"\s+", ":", normalized)
    normalized = re.sub(r":+", ":", normalized).strip(":")
    parts = normalized.split(":")
    if len(parts) not in (2, 3):
        return False
    if not all(re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", part) for part in parts):
        return False
    values = [float(part) for part in parts]
    return values[1] < 60 and (len(values) == 2 or values[2] < 60)

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
    raw_value: str | None = None

    @model_validator(mode="after")
    def valid_locator(self) -> "TextEvidence":
        if not self.path.strip():
            raise ValueError("text evidence path is required")
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("text evidence needs a positive inclusive line range")
        return self


class EcsvCellEvidence(StrictModel):
    kind: Literal["ecsv_cell"]
    path: str
    line: int
    column: str
    component_raw_value: str | None = None

    @model_validator(mode="after")
    def valid_locator(self) -> "EcsvCellEvidence":
        if not self.path.strip() or not self.column.strip() or self.line < 1:
            raise ValueError("ECSV evidence needs path, positive line, and column")
        return self


ContributionEvidenceRef = Union[TextEvidence, EcsvCellEvidence]

CoordinateFormat = Literal[
    "decimal_degrees",
    "sexagesimal_hms",
    "sexagesimal_dms",
    "sexagesimal_colon",
]


def validate_contribution_probability_representation(
    quantity: str,
    *,
    unit: str | None,
    value: str | None,
    range_lower: str | None,
    range_upper: str | None,
) -> None:
    """Accept contribution probabilities as fractions or explicit percents.

    Fractions use no unit and stay within 0--1. Percent values use the
    canonical ``%`` unit and stay within 0--100. Conversion, when needed by a
    consumer such as scoring, is program-owned rather than serialized back
    into the scientific record.
    """

    if quantity not in (
        "bound_assessment.bound_probability",
        "bound_assessment.unbound_probability",
    ):
        return
    normalized_unit = str(unit or "").strip()
    if normalized_unit not in ("", "%"):
        raise ValueError("probability unit must be empty for a fraction or '%' for a percent")
    upper = 100.0 if normalized_unit == "%" else 1.0
    for part, text in (
        ("value", value),
        ("range_lower", range_lower),
        ("range_upper", range_upper),
    ):
        if text is None or not str(text).strip():
            continue
        try:
            number = float(_normalize_number(str(text)))
        except ValueError:
            continue
        if not 0.0 <= number <= upper:
            scale = "0--100 percent" if normalized_unit == "%" else "0--1 fraction"
            raise ValueError(f"probability {part} must be a {scale}")


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
    evidence: list[ContributionEvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def value_required(self) -> "ContributionIdentifierItem":
        if not self.value.strip():
            raise ValueError("identifier value is required")
        return self


def derived_identifier_display_name(
    identifiers: list[Any],
    *,
    fallback: str,
) -> str:
    """Choose an order-independent display label without scientific preference."""

    values: list[str] = []
    for item in identifiers:
        value = (
            getattr(item, "value", None)
            if not isinstance(item, dict)
            else item.get("value")
        )
        text = str(value or "").strip()
        if text:
            values.append(text)
    if not values:
        return fallback
    return min(values, key=lambda value: (len(value), value.casefold(), value))


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


class QuantityDirectEvidence(StrictModel):
    """One part-labelled direct source for one numeric component."""

    part: Literal["value", "error", "lower_error", "upper_error", "range_lower", "range_upper"]
    source: ContributionEvidenceRef

    @model_validator(mode="after")
    def raw_numeric_fragment_required(self) -> "QuantityDirectEvidence":
        if isinstance(self.source, TextEvidence):
            if not str(self.source.raw_value or "").strip():
                raise ValueError("text direct evidence requires raw_value")
        elif not str(self.source.component_raw_value or "").strip():
            raise ValueError("ECSV direct evidence requires component_raw_value")
        return self


class ReportedValue(StrictModel):
    """One explicitly object-attributed value of one structured quantity.

    ``condition`` records the potential, prior, method, epoch, data release,
    frame, or convention the value belongs to. ``paper_preferred`` is the
    paper's explicit preference only; null means the paper states none.
    ``source`` is the provenance category and is orthogonal to preference.
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
    condition: str
    paper_preferred: bool | None = Field(strict=True)
    source: Literal["this_paper", "prior_work", "unclear"]
    direct_evidence: list[QuantityDirectEvidence] = Field(default_factory=list)
    context_evidence: list[TextEvidence] = Field(default_factory=list)
    source_note: str = ""

    @model_validator(mode="after")
    def value_and_limit_shape(self) -> "ReportedValue":
        if self.error is not None and self.error.strip() and (
            (self.lower_error is not None and self.lower_error.strip())
            or (self.upper_error is not None and self.upper_error.strip())
        ):
            raise ValueError("symmetric and asymmetric uncertainties cannot be mixed")
        has_lower = self.lower_error is not None and bool(self.lower_error.strip())
        has_upper = self.upper_error is not None and bool(self.upper_error.strip())
        if has_lower != has_upper:
            raise ValueError("asymmetric uncertainty requires both lower and upper errors")
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
        numeric_parts = (
            "value",
            "error",
            "lower_error",
            "upper_error",
            "range_lower",
            "range_upper",
        )
        for part in numeric_parts:
            text = getattr(self, part)
            if text is None or not text.strip():
                continue
            if part == "value" and self.coordinate_format not in (
                None,
                "decimal_degrees",
            ):
                if not _valid_sexagesimal(text):
                    raise ValueError(f"{part} is not valid sexagesimal numeric text")
            elif not _PLAIN_NUMBER_RE.fullmatch(_normalize_number(text)):
                raise ValueError(f"{part} must be a plain numeric string")

        populated = {
            part
            for part in numeric_parts
            if (getattr(self, part) is not None and getattr(self, part).strip())
        }
        evidence_parts = [item.part for item in self.direct_evidence]
        if len(evidence_parts) != len(set(evidence_parts)):
            raise ValueError("each numeric component has at most one direct evidence item")
        if set(evidence_parts) != populated:
            missing = sorted(populated - set(evidence_parts))
            unexpected = sorted(set(evidence_parts) - populated)
            raise ValueError(
                "direct evidence must cover exactly the populated numeric components; "
                f"missing={missing}, unexpected={unexpected}"
            )
        return self


class QuantityGroup(StrictModel):
    """All reported values of one structured quantity, as an unordered multiset.

    Array order and any display-only ordinal are not canonical and are never
    scored. Values are deduplicated only when the complete record (value,
    condition, provenance, and evidence) is identical.
    """

    quantity: Literal[HVS_CONTRIBUTION_QUANTITIES]
    values: list[ReportedValue] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_exact_duplicate_values(self) -> "QuantityGroup":
        seen: set[str] = set()
        for item in self.values:
            key = json.dumps(
                item.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
            )
            if key in seen:
                raise ValueError(
                    f"duplicate reported value for quantity {self.quantity}"
                )
            seen.add(key)
        coordinate_quantity = self.quantity in (
            "observed_phase_space.ra",
            "observed_phase_space.dec",
        )
        for item in self.values:
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
        return self


class QuantityExtractionFailure(StrictModel):
    """Explicit delivery failure for the quantity stage of one object."""

    code: str
    detail: str = ""

    @model_validator(mode="after")
    def error_required(self) -> "QuantityExtractionFailure":
        if not self.code.strip():
            raise ValueError("failure code is required")
        return self


class ObjectContribution(StrictModel):
    """One current-paper/object contribution record.

    ``record_id`` is a program-generated document-local technical handle; it
    is never model-authored and never a scientific matching or scoring key. A
    roster-success/quantity-failure object survives with its contribution
    identity intact, empty quantities, and ``quantity_extraction_status=failed``.
    """

    record_id: str
    identifiers: list[ContributionIdentifierItem] = Field(min_length=1)
    contribution_type: Literal[HVS_CONTRIBUTION_TYPES]
    contribution_summary: str
    contribution_evidence: list[ContributionEvidenceRef] = Field(min_length=1)
    paper_boundness: PaperBoundness
    quantity_extraction_status: Literal["complete", "failed"]
    quantities: list[QuantityGroup] = Field(default_factory=list)
    failure: QuantityExtractionFailure | None = None

    @model_validator(mode="after")
    def check_contribution(self) -> "ObjectContribution":
        if not self.record_id.strip():
            raise ValueError("record_id is required")
        normalized_identifiers = [item.value.strip().casefold() for item in self.identifiers]
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
        if self.quantity_extraction_status == "complete":
            if self.failure is not None:
                raise ValueError(
                    "failure is only allowed when quantity extraction failed"
                )
        else:
            if self.quantities:
                raise ValueError(
                    "failed quantity extraction emits no quantities"
                )
            if self.failure is None:
                raise ValueError(
                    "failed quantity extraction requires a failure object"
                )
        return self


class ReviewedExclusion(StrictModel):
    """Paper-level exclusion preserved for scientific transparency."""

    reason: str
    evidence: list[ContributionEvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def reason_required(self) -> "ReviewedExclusion":
        if not self.reason.strip():
            raise ValueError("reviewed exclusion reason is required")
        return self


class LiteratureHvsContributionsRecord(StrictModel):
    """Canonical contribution-first literature artifact (v1)."""

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
