"""Deterministic grouped-quantity validation and hydration.

Reuses the neutral V6 quantity, coordinate, locator, and hydration
primitives without modification: their semantics are identical per value.
New checks cover the grouped-multiset contract (vocabulary, one group per
quantity, non-empty values, exact-duplicate rejection) and per-value
condition/preference/provenance presence. Code never guesses or corrects a
source attribution; the submitted source value remains unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from stella.hvs_extraction.field_validate import (
    DIRECT_EVIDENCE_MISSING,
    FieldIssue,
    FieldValidationContext,
    _hydrate_source,
    _hydrate_text,
    _issues_for_coordinate,
    _issues_for_quantity,
    _validate_ecsv_locator,
    _validate_text_locator,
)

__all__ = [
    "DIRECT_EVIDENCE_MISSING",
    "QUANTITY_NOT_IN_VOCABULARY",
    "QUANTITY_DUPLICATE_GROUP",
    "VALUES_EMPTY",
    "VALUE_DUPLICATE",
    "CONDITION_REQUIRED",
    "PAPER_PREFERRED_REQUIRED",
    "SOURCE_REQUIRED",
    "SOURCE_KIND_INVALID",
    "COORDINATE_FORMAT_REQUIRED",
    "PROBABILITY_REPRESENTATION_INVALID",
    "validate_quantity_submission",
    "hydrate_quantity_submission",
    "quantity_allowed_roots",
]
from stella.hvs_contribution_extraction.quantity_schema import (
    COORDINATE_QUANTITY_PATHS,
    SOURCE_KINDS,
)
from stella.lit.schema_specs import HVS_CONTRIBUTION_QUANTITIES
from stella.lit.hvs_contribution_models import (
    validate_contribution_probability_representation,
)

# Grouped-multiset invariant codes.
QUANTITY_NOT_IN_VOCABULARY = "quantity_not_in_vocabulary"
QUANTITY_DUPLICATE_GROUP = "quantity_duplicate_group"
VALUES_EMPTY = "values_empty"
VALUE_DUPLICATE = "value_duplicate"
CONDITION_REQUIRED = "condition_required"
PAPER_PREFERRED_REQUIRED = "paper_preferred_required"
SOURCE_REQUIRED = "source_required"
SOURCE_KIND_INVALID = "source_kind_invalid"
COORDINATE_FORMAT_REQUIRED = "coordinate_format_required"
PROBABILITY_REPRESENTATION_INVALID = "probability_representation_invalid"

def _value_key(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def validate_quantity_submission(
    payload: dict[str, Any], ctx: FieldValidationContext
) -> list[FieldIssue]:
    """Run every deterministic structural, locator, and multiset check."""

    issues: list[FieldIssue] = []
    seen_quantities: dict[str, int] = {}
    for gi, group in enumerate(payload.get("quantities") or []):
        base = f"$.quantities[{gi}]"
        quantity = group.get("quantity")
        if quantity not in HVS_CONTRIBUTION_QUANTITIES:
            issues.append(
                FieldIssue(
                    f"{base}.quantity",
                    QUANTITY_NOT_IN_VOCABULARY,
                    f"quantity {quantity!r} is not in the nineteen-quantity vocabulary",
                )
            )
        elif quantity in seen_quantities:
            issues.append(
                FieldIssue(
                    f"{base}.quantity",
                    QUANTITY_DUPLICATE_GROUP,
                    f"quantity {quantity!r} already has a group at index {seen_quantities[quantity]}",
                )
            )
        else:
            seen_quantities[quantity] = gi

        values = group.get("values") or []
        if not values:
            issues.append(
                FieldIssue(f"{base}.values", VALUES_EMPTY, "each quantity group needs at least one value")
            )
        seen_value_keys: set[str] = set()
        for vi, value in enumerate(values):
            value_path = f"{base}.values[{vi}]"
            key = _value_key(value)
            if key in seen_value_keys:
                issues.append(
                    FieldIssue(
                        value_path,
                        VALUE_DUPLICATE,
                        "an exactly identical value record was already submitted in this quantity group",
                    )
                )
            seen_value_keys.add(key)

            if "condition" not in value:
                issues.append(
                    FieldIssue(f"{value_path}.condition", CONDITION_REQUIRED, "condition is required on every value")
                )
            if "paper_preferred" not in value:
                issues.append(
                    FieldIssue(f"{value_path}.paper_preferred", PAPER_PREFERRED_REQUIRED, "paper_preferred is required on every value (true, false, or null)")
                )
            source = value.get("source")
            if source is None:
                issues.append(
                    FieldIssue(f"{value_path}.source", SOURCE_REQUIRED, "source is required on every value")
                )
            elif not isinstance(source, str) or source not in SOURCE_KINDS:
                issues.append(
                    FieldIssue(
                        f"{value_path}.source",
                        SOURCE_KIND_INVALID,
                        f"source must be one of {SOURCE_KINDS}",
                    )
                )

            issues.extend(_issues_for_quantity(value_path, value))
            try:
                validate_contribution_probability_representation(
                    str(quantity or ""),
                    unit=value.get("unit"),
                    value=value.get("value"),
                    range_lower=value.get("range_lower"),
                    range_upper=value.get("range_upper"),
                )
            except ValueError as exc:
                issues.append(
                    FieldIssue(
                        value_path,
                        PROBABILITY_REPRESENTATION_INVALID,
                        str(exc),
                    )
                )
            if quantity in COORDINATE_QUANTITY_PATHS:
                coordinate_name = quantity.rsplit(".", 1)[1]
                if value.get("coordinate_format") is None:
                    issues.append(
                        FieldIssue(
                            f"{value_path}.coordinate_format",
                            COORDINATE_FORMAT_REQUIRED,
                            "coordinate values require coordinate_format",
                        )
                    )
                else:
                    issues.extend(_issues_for_coordinate(value_path, coordinate_name, value))

            for di, item in enumerate(value.get("direct_evidence") or []):
                source_ref = item.get("source") or {}
                source_path = f"{value_path}.direct_evidence[{di}].source"
                if source_ref.get("kind") == "text":
                    issues.extend(_validate_text_locator(source_path, source_ref, ctx, require_raw_value=True))
                elif source_ref.get("kind") == "ecsv_cell":
                    issues.extend(_validate_ecsv_locator(source_path, source_ref, ctx, allow_component=True))
            for ci, ref in enumerate(value.get("context_evidence") or []):
                issues.extend(
                    _validate_text_locator(f"{value_path}.context_evidence[{ci}]", ref, ctx, require_raw_value=False)
                )
    return issues


def hydrate_quantity_submission(
    payload: dict[str, Any],
    ctx: FieldValidationContext,
    *,
    tex_sha256: dict[str, str],
) -> dict[str, Any]:
    """Hydrate source representations; model-submitted values stay untouched."""

    def hydrate_text(ref: dict[str, Any]) -> dict[str, Any]:
        return _hydrate_text(ref, ctx, tex_sha256)

    def hydrate_direct(item: dict[str, Any]) -> dict[str, Any]:
        source = item["source"]
        if source.get("kind") == "text":
            hydrated = hydrate_text(source)
            hydrated["quantity_raw_value"] = source["raw_value"]
            return {"part": item["part"], "source": hydrated}
        return {"part": item["part"], "source": _hydrate_source(source, ctx)}

    def hydrate_value(value: dict[str, Any]) -> dict[str, Any]:
        return {
            **value,
            "direct_evidence": [hydrate_direct(item) for item in value.get("direct_evidence") or []],
            "context_evidence": [hydrate_text(ref) for ref in value.get("context_evidence") or []],
        }

    return {
        "quantities": [
            {
                "quantity": group["quantity"],
                "values": [hydrate_value(value) for value in group.get("values") or []],
            }
            for group in payload.get("quantities") or []
        ]
    }


def quantity_allowed_roots(issues: list[Any]) -> set[str]:
    """Smallest replaceable subtree per issue: one value, one group, or the list.

    Multiset semantics make the individual value the natural replacement
    unit; a whole quantity group may also be replaced when its identity itself
    is wrong.
    """

    roots: set[str] = set()
    for issue in issues:
        path = issue.path
        if path.startswith("$.quantities[") and ".values[" in path:
            head = path.split(".values[", 1)[0]
            value_index = path.split(".values[", 1)[1].split("]", 1)[0]
            roots.add(f"{head}.values[{value_index}]")
        elif path.startswith("$.quantities["):
            roots.add(path.split("].", 1)[0] + "]")
        else:
            roots.add(path)
    return roots
