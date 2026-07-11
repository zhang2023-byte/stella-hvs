"""Expert gold-annotation schema and upgrade logic for the benchmark.

The expert's primary artifact is a slim annotation YAML (see
``benchmark/templates/``) capturing only judgments, at exactly the
granularity the benchmark scores: candidate identities (L1), normalized
quantity values (L2), and evidence locations (L3). The upgrade step validates
it and emits the JSON twin (with a deterministic leak-audit ``canary``) next
to it in the external private gold repository (``STELLA_GOLD_DIR``).

Gold deliberately does not impersonate a full extraction record: experts
annotate from the PDF (the normative evidence source, see AGENTS.md), so
their evidence is a PDF locator plus an optional verbatim quote — it cannot
honestly inhabit the extraction schema's TeX/ECSV source refs. The AI
method_chain remains a schema-validated diagnostic product output, not an
expert-benchmarked gold field.
"""

from __future__ import annotations

import hashlib
import json
import re
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
)

# Quantity fields the benchmark scores at L2 (19 fields as of schema v0.2:
# bound_assessment keeps only the two probability slots; escape statistics
# left the core surface — docs/schema-v0.2-notes.md). The expert gold
# surface pins HVS speed to an explicitly Galactic rest frame, never an
# ambiguous generic total velocity. Schema v0.2 removed
# `derived_kinematics.total_velocity` from the extraction models, so the
# exclusion below is now a guard that keeps the gold vocabulary stable even
# if the slot ever returns.
_FROZEN_QUANTITY_FIELDS: tuple[str, ...] = (
    tuple(f"observed_phase_space.{name}" for name in ObservedPhaseSpace.model_fields)
    + tuple(f"derived_kinematics.{name}" for name in DerivedKinematics.model_fields)
    + tuple(f"bound_assessment.{name}" for name in BoundAssessment.model_fields)
)
_EXPERT_GOLD_EXCLUDED_QUANTITY_FIELDS = {
    "derived_kinematics.total_velocity",
}
SCORED_QUANTITY_FIELDS: tuple[str, ...] = tuple(
    field
    for field in _FROZEN_QUANTITY_FIELDS
    if field not in _EXPERT_GOLD_EXCLUDED_QUANTITY_FIELDS
)
GOLD_ORIGIN_TYPES = ("introduced_by_this_paper", "cited_from_literature")

# Same strict form the identity matcher accepts (stella.benchmark.identity).
GAIA_SOURCE_ID_RE = re.compile(r"^\s*Gaia\s+E?DR[0-9]\s+[0-9]+\s*$", re.IGNORECASE)

NUMERIC_QUANTITY_FIELDS = (
    "value",
    "error",
    "lower_error",
    "upper_error",
    "range_lower",
    "range_upper",
)

COORDINATE_QUANTITY_RANGES: dict[str, tuple[float, float, str, bool]] = {
    "observed_phase_space.ra": (0.0, 360.0, "[0, 360)", False),
    "observed_phase_space.dec": (-90.0, 90.0, "[-90, 90]", True),
}
HOURANGLE_UNITS = {"hourangle", "hour", "hours", "h", "hms"}
DEGREE_UNITS = {"degree", "degrees", "deg", "d", "dms"}
UNICODE_SIGN_TRANSLATION = {
    0x2212: "-",  # minus sign
    0xFE63: "-",  # small hyphen-minus
    0xFF0D: "-",  # fullwidth hyphen-minus
    0xFF0B: "+",  # fullwidth plus
}


def _normalize_number_text(text: str) -> str:
    return text.translate(UNICODE_SIGN_TRANSLATION).strip()


def _parse_plain_number(text: str) -> float | None:
    try:
        return float(_normalize_number_text(text))
    except ValueError:
        return None


def _parse_sexagesimal_components(text: str) -> float | None:
    normalized = _normalize_number_text(text)
    if not normalized:
        return None
    sign = -1.0 if normalized.startswith("-") else 1.0
    if normalized[0] in "+-":
        normalized = normalized[1:]
    for marker in ("h", "H", "d", "D", "m", "M", "°", "'"):
        normalized = normalized.replace(marker, ":")
    normalized = normalized.replace('"', "").replace("s", "").replace("S", "")
    normalized = re.sub(r"\s+", ":", normalized)
    normalized = re.sub(r":+", ":", normalized).strip(":")
    parts_text = normalized.split(":")
    if len(parts_text) not in (2, 3):
        return None
    if not all(
        re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", part)
        for part in parts_text
    ):
        return None
    parts = [float(part) for part in parts_text]
    if parts[1] >= 60.0 or (len(parts) == 3 and parts[2] >= 60.0):
        return None
    magnitude = parts[0] + parts[1] / 60.0
    if len(parts) == 3:
        magnitude += parts[2] / 3600.0
    return sign * magnitude


def _coordinate_value_degrees(field: str, value: str, unit: str) -> float | None:
    plain = _parse_plain_number(value)
    unit_normalized = unit.strip().lower()
    if plain is not None:
        if field == "observed_phase_space.ra" and unit_normalized in HOURANGLE_UNITS:
            return plain * 15.0
        return plain
    sexagesimal = _parse_sexagesimal_components(value)
    if sexagesimal is None:
        return None
    if field == "observed_phase_space.ra" and unit_normalized not in DEGREE_UNITS:
        return sexagesimal * 15.0
    return sexagesimal


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
        coordinate_value_degrees: float | None = None
        for name in NUMERIC_QUANTITY_FIELDS:
            text = getattr(self, name).strip()
            if not text:
                continue
            if name == "value" and self.field in COORDINATE_QUANTITY_RANGES:
                coordinate_value_degrees = _coordinate_value_degrees(
                    self.field, text, self.unit
                )
                if coordinate_value_degrees is not None:
                    continue
                raise ValueError(
                    f"{name} must be a plain number or sexagesimal coordinate "
                    f"for {self.field}, got {text!r}"
                )
            if _parse_plain_number(text) is None:
                raise ValueError(
                    f"{name} must be a plain number, got {text!r} "
                    "(operators go to limit_kind, units to unit, "
                    "qualifiers to notes)"
                ) from None
        if self.field in COORDINATE_QUANTITY_RANGES and self.value.strip():
            lower, upper, label, upper_inclusive = COORDINATE_QUANTITY_RANGES[
                self.field
            ]
            value = coordinate_value_degrees
            if value is None:
                raise ValueError(
                    f"value must be a plain number or sexagesimal coordinate "
                    f"for {self.field}, got {self.value.strip()!r}"
                )
            above_upper = value > upper if upper_inclusive else value >= upper
            if value < lower or above_upper:
                raise ValueError(
                    f"{self.field} out of range {label}: {self.value}"
                )
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
    paper_candidate_id: str = ""
    gaia_source_id: str = ""
    aliases: list[str] = Field(default_factory=list)
    origin_type: str = ""
    quantities: list[GoldQuantity] = Field(default_factory=list)
    evidence: list[GoldEvidence] = Field(default_factory=list)
    notes: str = ""

    @property
    def display_id(self) -> str:
        if self.paper_candidate_id:
            return self.paper_candidate_id
        if self.gaia_source_id:
            return self.gaia_source_id
        return self.aliases[0] if self.aliases else ""

    @model_validator(mode="after")
    def check_candidate(self) -> "GoldCandidate":
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError("aliases must be non-empty strings")
        if not (
            self.paper_candidate_id.strip()
            or self.gaia_source_id.strip()
            or any(alias.strip() for alias in self.aliases)
        ):
            raise ValueError(
                "candidate needs at least one paper_candidate_id, "
                "gaia_source_id, or alias"
            )
        if self.gaia_source_id.strip() and not GAIA_SOURCE_ID_RE.match(
            self.gaia_source_id
        ):
            raise ValueError(
                f"gaia_source_id must look like 'Gaia DR3 123...', "
                f"got {self.gaia_source_id!r}"
            )
        if self.origin_type not in GOLD_ORIGIN_TYPES:
            raise ValueError(f"unknown origin_type: {self.origin_type!r}")
        if not self.evidence:
            raise ValueError("candidate-level evidence is required")
        return self


class GoldAnnotationProcess(StrictModel):
    """How the expert annotation was produced."""

    protocol: str = ""
    scribe_agent: str = ""
    scribe_model: str = ""
    notes: str = ""


class GoldAnnotationSchema(StrictModel):
    name: Literal["benchmark.gold_annotation"]
    version: Literal[1]


class GoldAnnotation(StrictModel):
    schema_: GoldAnnotationSchema = Field(alias="schema")
    arxiv_id: str
    annotator: str
    annotated_at: str
    guideline_version: str
    evidence_basis: Literal["pdf"] = "pdf"
    annotation_process: GoldAnnotationProcess | None = None
    canary: str = ""
    status: Literal["candidates_found", "no_candidates"]
    candidates: list[GoldCandidate] = Field(default_factory=list)
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
        paper_ids = [
            candidate.paper_candidate_id
            for candidate in self.candidates
            if candidate.paper_candidate_id.strip()
        ]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("candidate paper_candidate_id values must be unique")
        gaia_ids = [
            candidate.gaia_source_id.lower()
            for candidate in self.candidates
            if candidate.gaia_source_id.strip()
        ]
        if len(gaia_ids) != len(set(gaia_ids)):
            raise ValueError("candidate gaia_source_id values must be unique")
        return self


# Soft unit expectations by field-name fragment. Lint warnings only — the
# expert records the paper's unit and may legitimately deviate.
EXPECTED_UNITS_BY_FRAGMENT: dict[str, tuple[str, ...]] = {
    "velocity": ("km/s", "km s^-1", "km s-1", "km/s "),
    "parallax": ("mas",),
    "proper_motion": ("mas/yr", "mas yr^-1"),
    "distance": ("pc", "kpc", "mpc"),
    "radius": ("pc", "kpc"),
}

# Transformed printed forms a paper may legitimately use instead of a linear
# unit — log distance, distance modulus (mag), dex. `unit` is free text by
# design and the benchmark keeps such forms verbatim (no conversion, to stay
# aligned with the frozen AI side), so they are not "unusual" units.
ALT_UNIT_MARKERS: tuple[str, ...] = ("log", "dex", "mag")


def lint_annotation(annotation: GoldAnnotation) -> list[str]:
    """Content-level warnings that need a human eye but are not errors."""

    warnings: list[str] = []
    for candidate in annotation.candidates:
        for quantity in candidate.quantities:
            field_name = quantity.field
            unit = quantity.unit.strip().lower()
            if "probability" in field_name and unit:
                warnings.append(
                    f"{candidate.display_id}/{field_name}: probabilities are "
                    f"unitless 0-1 fractions, found unit {quantity.unit!r}"
                )
                continue
            if any(marker in unit for marker in ALT_UNIT_MARKERS):
                continue  # transformed printed form (log distance, modulus, …)
            for fragment, expected in EXPECTED_UNITS_BY_FRAGMENT.items():
                if fragment in field_name and unit and unit not in expected:
                    warnings.append(
                        f"{candidate.display_id}/{field_name}: unit "
                        f"{quantity.unit!r} is unusual (expected one of "
                        f"{', '.join(expected)}); fine if the paper says so"
                    )
                    break
    return warnings


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


def compact_annotation_document(annotation: GoldAnnotation) -> dict:
    """Serialize a validated annotation without empty optional fields.

    Drafts intentionally retain their editor-shaped payload. This function is
    for formal YAML and JSON only; omitted values are restored by schema
    defaults when the document is read again.
    """

    document = _omit_empty_annotation_values(annotation.model_dump(mode="json", by_alias=True))
    if not isinstance(document, dict):  # Defensive guard for the public helper.
        raise TypeError("gold annotation document must be a mapping")
    return document


def annotation_canary(document: dict) -> str:
    """Return a deterministic leak-audit marker for a formal gold JSON twin."""

    payload = dict(document)
    payload.pop("canary", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return f"stella-gold-canary-v0.1-{digest}"


def gold_json_document(annotation: GoldAnnotation) -> dict:
    """Serialize a validated annotation for the generated JSON twin."""

    document = compact_annotation_document(annotation)
    document["canary"] = annotation_canary(document)
    return document


def upgrade_annotation(payload: dict) -> dict:
    """Validate a parsed annotation YAML and return the JSON-ready gold doc."""

    annotation = GoldAnnotation.model_validate(payload)
    return gold_json_document(annotation)
