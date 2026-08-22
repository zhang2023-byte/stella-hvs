"""Strict schema validation for contribution documents and artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stella.lit.hvs_contribution_models import (
    LiteratureHvsContributionsRecord,
    validate_literature_hvs_contributions_document,
)
from stella.schema_registry import require_schema


def validate_contribution_document(payload: Any) -> LiteratureHvsContributionsRecord:
    """Validate a literature_hvs_contributions document through the registry."""

    return validate_literature_hvs_contributions_document(payload)


def validate_contribution_document_file(path: Path) -> LiteratureHvsContributionsRecord:
    import json

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_contribution_document(payload)


def validate_transient_artifact(
    payload: Any, expected_name: str
) -> tuple[str, int]:
    """Validate one hvs_contribution_extraction transient artifact reference."""

    return require_schema(payload, expected_name)
