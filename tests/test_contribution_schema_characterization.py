"""Semantic characterization of the contribution-first literature schema.

This test freezes the reviewed scientific contract of the
``literature_hvs_contributions`` artifact before the architecture refactor:
field names, required/optional status, value types, controlled vocabularies,
and nested multiplicity. It deliberately ignores Python module paths and
generated titles so the frozen contract remains comparable while the owning
modules move. Any diff here is a scientific contract change that this
refactor is not authorized to make.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "contracts"
    / "literature_hvs_contributions_schema.v1.json"
)


def _type_of(prop: dict[str, Any]) -> str:
    """Render a JSON Schema property as a module-independent type string."""

    if "enum" in prop:
        return "enum"
    if "$ref" in prop:
        return "ref:" + prop["$ref"].split("/")[-1]
    if "const" in prop:
        return f"const={prop['const']!r}"
    if "anyOf" in prop:
        members = sorted(_type_of(member) for member in prop["anyOf"])
        return "union[" + "|".join(members) + "]"
    type_name = prop.get("type")
    if type_name == "array":
        return f"array<{_type_of(prop.get('items', {}))}>"
    if type_name == "object" and "additionalProperties" in prop:
        return f"map<{_type_of(prop['additionalProperties'])}>"
    return str(type_name)


def _field_shape(prop: dict[str, Any]) -> dict[str, Any]:
    shape: dict[str, Any] = {"type": _type_of(prop)}
    if "enum" in prop:
        shape["enum"] = list(prop["enum"])
    if prop.get("type") == "array":
        shape["items"] = _type_of(prop.get("items", {}))
        shape["min_items"] = prop.get("minItems", 0)
    return shape


def _model_shape(definition: dict[str, Any]) -> dict[str, Any]:
    properties = definition.get("properties", {})
    required = sorted(definition.get("required", []))
    return {
        "required": required,
        "optional": sorted(set(properties) - set(required)),
        "fields": {
            name: _field_shape(prop) for name, prop in sorted(properties.items())
        },
    }


def characterize_contribution_schema() -> dict[str, Any]:
    """Extract the frozen structural contract from the Pydantic models."""

    from stella.lit.hvs_contribution_models import LiteratureHvsContributionsRecord
    from stella.lit.schema_specs import (
        HVS_CONTRIBUTION_QUANTITIES,
        HVS_CONTRIBUTION_TYPES,
        HVS_PAPER_BOUNDNESS_STATUSES,
    )

    schema = LiteratureHvsContributionsRecord.model_json_schema()
    defs = schema.get("$defs", {})
    models = {
        name: _model_shape(definition) for name, definition in sorted(defs.items())
    }
    models["LiteratureHvsContributionsRecord"] = _model_shape(schema)
    return {
        "artifact": "literature_hvs_contributions",
        "schema_version": 1,
        "vocabulary": {
            "contribution_types": list(HVS_CONTRIBUTION_TYPES),
            "paper_boundness_statuses": list(HVS_PAPER_BOUNDNESS_STATUSES),
            "quantities": list(HVS_CONTRIBUTION_QUANTITIES),
        },
        "models": models,
    }


class ContributionSchemaCharacterization(unittest.TestCase):
    def test_contract_matches_frozen_characterization(self) -> None:
        frozen = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(frozen, characterize_contribution_schema())


if __name__ == "__main__":
    unittest.main()
