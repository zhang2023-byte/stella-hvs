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
    "velocity": re.compile(
        r"((?<!high[- ])(?<!hyper)velocit(?:y|ies)|galactocentric|tangential|v[_ -]?(tot|gc|rf|tan))",
        re.IGNORECASE,
    ),
    "orbit": re.compile(r"(orbit|integrat|trajectory|eccentricity|pericentre|apocentre)", re.IGNORECASE),
    "bound_assessment": re.compile(r"(escape|bound|unbound|positive energy|\bp[_ -]?ub\b)", re.IGNORECASE),
    "radial_velocity": re.compile(r"(radial velocity|\brv\b)", re.IGNORECASE),
    "follow_up": re.compile(r"(follow[- ]?up|validation|observations?)", re.IGNORECASE),
}
COARSE_SIGNAL_COMBINATIONS = (
    ("distance", "velocity"),
    ("velocity", "orbit"),
    ("orbit", "bound_assessment"),
    ("radial_velocity", "follow_up"),
)
STEP_TYPE_COARSE_SIGNALS: dict[str, frozenset[str]] = {
    "distance_estimation": frozenset({"distance"}),
    "radial_velocity_measurement": frozenset({"radial_velocity"}),
    "velocity_calculation": frozenset({"velocity"}),
    "galactic_potential_model": frozenset(),
    "escape_or_bound_assessment": frozenset({"bound_assessment"}),
    "orbit_integration": frozenset({"orbit"}),
    "origin_assessment": frozenset({"origin"}),
    "follow_up_validation": frozenset({"follow_up"}),
}


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
    signals = _method_step_action_signals(step)
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


def _method_step_action_signals(step: dict[str, Any]) -> set[str]:
    """Return coarse signals for actions a method step appears to perform.

    Inputs are deliberately excluded: velocity and orbit calculations naturally
    consume distances, radial velocities, and phase-space vectors without
    directly producing those upstream quantities.
    """
    signals: set[str] = set()
    step_type = step.get("step_type")
    if isinstance(step_type, str):
        signals.update(STEP_TYPE_COARSE_SIGNALS.get(step_type, ()))

    output_text = _method_step_list_text(step, "outputs")
    for name, pattern in COARSE_SIGNAL_PATTERNS.items():
        if pattern.search(output_text):
            signals.add(name)

    summary = step.get("summary")
    if isinstance(summary, str):
        signals.update(_method_step_summary_action_signals(summary))

    return _suppress_compatible_method_signals(step, signals)


def _method_step_summary_action_signals(summary: str) -> set[str]:
    lowered = summary.lower()
    if re.search(r"\b(no|not|without)\b[^.]{0,80}\b(bound|unbound|escape)\b", lowered):
        lowered = COARSE_SIGNAL_PATTERNS["bound_assessment"].sub(" ", lowered)

    signals: set[str] = set()
    if re.search(r"\b(estimating|estimated|derive[ds]?|comput(?:e|ed|ing))\b[^.]{0,80}\bdistances?\b", lowered):
        signals.add("distance")
    if re.search(r"\b(comput(?:e|ed|ing)|calculat(?:e|ed|ing)|conversion|converted)\b[^.]{0,100}\b(velocity|velocities|v[_ -]?(tot|gc|rf|tan)|galactocentric)\b", lowered):
        signals.add("velocity")
    orbit_summary = re.sub(r"\bused for orbit integration\b", " ", lowered)
    if re.search(
        r"\b(integrat(?:e|ed|ing)|traceback)\b|"
        r"\b(comput(?:e|ed|ing)|calculat(?:e|ed|ing))\b[^.]{0,80}\b(orbit|trajectory)\b|"
        r"\borbit integration using\b",
        orbit_summary,
    ):
        signals.add("orbit")
    if re.search(r"\b(assess(?:ed|ing)?|classif(?:y|ied|ication)|compar(?:e|ed|ing))\b[^.]{0,120}\b(escape|bound|unbound|positive energy|p[_ -]?ub)\b", lowered):
        signals.add("bound_assessment")
    if re.search(r"\b(measur(?:e|ed|ing|ement)|determin(?:e|ed|ing))\b[^.]{0,80}\b(radial velocity|rv)\b", lowered):
        signals.add("radial_velocity")
    if COARSE_SIGNAL_PATTERNS["follow_up"].search(lowered):
        signals.add("follow_up")
    return signals


def _suppress_compatible_method_signals(step: dict[str, Any], signals: set[str]) -> set[str]:
    step_type = step.get("step_type")
    if not isinstance(step_type, str):
        return signals

    suppressed = set(signals)
    if step_type == "input_catalog":
        return STEP_TYPE_COARSE_SIGNALS.get(step_type, frozenset()).intersection(suppressed)
    if step_type == "radial_velocity_measurement" and "radial_velocity" in suppressed:
        suppressed.discard("follow_up")
    if step_type == "velocity_calculation" and "velocity" in suppressed:
        if not _method_step_outputs_signal(step, "distance"):
            suppressed.discard("distance")
        if not _method_step_outputs_signal(step, "radial_velocity"):
            suppressed.discard("radial_velocity")
        if "orbit" in suppressed and not _method_step_outputs_signal(step, "orbit"):
            suppressed.discard("orbit")
    if step_type == "orbit_integration" and "orbit" in suppressed:
        suppressed.discard("velocity")
        if not _method_step_outputs_signal(step, "distance"):
            suppressed.discard("distance")
        if not _method_step_outputs_signal(step, "bound_assessment"):
            suppressed.discard("bound_assessment")
    if step_type == "escape_or_bound_assessment" and "bound_assessment" in suppressed:
        suppressed.discard("orbit")
        if not _method_step_outputs_signal(step, "distance"):
            suppressed.discard("distance")
        if not _method_step_outputs_signal(step, "radial_velocity"):
            suppressed.discard("radial_velocity")
        suppressed.discard("velocity")
    if step_type == "origin_assessment":
        suppressed.discard("velocity")
        suppressed.discard("orbit")
    if step_type == "galactic_potential_model":
        suppressed.discard("orbit")
        if not _method_step_outputs_signal(step, "bound_assessment"):
            suppressed.discard("bound_assessment")
    return suppressed


def _method_step_outputs_signal(step: dict[str, Any], signal: str) -> bool:
    pattern = COARSE_SIGNAL_PATTERNS[signal]
    return bool(pattern.search(_method_step_list_text(step, "outputs")))


def _method_step_list_text(step: dict[str, Any], key: str) -> str:
    value = step.get(key)
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return ""

