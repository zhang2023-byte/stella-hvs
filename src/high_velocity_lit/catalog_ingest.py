"""Bootstrap machine-readable catalog-ingestion scaffolds from per-paper verification records."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .literature_catalog import effective_catalog_verification, now_iso, normalize_space, read_json, relative_to


CATALOG_INGEST_MANIFEST_SCHEMA_VERSION = "stella.catalog.ingest.manifest.v1"
CATALOG_FIELD_DEFINITIONS_SCHEMA_VERSION = "stella.catalog.ingest.field_definitions.v1"
CATALOG_COLUMN_MAPPING_SCHEMA_VERSION = "stella.catalog.ingest.column_mapping.v1"
GENERIC_COLUMN_RE = re.compile(r"^col_\d+$", re.IGNORECASE)
SLUG_RE = re.compile(r"[^a-z0-9]+")
SCHEMA_DEFINITION_HEADERS = ("label", "unit", "description")

SCHEMA_FIELD_HINTS: dict[str, dict[str, Any]] = {
    "designation": {
        "standardized_name": "gaia_dr3_source_id",
        "semantic_type": "object_id",
        "semantic_group": "object_identifier",
        "value_kind": "string",
        "object_identifier": True,
        "target_unit": "",
    },
    "RAdeg": {
        "standardized_name": "ra_deg_icrs",
        "semantic_type": "coordinate",
        "semantic_group": "coordinate",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "deg",
    },
    "DEdeg": {
        "standardized_name": "dec_deg_icrs",
        "semantic_type": "coordinate",
        "semantic_group": "coordinate",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "deg",
    },
    "plx": {
        "standardized_name": "parallax_mas",
        "semantic_type": "astrometry",
        "semantic_group": "astrometry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "mas",
    },
    "e_plx": {
        "standardized_name": "parallax_error_mas",
        "semantic_type": "astrometry_error",
        "semantic_group": "astrometry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "mas",
    },
    "plx-zp": {
        "standardized_name": "parallax_zeropoint_mas",
        "semantic_type": "astrometry_calibration",
        "semantic_group": "astrometry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "mas",
    },
    "pmRA": {
        "standardized_name": "pmra_mas_per_yr",
        "semantic_type": "astrometry",
        "semantic_group": "astrometry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "mas/yr",
    },
    "e_pmRA": {
        "standardized_name": "pmra_error_mas_per_yr",
        "semantic_type": "astrometry_error",
        "semantic_group": "astrometry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "mas/yr",
    },
    "pmDE": {
        "standardized_name": "pmdec_mas_per_yr",
        "semantic_type": "astrometry",
        "semantic_group": "astrometry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "mas/yr",
    },
    "e_pmDE": {
        "standardized_name": "pmdec_error_mas_per_yr",
        "semantic_type": "astrometry_error",
        "semantic_group": "astrometry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "mas/yr",
    },
    "plx_pmra-corr": {
        "standardized_name": "parallax_pmra_corr",
        "semantic_type": "correlation_coefficient",
        "semantic_group": "astrometry",
        "value_kind": "ratio",
        "object_identifier": False,
        "target_unit": "",
    },
    "plx_pmdec-corr": {
        "standardized_name": "parallax_pmdec_corr",
        "semantic_type": "correlation_coefficient",
        "semantic_group": "astrometry",
        "value_kind": "ratio",
        "object_identifier": False,
        "target_unit": "",
    },
    "pmra_pmdec-corr": {
        "standardized_name": "pmra_pmdec_corr",
        "semantic_type": "correlation_coefficient",
        "semantic_group": "astrometry",
        "value_kind": "ratio",
        "object_identifier": False,
        "target_unit": "",
    },
    "ruwe": {
        "standardized_name": "gaia_ruwe",
        "semantic_type": "quality_metric",
        "semantic_group": "quality_flag",
        "value_kind": "ratio",
        "object_identifier": False,
        "target_unit": "",
    },
    "Gmag": {
        "standardized_name": "gaia_g_mag",
        "semantic_type": "photometry",
        "semantic_group": "photometry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "mag",
    },
    "bp-rp": {
        "standardized_name": "gaia_bp_rp_color_mag",
        "semantic_type": "photometry_color",
        "semantic_group": "photometry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "mag",
    },
    "cross-match-sur": {
        "standardized_name": "crossmatch_survey_name",
        "semantic_type": "provenance",
        "semantic_group": "provenance",
        "value_kind": "string",
        "object_identifier": False,
        "target_unit": "",
    },
    "surveyid": {
        "standardized_name": "crossmatch_survey_object_id",
        "semantic_type": "external_object_id",
        "semantic_group": "provenance",
        "value_kind": "string",
        "object_identifier": True,
        "target_unit": "",
    },
    "Teff": {
        "standardized_name": "teff_k",
        "semantic_type": "stellar_parameter",
        "semantic_group": "stellar_parameter",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "K",
    },
    "e_Teff": {
        "standardized_name": "teff_error_k",
        "semantic_type": "stellar_parameter_error",
        "semantic_group": "stellar_parameter",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "K",
    },
    "logg": {
        "standardized_name": "logg_cgs",
        "semantic_type": "stellar_parameter",
        "semantic_group": "stellar_parameter",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "log(cm/s^2)",
    },
    "e_logg": {
        "standardized_name": "logg_error_cgs",
        "semantic_type": "stellar_parameter_error",
        "semantic_group": "stellar_parameter",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "log(cm/s^2)",
    },
    "FeH": {
        "standardized_name": "fe_h_dex",
        "semantic_type": "chemistry",
        "semantic_group": "chemistry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "dex",
    },
    "e_FeH": {
        "standardized_name": "fe_h_error_dex",
        "semantic_type": "chemistry_error",
        "semantic_group": "chemistry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "dex",
    },
    "a/FeH": {
        "standardized_name": "alpha_fe_dex",
        "semantic_type": "chemistry",
        "semantic_group": "chemistry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "dex",
    },
    "e_a/FeH": {
        "standardized_name": "alpha_fe_error_dex",
        "semantic_type": "chemistry_error",
        "semantic_group": "chemistry",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "dex",
    },
    "RVel": {
        "standardized_name": "radial_velocity_weighted_km_per_s",
        "semantic_type": "radial_velocity",
        "semantic_group": "radial_velocity",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "km/s",
    },
    "e_RVel": {
        "standardized_name": "radial_velocity_weighted_error_km_per_s",
        "semantic_type": "radial_velocity_error",
        "semantic_group": "radial_velocity",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "km/s",
    },
    "GGDrlen": {
        "standardized_name": "ggd_lengthscale",
        "semantic_type": "distance_model_parameter",
        "semantic_group": "distance_model",
        "value_kind": "ratio",
        "object_identifier": False,
        "target_unit": "",
    },
    "GGDalpha": {
        "standardized_name": "ggd_alpha",
        "semantic_type": "distance_model_parameter",
        "semantic_group": "distance_model",
        "value_kind": "ratio",
        "object_identifier": False,
        "target_unit": "",
    },
    "GGDbeta": {
        "standardized_name": "ggd_beta",
        "semantic_type": "distance_model_parameter",
        "semantic_group": "distance_model",
        "value_kind": "ratio",
        "object_identifier": False,
        "target_unit": "",
    },
    "Dist": {
        "standardized_name": "heliocentric_distance_kpc",
        "semantic_type": "distance",
        "semantic_group": "distance",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "kpc",
    },
    "e_Dist": {
        "standardized_name": "heliocentric_distance_lower_error_kpc",
        "semantic_type": "distance_error",
        "semantic_group": "distance",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "kpc",
    },
    "E_Dist": {
        "standardized_name": "heliocentric_distance_upper_error_kpc",
        "semantic_type": "distance_error",
        "semantic_group": "distance",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "kpc",
    },
    "RGC": {
        "standardized_name": "galactocentric_distance_kpc",
        "semantic_type": "distance",
        "semantic_group": "distance",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "kpc",
    },
    "e_RGC": {
        "standardized_name": "galactocentric_distance_lower_error_kpc",
        "semantic_type": "distance_error",
        "semantic_group": "distance",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "kpc",
    },
    "E_RGC": {
        "standardized_name": "galactocentric_distance_upper_error_kpc",
        "semantic_type": "distance_error",
        "semantic_group": "distance",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "kpc",
    },
    "VGC": {
        "standardized_name": "galactocentric_speed_km_per_s",
        "semantic_type": "kinematics",
        "semantic_group": "kinematics",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "km/s",
    },
    "e_VGC": {
        "standardized_name": "galactocentric_speed_lower_error_km_per_s",
        "semantic_type": "kinematics_error",
        "semantic_group": "kinematics",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "km/s",
    },
    "E_VGC": {
        "standardized_name": "galactocentric_speed_upper_error_km_per_s",
        "semantic_type": "kinematics_error",
        "semantic_group": "kinematics",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "km/s",
    },
    "Vphi": {
        "standardized_name": "galactocentric_azimuthal_velocity_km_per_s",
        "semantic_type": "kinematics",
        "semantic_group": "kinematics",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "km/s",
    },
    "P-ub": {
        "standardized_name": "unbound_probability",
        "semantic_type": "probability",
        "semantic_group": "probability",
        "value_kind": "probability",
        "object_identifier": False,
        "target_unit": "",
    },
    "P-disk": {
        "standardized_name": "disk_origin_probability",
        "semantic_type": "probability",
        "semantic_group": "probability",
        "value_kind": "probability",
        "object_identifier": False,
        "target_unit": "",
    },
    "P-sgr": {
        "standardized_name": "sgr_origin_probability",
        "semantic_type": "probability",
        "semantic_group": "probability",
        "value_kind": "probability",
        "object_identifier": False,
        "target_unit": "",
    },
    "var-flag": {
        "standardized_name": "gaia_phot_variable_flag",
        "semantic_type": "quality_flag",
        "semantic_group": "quality_flag",
        "value_kind": "flag",
        "object_identifier": False,
        "target_unit": "",
    },
    "Pstar": {
        "standardized_name": "gaia_dsc_combmod_star_probability",
        "semantic_type": "probability",
        "semantic_group": "probability",
        "value_kind": "probability",
        "object_identifier": False,
        "target_unit": "",
    },
    "RVel-DR3": {
        "standardized_name": "gaia_dr3_radial_velocity_km_per_s",
        "semantic_type": "radial_velocity",
        "semantic_group": "radial_velocity",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "km/s",
    },
    "e_RVel-DR3": {
        "standardized_name": "gaia_dr3_radial_velocity_error_km_per_s",
        "semantic_type": "radial_velocity_error",
        "semantic_group": "radial_velocity",
        "value_kind": "quantity",
        "object_identifier": False,
        "target_unit": "km/s",
    },
}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.reader(handle)]


def _non_empty_cells(row: list[str]) -> list[str]:
    return [normalize_space(cell) for cell in row if normalize_space(cell)]


def looks_like_units_row(row: list[str]) -> bool:
    non_empty = _non_empty_cells(row)
    if not non_empty:
        return False
    bracketed = sum(1 for cell in non_empty if cell.startswith("[") and cell.endswith("]"))
    return bracketed / len(non_empty) >= 0.6


def _raw_headers(record_header: list[Any], csv_header: list[str], column_count: int) -> list[str]:
    if record_header and any(normalize_space(str(item)) for item in record_header):
        values = [normalize_space(str(item)) for item in record_header]
    else:
        values = [normalize_space(str(item)) for item in csv_header]
    if len(values) < column_count:
        values.extend("" for _ in range(column_count - len(values)))
    return values[:column_count]


def _sanitize_source_column(value: str, *, index: int) -> str:
    text = normalize_space(value).replace("\\_", "_")
    if "@" in text and text.split():
        text = text.split()[-1]
    text = text.strip()
    return text or f"col_{index + 1}"


def _choose_source_columns(raw_headers: list[str], csv_header: list[str], column_count: int) -> list[str]:
    if csv_header and len(csv_header) >= column_count and not all(GENERIC_COLUMN_RE.fullmatch(normalize_space(item) or "") for item in csv_header[:column_count]):
        base = [normalize_space(item) for item in csv_header[:column_count]]
    else:
        base = raw_headers[:column_count]
    return [_sanitize_source_column(value, index=index) for index, value in enumerate(base)]


def slugify(text: str, *, default: str) -> str:
    lowered = normalize_space(text).lower()
    slug = SLUG_RE.sub("_", lowered).strip("_")
    return slug or default


def _looks_like_schema_definition_table(csv_header: list[str]) -> bool:
    normalized = tuple(slugify(item, default="") for item in csv_header[:3])
    return normalized == SCHEMA_DEFINITION_HEADERS


def _schema_definition_rows(csv_path: Path) -> list[dict[str, str]]:
    rows = read_csv_rows(csv_path)
    if not rows or not _looks_like_schema_definition_table(rows[0]):
        return []
    fields: list[dict[str, str]] = []
    for index, row in enumerate(rows[1:], start=1):
        padded = [normalize_space(cell) for cell in row[:3]]
        if len(padded) < 3:
            padded.extend("" for _ in range(3 - len(padded)))
        label, units_hint, definition = padded
        if label:
            fields.append(
                {
                    "source_column": _sanitize_source_column(label, index=index),
                    "record_header": "Label",
                    "csv_header": "Label",
                    "units_hint": units_hint,
                    "definition": definition,
                }
            )
            continue
        if fields:
            continuation = normalize_space(" ".join(part for part in (units_hint, definition) if part))
            if continuation:
                fields[-1]["definition"] = normalize_space(f"{fields[-1]['definition']} {continuation}")
    return fields


def _normalized_target_unit(source_column: str, units_hint: str) -> str:
    known = SCHEMA_FIELD_HINTS.get(source_column) or {}
    if known.get("target_unit") is not None:
        return normalize_space(str(known.get("target_unit") or ""))
    unit = normalize_space(units_hint)
    if unit in {"---", "[-]"}:
        return ""
    return (
        unit.replace("[", "")
        .replace("]", "")
        .replace(".yr-1", "/yr")
        .replace(".s-1", "/s")
    )


def _infer_schema_field_hint(source_column: str, *, units_hint: str) -> dict[str, Any]:
    exact = SCHEMA_FIELD_HINTS.get(source_column)
    if exact is not None:
        return {
            "standardized_name": exact["standardized_name"],
            "semantic_type": exact["semantic_type"],
            "semantic_group": exact["semantic_group"],
            "value_kind": exact["value_kind"],
            "object_identifier": bool(exact["object_identifier"]),
            "target_unit": _normalized_target_unit(source_column, units_hint),
            "confidence": "high",
        }
    semantic_group = "provenance" if "id" in source_column.lower() else "unknown"
    semantic_type = "external_object_id" if "id" in source_column.lower() else "unknown"
    value_kind = "string" if "id" in source_column.lower() else "unknown"
    return {
        "standardized_name": slugify(source_column, default="field"),
        "semantic_type": semantic_type,
        "semantic_group": semantic_group,
        "value_kind": value_kind,
        "object_identifier": "id" in source_column.lower(),
        "target_unit": _normalized_target_unit(source_column, units_hint),
        "confidence": "medium" if semantic_group != "unknown" else "low",
    }


def infer_catalog_role_hint(
    *,
    caption: str,
    row_count: int,
    headers: list[str] | None = None,
    schema_field_count: int = 0,
) -> str:
    lowered = caption.lower()
    header_text = " ".join(normalize_space(item).lower() for item in (headers or []) if normalize_space(item))
    if schema_field_count >= 2 and any(token in lowered for token in ("catalog", "format")):
        return "schema_definition"
    if any(token in lowered for token in ("format", "criteria", "criterion", "remark", "quality check")):
        return "schema_or_supporting"
    if any(token in header_text for token in ("critical values", "remark", "quantity")):
        return "schema_or_supporting"
    if "catalog" in lowered:
        return "candidate_catalog"
    if row_count >= 5:
        return "candidate_catalog"
    return "unknown"


def collect_catalog_candidates(record: dict[str, Any], *, workspace_root: Path) -> list[dict[str, Any]]:
    tables = (record.get("catalog") or {}).get("tables") or (record.get("source") or {}).get("tables") or []
    candidates: list[dict[str, Any]] = []
    arxiv_id = normalize_space(str(record.get("arxiv_id") or ""))
    for position, table in enumerate(tables, start=1):
        if not isinstance(table, dict):
            continue
        csv_path_text = normalize_space(str(table.get("csv_path") or ""))
        if not csv_path_text:
            continue
        csv_path = Path(csv_path_text)
        if not csv_path.exists():
            continue
        rows = read_csv_rows(csv_path)
        schema_rows = _schema_definition_rows(csv_path)
        csv_header = rows[0] if rows else []
        body_rows = rows[1:] if len(rows) > 1 else []
        units_row = body_rows[0] if body_rows and looks_like_units_row(body_rows[0]) else []
        preview_rows = body_rows[1:4] if units_row else body_rows[:3]
        column_count = max(len(csv_header), len(units_row), max((len(row) for row in preview_rows), default=0))
        raw_headers = _raw_headers(table.get("header") or [], csv_header, column_count)
        source_columns = _choose_source_columns(raw_headers, csv_header, column_count)
        table_stem = csv_path.stem
        candidates.append(
            {
                "catalog_id": f"{arxiv_id}:{table_stem}",
                "table_name": table_stem,
                "source_tex": normalize_space(str(table.get("source_tex") or "")),
                "caption": normalize_space(str(table.get("caption") or "")),
                "csv_path": relative_to(csv_path, workspace_root),
                "extracted_row_count": int(table.get("row_count") or max(len(body_rows), 0)),
                "column_count": column_count,
                "catalog_role_hint": infer_catalog_role_hint(
                    caption=normalize_space(str(table.get("caption") or "")),
                    row_count=int(table.get("row_count") or max(len(body_rows), 0)),
                    headers=raw_headers,
                    schema_field_count=len(schema_rows),
                ),
                "header_source": "record_header" if any(raw_headers) else "csv_header",
                "record_header": raw_headers,
                "csv_header": [normalize_space(item) for item in csv_header[:column_count]],
                "source_columns": source_columns,
                "units_row": [normalize_space(item) for item in units_row[:column_count]] if units_row else [],
                "preview_rows": [[normalize_space(cell) for cell in row[:column_count]] for row in preview_rows],
                "schema_field_count": len(schema_rows),
                "selected_for_ingest": None,
                "notes": (
                    "Schema definition for a machine-readable catalog; use row labels as the real catalog columns."
                    if schema_rows
                    else ""
                ),
            }
        )
    return candidates


def build_catalog_ingest_manifest(
    record: dict[str, Any],
    *,
    paper_dir: Path,
    workspace_root: Path,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    effective = effective_catalog_verification(record)
    selected_catalogs_count = sum(1 for candidate in candidates if candidate.get("selected_for_ingest") is True)
    schema_catalog_count = sum(1 for candidate in candidates if candidate.get("catalog_role_hint") == "schema_definition")
    return {
        "schema_version": CATALOG_INGEST_MANIFEST_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "arxiv_id": normalize_space(str(record.get("arxiv_id") or "")),
        "title": normalize_space(str(record.get("title") or "")),
        "source_record_path": relative_to(paper_dir / "record.json", workspace_root),
        "verification_summary": {
            "decision_source": normalize_space(str(effective.get("decision_source") or "")),
            "overall_verdict": normalize_space(str(effective.get("overall_verdict") or "")),
            "catalog_location": normalize_space(str(effective.get("catalog_location") or "")),
            "primary_host": normalize_space(str(effective.get("primary_host") or "")),
            "internal_delivery": normalize_space(str(effective.get("internal_delivery") or "")),
            "external_delivery": normalize_space(str(effective.get("external_delivery") or "")),
            "confidence": normalize_space(str(effective.get("confidence") or "")),
        },
        "source_summary": {
            "catalog_table_count": len(candidates),
            "data_file_count": len(((record.get("catalog") or {}).get("data_files") or [])),
        },
        "catalog_candidates": candidates,
        "status": {
            "manifest_prepared": True,
            "selected_catalogs_count": selected_catalogs_count,
            "field_definitions_started": schema_catalog_count > 0,
            "column_mapping_started": schema_catalog_count > 0,
        },
    }


def _build_pending_field_entries(candidate: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    fields = []
    units_row = candidate.get("units_row") or []
    raw_headers = candidate.get("record_header") or []
    csv_headers = candidate.get("csv_header") or []
    for index, source_column in enumerate(candidate.get("source_columns") or []):
        fields.append(
            {
                "field_id": f"{candidate['catalog_id']}:{slugify(source_column, default=f'col_{index + 1}')}",
                "source_column": source_column,
                "record_header": raw_headers[index] if index < len(raw_headers) else "",
                "csv_header": csv_headers[index] if index < len(csv_headers) else "",
                "units_hint": units_row[index] if index < len(units_row) else "",
                "definition": "",
                "semantic_type": "",
                "standardized_name": "",
                "object_identifier": False,
                "value_kind": "unknown",
                "status": "pending",
                "notes": "",
            }
        )
    return "pending", fields


def _build_schema_field_entries(candidate: dict[str, Any], *, workspace_root: Path) -> tuple[str, list[dict[str, Any]]]:
    csv_path = workspace_root / str(candidate.get("csv_path") or "")
    schema_rows = _schema_definition_rows(csv_path)
    if not schema_rows:
        return _build_pending_field_entries(candidate)
    fields: list[dict[str, Any]] = []
    for index, row in enumerate(schema_rows):
        source_column = normalize_space(str(row.get("source_column") or ""))
        field_hint = _infer_schema_field_hint(source_column, units_hint=normalize_space(str(row.get("units_hint") or "")))
        fields.append(
            {
                "field_id": f"{candidate['catalog_id']}:{slugify(source_column, default=f'field_{index + 1}')}",
                "source_column": source_column,
                "record_header": normalize_space(str(row.get("record_header") or "Label")),
                "csv_header": normalize_space(str(row.get("csv_header") or "Label")),
                "units_hint": normalize_space(str(row.get("units_hint") or "")),
                "definition": normalize_space(str(row.get("definition") or "")),
                "semantic_type": normalize_space(str(field_hint.get("semantic_type") or "")),
                "standardized_name": normalize_space(str(field_hint.get("standardized_name") or "")),
                "object_identifier": bool(field_hint.get("object_identifier")),
                "value_kind": normalize_space(str(field_hint.get("value_kind") or "unknown")),
                "status": "drafted",
                "notes": "Expanded from the catalog-format schema table that defines the external full catalog.",
            }
        )
    return "drafted", fields


def build_field_definitions_bundle(
    record: dict[str, Any],
    *,
    candidates: list[dict[str, Any]],
    workspace_root: Path,
) -> dict[str, Any]:
    catalogs: list[dict[str, Any]] = []
    for candidate in candidates:
        catalog_status, fields = _build_schema_field_entries(candidate, workspace_root=workspace_root)
        catalogs.append(
            {
                "catalog_id": candidate["catalog_id"],
                "table_name": candidate["table_name"],
                "caption": candidate.get("caption") or "",
                "csv_path": candidate["csv_path"],
                "catalog_role_hint": candidate.get("catalog_role_hint") or "unknown",
                "selected_for_ingest": candidate.get("selected_for_ingest"),
                "status": catalog_status,
                "fields": fields,
            }
        )
    return {
        "schema_version": CATALOG_FIELD_DEFINITIONS_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "arxiv_id": normalize_space(str(record.get("arxiv_id") or "")),
        "title": normalize_space(str(record.get("title") or "")),
        "catalogs": catalogs,
    }


def build_column_mapping_bundle(
    record: dict[str, Any],
    *,
    candidates: list[dict[str, Any]],
    workspace_root: Path,
) -> dict[str, Any]:
    mappings: list[dict[str, Any]] = []
    for candidate in candidates:
        csv_path = workspace_root / str(candidate.get("csv_path") or "")
        schema_rows = _schema_definition_rows(csv_path)
        if schema_rows:
            for row in schema_rows:
                source_column = normalize_space(str(row.get("source_column") or ""))
                field_hint = _infer_schema_field_hint(source_column, units_hint=normalize_space(str(row.get("units_hint") or "")))
                mappings.append(
                    {
                        "catalog_id": candidate["catalog_id"],
                        "source_column": source_column,
                        "standardized_name": normalize_space(str(field_hint.get("standardized_name") or "")),
                        "semantic_group": normalize_space(str(field_hint.get("semantic_group") or "")),
                        "unit": normalize_space(str(field_hint.get("target_unit") or "")),
                        "transform": "",
                        "confidence": normalize_space(str(field_hint.get("confidence") or "pending")),
                        "status": "drafted",
                        "notes": "Derived from the catalog-format schema table for the external full catalog.",
                    }
                )
            continue
        units_row = candidate.get("units_row") or []
        for index, source_column in enumerate(candidate.get("source_columns") or []):
            mappings.append(
                {
                    "catalog_id": candidate["catalog_id"],
                    "source_column": source_column,
                    "standardized_name": "",
                    "semantic_group": "",
                    "unit": units_row[index] if index < len(units_row) else "",
                    "transform": "",
                    "confidence": "pending",
                    "status": "pending",
                    "notes": "",
                }
            )
    return {
        "schema_version": CATALOG_COLUMN_MAPPING_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "arxiv_id": normalize_space(str(record.get("arxiv_id") or "")),
        "title": normalize_space(str(record.get("title") or "")),
        "mappings": mappings,
    }


def bootstrap_catalog_ingestion(
    *,
    paper_dir: Path,
    workspace_root: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    record_path = paper_dir / "record.json"
    record = read_json(record_path)
    candidates = collect_catalog_candidates(record, workspace_root=workspace_root)
    ingest_dir = paper_dir / "catalog_ingest"
    manifest = build_catalog_ingest_manifest(
        record,
        paper_dir=paper_dir,
        workspace_root=workspace_root,
        candidates=candidates,
    )
    field_definitions = build_field_definitions_bundle(record, candidates=candidates, workspace_root=workspace_root)
    column_mapping = build_column_mapping_bundle(record, candidates=candidates, workspace_root=workspace_root)
    outputs = {
        ingest_dir / "manifest.json": manifest,
        ingest_dir / "field_definitions.json": field_definitions,
        ingest_dir / "column_mapping.json": column_mapping,
    }
    written_paths: list[str] = []
    skipped_paths: list[str] = []
    for path, payload in outputs.items():
        if path.exists() and not overwrite:
            skipped_paths.append(str(path))
            continue
        write_json(path, payload)
        written_paths.append(str(path))
    return {
        "arxiv_id": normalize_space(str(record.get("arxiv_id") or "")),
        "paper_dir": str(paper_dir),
        "catalog_candidate_count": len(candidates),
        "written_paths": written_paths,
        "skipped_paths": skipped_paths,
    }
