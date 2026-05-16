"""Rules for HVS candidate method provenance graphs."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


REPORTED_VALUE_STEP_TYPE = "reported_value_adoption"

CATEGORY_ALLOWED_DIRECT_STEP_TYPES: dict[str, frozenset[str]] = {
    "catalog_observed": frozenset({"input_catalog", "astrometric_calibration", REPORTED_VALUE_STEP_TYPE}),
    "radial_velocity": frozenset({"input_catalog", "radial_velocity_measurement", REPORTED_VALUE_STEP_TYPE}),
    "distance": frozenset({"distance_estimation", REPORTED_VALUE_STEP_TYPE}),
    "velocity": frozenset({"velocity_calculation", REPORTED_VALUE_STEP_TYPE}),
    "bound_assessment": frozenset({"escape_or_bound_assessment", REPORTED_VALUE_STEP_TYPE}),
    "orbit": frozenset({"orbit_integration", REPORTED_VALUE_STEP_TYPE}),
    "origin": frozenset({"origin_assessment", REPORTED_VALUE_STEP_TYPE}),
    "stellar_parameter": frozenset(
        {"stellar_parameter_inference", "photometric_or_sed_modeling", REPORTED_VALUE_STEP_TYPE}
    ),
    "photometric": frozenset({"input_catalog", "photometric_or_sed_modeling", REPORTED_VALUE_STEP_TYPE}),
    "quality": frozenset({"quality_filter", REPORTED_VALUE_STEP_TYPE}),
    "sample_selection": frozenset({"sample_selection", "quality_filter", "candidate_classification", REPORTED_VALUE_STEP_TYPE}),
    "candidate_classification": frozenset({"candidate_classification", "escape_or_bound_assessment", REPORTED_VALUE_STEP_TYPE}),
}

CATEGORY_REQUIRED_LINEAGE_STEP_TYPES: dict[str, tuple[frozenset[str], ...]] = {
    "distance": (frozenset({"input_catalog", "astrometric_calibration"}),),
    "velocity": (frozenset({"input_catalog", "astrometric_calibration"}),),
    "bound_assessment": (
        frozenset({"velocity_calculation"}),
        frozenset({"galactic_potential_model"}),
    ),
    "orbit": (
        frozenset({"velocity_calculation"}),
        frozenset({"galactic_potential_model"}),
    ),
    "origin": (frozenset({"orbit_integration"}),),
}

CORE_OBSERVED_CATALOG_FIELDS = {
    "ra",
    "dec",
    "parallax",
    "proper_motion_ra",
    "proper_motion_dec",
}
CORE_OBSERVED_DISTANCE_FIELDS = {"distance"}
CORE_OBSERVED_RADIAL_VELOCITY_FIELDS = {"radial_velocity"}
CORE_DERIVED_BOUND_FIELDS = {"escape_velocity", "escape_velocity_ratio"}
CORE_PROBABILITY_BOUND_FIELDS = {"bound_probability", "unbound_probability"}
CORE_PROBABILITY_CLASSIFICATION_FIELDS = {"classification_probability"}

QUALITY_RE = re.compile(
    r"(ruwe|parallax[_ -]?over[_ -]?error|visibility[_ -]?period|significance|"
    r"signal[_ -]?to[_ -]?noise|\bs/?n\b|transit|template|quality|flag)",
    re.IGNORECASE,
)
DISTANCE_RE = re.compile(r"(distance|dist\b|rgeo|photogeometric|heliocentric[_ -]?distance)", re.IGNORECASE)
RADIAL_VELOCITY_RE = re.compile(r"(radial[_ -]?velocity|\brv\b|vlos|line[_ -]?of[_ -]?sight)", re.IGNORECASE)
BOUND_RE = re.compile(
    r"(escape|unbound|bound[_ -]?probability|boundness|positive[_ -]?energy|escape[_ -]?margin)",
    re.IGNORECASE,
)
ORBIT_RE = re.compile(
    r"(orbit|eccentricity|pericentre|pericenter|apocentre|apocenter|angular[_ -]?momentum|"
    r"\blz\b|r[_ -]?min|r[_ -]?max|time[_ -]?of[_ -]?flight|flight[_ -]?time|disk[_ -]?cross)",
    re.IGNORECASE,
)
ORIGIN_RE = re.compile(r"(origin|ejection[_ -]?site|progenitor|galactic[_ -]?center|gc[_ -]?origin)", re.IGNORECASE)
STELLAR_RE = re.compile(
    r"(stellar|spectral[_ -]?type|luminosity[_ -]?class|teff|log[_ -]?g|metallicity|"
    r"\[?fe/h\]?|\bage\b|mass|abundance)",
    re.IGNORECASE,
)
PHOTOMETRIC_RE = re.compile(r"(photometr|magnitude|colour|color|redden|extinction|e\(b-v\)|bp-rp)", re.IGNORECASE)
VELOCITY_RE = re.compile(
    r"(velocity|v[_ -]?(tot|tan|gc|rf|grf|ej)|galactocentric[_ -]?v|galactic[_ -]?rest|"
    r"azimuthal[_ -]?velocity)",
    re.IGNORECASE,
)
SELECTION_RE = re.compile(r"(selection|selected|candidate[_ -]?sample|quality[_ -]?filtered)", re.IGNORECASE)
CLASSIFICATION_RE = re.compile(r"(classification|candidate[_ -]?status|ranking|score)", re.IGNORECASE)

COARSE_SIGNAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "distance": re.compile(r"(distance|photogeometric|bailer|parallax)", re.IGNORECASE),
    "velocity": re.compile(r"(velocity|galactocentric|tangential|v[_ -]?(tot|gc|rf|tan))", re.IGNORECASE),
    "orbit": re.compile(r"(orbit|integrat|trajectory|eccentricity|pericentre|apocentre)", re.IGNORECASE),
    "bound_assessment": re.compile(r"(escape|bound|unbound|positive energy|p[_ -]?ub)", re.IGNORECASE),
    "radial_velocity": re.compile(r"(radial velocity|\brv\b)", re.IGNORECASE),
    "follow_up": re.compile(r"(follow[- ]?up|validation|observ)", re.IGNORECASE),
}
COARSE_SIGNAL_COMBINATIONS = (
    ("distance", "velocity"),
    ("orbit", "bound_assessment"),
    ("radial_velocity", "follow_up"),
)


def classify_quantity_record(location: str, record: dict[str, Any]) -> str | None:
    """Classify a quantity for direct-producer validation."""
    field_name = _field_name_from_location(location)
    if ".core.observed_phase_space." in location:
        if field_name in CORE_OBSERVED_CATALOG_FIELDS:
            return "catalog_observed"
        if field_name in CORE_OBSERVED_DISTANCE_FIELDS:
            return "distance"
        if field_name in CORE_OBSERVED_RADIAL_VELOCITY_FIELDS:
            return "radial_velocity"
    if ".core.derived_kinematics." in location:
        if field_name in CORE_DERIVED_BOUND_FIELDS:
            return "bound_assessment"
        return "velocity"
    if ".core.probabilities." in location:
        if field_name in CORE_PROBABILITY_BOUND_FIELDS:
            return "bound_assessment"
        if field_name in CORE_PROBABILITY_CLASSIFICATION_FIELDS:
            return "candidate_classification"

    searchable = _searchable_quantity_text(field_name, record)
    if BOUND_RE.search(searchable):
        return "bound_assessment"
    if ORIGIN_RE.search(searchable):
        return "origin"
    if ORBIT_RE.search(searchable):
        return "orbit"
    if DISTANCE_RE.search(searchable):
        return "distance"
    if RADIAL_VELOCITY_RE.search(searchable):
        return "radial_velocity"
    if VELOCITY_RE.search(searchable):
        return "velocity"
    if STELLAR_RE.search(searchable):
        return "stellar_parameter"
    if QUALITY_RE.search(searchable):
        return "quality"
    if PHOTOMETRIC_RE.search(searchable):
        return "photometric"
    if CLASSIFICATION_RE.search(searchable):
        return "candidate_classification"
    if SELECTION_RE.search(searchable):
        return "sample_selection"
    return None


def allowed_direct_step_types(category: str | None) -> frozenset[str]:
    if category is None:
        return frozenset()
    return CATEGORY_ALLOWED_DIRECT_STEP_TYPES.get(category, frozenset())


def required_lineage_step_type_groups(category: str | None) -> tuple[frozenset[str], ...]:
    if category is None:
        return ()
    return CATEGORY_REQUIRED_LINEAGE_STEP_TYPES.get(category, ())


def lineage_for_step(step_id: str, dependencies: dict[str, list[str]]) -> list[str]:
    """Return step_id followed by recursive dependencies in nearest-first order."""
    lineage: list[str] = []
    seen: set[str] = set()

    def visit(current: str) -> None:
        if current in seen:
            return
        seen.add(current)
        lineage.append(current)
        for dependency in dependencies.get(current, []):
            visit(dependency)

    visit(step_id)
    return lineage


def coarse_step_warnings(step: dict[str, Any]) -> list[str]:
    """Return warnings for method steps that appear to mix atomic actions."""
    text = _method_step_search_text(step)
    signals = {name for name, pattern in COARSE_SIGNAL_PATTERNS.items() if pattern.search(text)}
    warnings: list[str] = []
    for first, second in COARSE_SIGNAL_COMBINATIONS:
        if first in signals and second in signals:
            warnings.append(f"method step appears to mix {first} and {second}; split atomic steps if both are real")
    return warnings


def categories_have_compatible_direct_types(categories: Iterable[str]) -> bool:
    category_list = list(categories)
    if len(category_list) <= 1:
        return True
    allowed_sets = [
        CATEGORY_ALLOWED_DIRECT_STEP_TYPES[category] - {REPORTED_VALUE_STEP_TYPE}
        for category in category_list
        if category in CATEGORY_ALLOWED_DIRECT_STEP_TYPES
    ]
    if len(allowed_sets) <= 1:
        return True
    intersection = set(allowed_sets[0])
    for allowed in allowed_sets[1:]:
        intersection &= set(allowed)
    return bool(intersection)


def _field_name_from_location(location: str) -> str:
    location = re.sub(r"\[\d+\]", "", location)
    return location.rsplit(".", 1)[-1]


def _searchable_quantity_text(field_name: str, record: dict[str, Any]) -> str:
    values = [field_name]
    for key in ("name", "kind", "description", "unit"):
        value = record.get(key)
        if isinstance(value, str):
            values.append(value)
    return " ".join(values)


def _method_step_search_text(step: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("step_type", "summary"):
        value = step.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ("inputs", "outputs"):
        value = step.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
    return " ".join(values)
