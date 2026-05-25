"""Enrich object-level HVS catalog records with public SIMBAD and Gaia DR3 data."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import astropy.units as u
from astropy.coordinates import SkyCoord


ENRICHMENT_MODES = ("auto", "off", "required")
ENRICHMENT_RADIUS_ARCSEC = 5.0
SIMBAD_IDENTIFIER_BATCH_SIZE = 200
SIMBAD_REGION_BATCH_SIZE = 20
GAIA_SOURCE_ID_BATCH_SIZE = 500
GAIA_REGION_BATCH_SIZE = 20
SIMBAD_FLUX_COLUMNS = ("U", "B", "V", "I", "J", "H", "K", "u", "g", "r", "i", "z")
SIMBAD_FLUX_ADQL_COLUMNS = {"u": "u_", "g": "g_", "r": "r_", "i": "i_", "z": "z_"}
SIMBAD_COLUMNS = (
    "oid",
    "main_id",
    "ra",
    "dec",
    "coo_err_maj",
    "coo_err_min",
    "coo_bibcode",
    "otype",
    "otype_txt",
    "sp_type",
    "sp_bibcode",
    "rvz_radvel",
    "rvz_err",
    "rvz_bibcode",
    "ids",
    *SIMBAD_FLUX_COLUMNS,
)
GAIA_ASTROMETRY_FIELDS = (
    "ra",
    "dec",
    "ra_error",
    "dec_error",
    "parallax",
    "parallax_error",
    "pmra",
    "pmra_error",
    "pmdec",
    "pmdec_error",
)
GAIA_PHOTOMETRY_FIELDS = (
    "phot_g_mean_mag",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
    "phot_g_mean_flux",
    "phot_bp_mean_flux",
    "phot_rp_mean_flux",
    "bp_rp",
    "bp_g",
    "g_rp",
)
GAIA_STELLAR_PARAMETER_FIELDS = (
    "teff_gspphot",
    "logg_gspphot",
    "mh_gspphot",
    "distance_gspphot",
    "azero_gspphot",
    "ag_gspphot",
    "ebpminrp_gspphot",
    "radius_flame",
    "lum_flame",
    "mass_flame",
    "age_flame",
)
GAIA_QUALITY_FIELDS = (
    "ruwe",
    "astrometric_params_solved",
    "astrometric_excess_noise",
    "duplicated_source",
    "phot_g_mean_flux_over_error",
    "phot_bp_mean_flux_over_error",
    "phot_rp_mean_flux_over_error",
    "radial_velocity_error",
    "rv_expected_sig_to_noise",
    "non_single_star",
)
GAIA_HIGHLIGHT_FIELDS = (
    "source_id",
    "designation",
    *GAIA_ASTROMETRY_FIELDS,
    *GAIA_PHOTOMETRY_FIELDS,
    "radial_velocity",
    "radial_velocity_error",
    *GAIA_STELLAR_PARAMETER_FIELDS,
    *GAIA_QUALITY_FIELDS,
)
NUMERIC_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
GAIA_SOURCE_ID_RE = re.compile(r"^Gaia\s+((?:E)?DR\d+)\s+(\d+)$", re.IGNORECASE)


class EnrichmentError(RuntimeError):
    """Raised when required catalog enrichment cannot complete."""


@dataclass(frozen=True)
class ObjectQueryCoordinate:
    object_id: str
    coordinate: SkyCoord


@dataclass(frozen=True)
class QueryRows:
    rows: list[dict[str, Any]]
    units: dict[str, str]


class EnrichmentClients(Protocol):
    def query_simbad_by_identifiers(self, identifiers: list[str]) -> Any:
        ...

    def query_simbad_by_regions(self, coordinates: list[ObjectQueryCoordinate]) -> Any:
        ...

    def query_gaia_by_source_ids(self, source_ids: list[str]) -> Any:
        ...

    def query_gaia_by_regions(self, coordinates: list[ObjectQueryCoordinate]) -> Any:
        ...


def now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def disabled_enrichment() -> dict[str, Any]:
    return {
        "status": "disabled",
        "queried_at": "",
        "providers": {},
        "verification": {},
        "warnings": [],
    }


def failed_enrichment(message: str, *, queried_at: str, warning_type: str = "enrichment_failed") -> dict[str, Any]:
    return {
        "status": "failed",
        "queried_at": queried_at,
        "providers": {},
        "verification": {},
        "warnings": [{"type": warning_type, "message": message}],
    }


def normalize_identifier(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def parse_gaia_source_number(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    match = GAIA_SOURCE_ID_RE.match(text)
    if not match:
        return ""
    return match.group(2)


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else None
    match = NUMERIC_RE.search(str(value))
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _json_scalar(value: Any) -> Any:
    if value is None:
        return ""
    if hasattr(value, "mask") and bool(getattr(value, "mask", False)):
        return ""
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ""
    text = str(value)
    if text in {"--", "nan", "NaN", "None"}:
        return ""
    return text


def _non_empty_json(value: Any) -> bool:
    return value not in (None, "", [], {})


def rows_from_query_result(result: Any) -> QueryRows:
    """Convert astroquery/fake query output into JSON-safe row dictionaries."""
    if result is None:
        return QueryRows(rows=[], units={})
    if isinstance(result, QueryRows):
        return result
    if isinstance(result, list):
        return QueryRows(rows=[{str(k): _json_scalar(v) for k, v in row.items()} for row in result], units={})
    if isinstance(result, tuple) and len(result) == 2:
        rows, units = result
        if isinstance(rows, list) and isinstance(units, dict):
            return QueryRows(
                rows=[{str(k): _json_scalar(v) for k, v in row.items()} for row in rows],
                units={str(k): str(v) for k, v in units.items() if str(v)},
            )

    colnames = list(getattr(result, "colnames", []) or [])
    units = {}
    for name in colnames:
        unit = getattr(result[name], "unit", None)
        if unit:
            units[str(name)] = str(unit)

    rows: list[dict[str, Any]] = []
    for row in result:
        rows.append({str(name): _json_scalar(row[name]) for name in colnames})
    return QueryRows(rows=rows, units=units)


def _raw_columns(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if _non_empty_json(value)}


def _adql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _chunked(values: list[Any], size: int) -> list[list[Any]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _query_with_split_fallback(values: list[Any], query_fn: Any) -> list[Any]:
    """Run a batch query and split oversized/problematic batches once needed."""
    if not values:
        return []
    try:
        return [query_fn(values)]
    except Exception:
        if len(values) == 1:
            raise
        midpoint = len(values) // 2
        return [
            *_query_with_split_fallback(values[:midpoint], query_fn),
            *_query_with_split_fallback(values[midpoint:], query_fn),
        ]


class AstroqueryCatalogClients:
    """Public SIMBAD/Gaia DR3 clients backed by astroquery."""

    def __init__(self) -> None:
        try:
            from astroquery.gaia import GaiaClass
            from astroquery.simbad import SimbadClass
        except Exception as exc:  # pragma: no cover - depends on optional runtime dependency.
            raise EnrichmentError(f"astroquery import failed: {type(exc).__name__}: {exc}") from exc

        try:
            self._gaia = GaiaClass(show_server_messages=False)
        except TypeError:  # pragma: no cover - older astroquery compatibility.
            self._gaia = GaiaClass()
        self._simbad = SimbadClass()
        self._simbad.ROW_LIMIT = -1
        try:
            self._gaia.ROW_LIMIT = -1
            self._gaia.MAIN_GAIA_TABLE = "gaiadr3.gaia_source"
        except Exception:
            pass

    def query_simbad_by_identifiers(self, identifiers: list[str]) -> QueryRows:
        if not identifiers:
            return QueryRows(rows=[], units={})
        rows: list[dict[str, Any]] = []
        units: dict[str, str] = {}
        def query_chunk(chunk: list[str]) -> QueryRows:
            query = _simbad_identifier_query(chunk)
            return rows_from_query_result(self._simbad.query_tap(query, async_job=True))

        for chunk in _chunked(identifiers, SIMBAD_IDENTIFIER_BATCH_SIZE):
            for result in _query_with_split_fallback(chunk, query_chunk):
                rows.extend(result.rows)
                units.update(result.units)
        return QueryRows(rows=rows, units=units)

    def query_simbad_by_regions(self, coordinates: list[ObjectQueryCoordinate]) -> QueryRows:
        if not coordinates:
            return QueryRows(rows=[], units={})
        rows: list[dict[str, Any]] = []
        units: dict[str, str] = {}
        def query_chunk(chunk: list[ObjectQueryCoordinate]) -> QueryRows:
            query = _simbad_region_query(chunk)
            return rows_from_query_result(self._simbad.query_tap(query, async_job=True))

        for chunk in _chunked(coordinates, SIMBAD_REGION_BATCH_SIZE):
            for result in _query_with_split_fallback(chunk, query_chunk):
                rows.extend(result.rows)
                units.update(result.units)
        return QueryRows(rows=rows, units=units)

    def query_gaia_by_source_ids(self, source_ids: list[str]) -> QueryRows:
        if not source_ids:
            return QueryRows(rows=[], units={})
        rows: list[dict[str, Any]] = []
        units: dict[str, str] = {}
        def query_chunk(chunk: list[str]) -> QueryRows:
            query = _gaia_source_id_query(chunk)
            job = self._gaia.launch_job_async(query, verbose=False)
            return rows_from_query_result(job.get_results())

        for chunk in _chunked(source_ids, GAIA_SOURCE_ID_BATCH_SIZE):
            for result in _query_with_split_fallback(chunk, query_chunk):
                rows.extend(result.rows)
                units.update(result.units)
        return QueryRows(rows=rows, units=units)

    def query_gaia_by_regions(self, coordinates: list[ObjectQueryCoordinate]) -> QueryRows:
        if not coordinates:
            return QueryRows(rows=[], units={})
        rows: list[dict[str, Any]] = []
        units: dict[str, str] = {}
        def query_chunk(chunk: list[ObjectQueryCoordinate]) -> QueryRows:
            query = _gaia_region_query(chunk)
            job = self._gaia.launch_job_async(query, verbose=False)
            return rows_from_query_result(job.get_results())

        for chunk in _chunked(coordinates, GAIA_REGION_BATCH_SIZE):
            for result in _query_with_split_fallback(chunk, query_chunk):
                rows.extend(result.rows)
                units.update(result.units)
        return QueryRows(rows=rows, units=units)


def _simbad_select_columns() -> str:
    flux_columns = ", ".join(
        f'allfluxes."{SIMBAD_FLUX_ADQL_COLUMNS.get(column, column)}" AS "{column}"'
        for column in SIMBAD_FLUX_COLUMNS
    )
    return (
        "basic.oid, basic.main_id, basic.ra, basic.dec, basic.coo_err_maj, basic.coo_err_min, "
        "basic.coo_bibcode, basic.otype, basic.otype_txt, basic.sp_type, basic.sp_bibcode, "
        "basic.rvz_radvel, basic.rvz_err, basic.rvz_bibcode, ids.ids, "
        f"{flux_columns}"
    )


def _simbad_from_clause() -> str:
    return (
        "basic "
        "LEFT JOIN ids ON basic.oid = ids.oidref "
        "LEFT JOIN allfluxes ON basic.oid = allfluxes.oidref"
    )


def _simbad_identifier_query(identifiers: list[str]) -> str:
    values = ", ".join(_adql_string(value) for value in identifiers)
    return (
        f"SELECT {_simbad_select_columns()} "
        f"FROM {_simbad_from_clause()} "
        "WHERE basic.oid IN ("
        "SELECT DISTINCT oidref FROM ident WHERE id IN ("
        f"{values}"
        "))"
    )


def _simbad_region_query(coordinates: list[ObjectQueryCoordinate]) -> str:
    criteria = []
    radius_deg = ENRICHMENT_RADIUS_ARCSEC / 3600.0
    for item in coordinates:
        criteria.append(
            "CONTAINS(POINT('ICRS', basic.ra, basic.dec), "
            f"CIRCLE('ICRS', {item.coordinate.ra.deg:.14f}, {item.coordinate.dec.deg:.14f}, {radius_deg:.14f})) = 1"
        )
    return f"SELECT {_simbad_select_columns()} FROM {_simbad_from_clause()} WHERE " + " OR ".join(criteria)


def _gaia_source_id_query(source_ids: list[str]) -> str:
    values = ", ".join(str(int(value)) for value in source_ids if str(value).isdigit())
    return f"SELECT * FROM gaiadr3.gaia_source WHERE source_id IN ({values})" if values else ""


def _gaia_region_query(coordinates: list[ObjectQueryCoordinate]) -> str:
    criteria = []
    radius_deg = ENRICHMENT_RADIUS_ARCSEC / 3600.0
    for item in coordinates:
        criteria.append(
            "CONTAINS(POINT('ICRS', ra, dec), "
            f"CIRCLE('ICRS', {item.coordinate.ra.deg:.14f}, {item.coordinate.dec.deg:.14f}, {radius_deg:.14f})) = 1"
        )
    return "SELECT * FROM gaiadr3.gaia_source WHERE " + " OR ".join(criteria)


def _candidate_identifier_values(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    canonical = record.get("canonical_identifier") if isinstance(record.get("canonical_identifier"), dict) else {}
    for value in (canonical.get("value"), record.get("object_id")):
        if value:
            values.append(str(value))
    for source in record.get("sources") or []:
        if not isinstance(source, dict):
            continue
        for key in ("gaia_source_id", "paper_candidate_id", "record_id"):
            value = source.get(key)
            if value:
                values.append(str(value))
    for candidate in record.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
        for key in ("gaia_source_id", "paper_candidate_id", "record_id"):
            value = identifiers.get(key)
            if value:
                values.append(str(value))
        for value in identifiers.get("all") or []:
            if value:
                values.append(str(value))
    return _unique_preserve_order(values)


def _unique_preserve_order(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").strip().split())
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _object_coordinate(record: dict[str, Any]) -> SkyCoord | None:
    for candidate in record.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        core = candidate.get("core") if isinstance(candidate.get("core"), dict) else {}
        observed = core.get("observed_phase_space") if isinstance(core.get("observed_phase_space"), dict) else {}
        ra = observed.get("ra")
        dec = observed.get("dec")
        if not isinstance(ra, dict) or not isinstance(dec, dict):
            continue
        coordinate = _coordinate_from_quantities(ra, dec)
        if coordinate is not None:
            return coordinate
    return None


def _coordinate_from_quantities(ra: dict[str, Any], dec: dict[str, Any]) -> SkyCoord | None:
    ra_value = str(ra.get("value") or "").strip()
    dec_value = str(dec.get("value") or "").strip()
    if not ra_value or not dec_value:
        return None
    ra_unit_text = str(ra.get("unit") or "").strip().lower()
    try:
        ra_unit = u.hourangle if ":" in ra_value and ra_unit_text not in {"deg", "degree", "degrees"} else u.deg
        return SkyCoord(ra=ra_value, dec=dec_value, unit=(ra_unit, u.deg), frame="icrs")
    except Exception:
        return None


def _coordinate_from_row(row: dict[str, Any]) -> SkyCoord | None:
    ra = parse_float(row.get("ra"))
    dec = parse_float(row.get("dec"))
    if ra is None or dec is None:
        return None
    try:
        return SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
    except Exception:
        return None


def _object_gaia_source_numbers(record: dict[str, Any]) -> list[str]:
    numbers: list[str] = []
    for value in _candidate_identifier_values(record):
        number = parse_gaia_source_number(value)
        if number:
            numbers.append(number)
    return _unique_preserve_order(numbers)


def _aliases_from_simbad_row(row: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    main_id = row.get("main_id")
    if main_id:
        aliases.append(str(main_id))
    ids = row.get("ids")
    if ids:
        aliases.extend(str(ids).split("|"))
    return _unique_preserve_order(aliases)


def _row_matches_object_identifiers(row: dict[str, Any], identifiers: list[str]) -> bool:
    aliases = {normalize_identifier(value) for value in _aliases_from_simbad_row(row)}
    return any(normalize_identifier(value) in aliases for value in identifiers)


def _nearest_row_for_coordinate(rows: list[dict[str, Any]], coordinate: SkyCoord) -> tuple[dict[str, Any] | None, float | None, int]:
    best_row: dict[str, Any] | None = None
    best_sep: float | None = None
    match_count = 0
    for row in rows:
        row_coord = _coordinate_from_row(row)
        if row_coord is None:
            continue
        sep = float(row_coord.separation(coordinate).arcsec)
        if sep <= ENRICHMENT_RADIUS_ARCSEC:
            match_count += 1
            if best_sep is None or sep < best_sep:
                best_sep = sep
                best_row = row
    return best_row, best_sep, match_count


def _field_payload(row: dict[str, Any], field: str, units: dict[str, str]) -> dict[str, Any]:
    value = row.get(field)
    if not _non_empty_json(value):
        return {}
    payload: dict[str, Any] = {"value": value}
    unit = units.get(field)
    if unit:
        payload["unit"] = unit
    return payload


def _field_group(row: dict[str, Any], fields: tuple[str, ...], units: dict[str, str]) -> dict[str, Any]:
    return {field: payload for field in fields if (payload := _field_payload(row, field, units))}


def _simbad_provider(row: dict[str, Any] | None, units: dict[str, str], *, matched_by: str) -> dict[str, Any]:
    if row is None:
        return {"status": "not_found", "matched_by": ""}
    photometry = []
    for band in SIMBAD_FLUX_COLUMNS:
        if _non_empty_json(row.get(band)):
            photometry.append({"band": band, "value": row.get(band), "unit": units.get(band, "mag")})
    radial_velocity: dict[str, Any] = {}
    if _non_empty_json(row.get("rvz_radvel")):
        radial_velocity = {
            "value": row.get("rvz_radvel"),
            "unit": units.get("rvz_radvel", "km/s"),
        }
        if _non_empty_json(row.get("rvz_err")):
            radial_velocity["error"] = row.get("rvz_err")
        if _non_empty_json(row.get("rvz_bibcode")):
            radial_velocity["bibcode"] = row.get("rvz_bibcode")
    spectral_type: dict[str, Any] = {}
    if _non_empty_json(row.get("sp_type")):
        spectral_type = {"value": row.get("sp_type")}
        if _non_empty_json(row.get("sp_bibcode")):
            spectral_type["bibcode"] = row.get("sp_bibcode")
    return {
        "status": "matched",
        "matched_by": matched_by,
        "main_id": str(row.get("main_id") or ""),
        "aliases": _aliases_from_simbad_row(row),
        "object_type": str(row.get("otype") or ""),
        "object_type_label": str(row.get("otype_txt") or ""),
        "coordinates": _field_group(row, ("ra", "dec", "coo_err_maj", "coo_err_min"), units),
        "radial_velocity": radial_velocity,
        "spectral_type": spectral_type,
        "photometry": photometry,
        "raw_columns": _raw_columns(row),
        "column_units": {key: value for key, value in units.items() if key in row},
    }


def _gaia_provider(row: dict[str, Any] | None, units: dict[str, str], *, matched_by: str) -> dict[str, Any]:
    if row is None:
        return {"status": "not_found", "matched_by": ""}
    radial_velocity: dict[str, Any] = {}
    if _non_empty_json(row.get("radial_velocity")):
        radial_velocity = {
            "value": row.get("radial_velocity"),
            "unit": units.get("radial_velocity", "km/s"),
        }
        if _non_empty_json(row.get("radial_velocity_error")):
            radial_velocity["error"] = row.get("radial_velocity_error")
    return {
        "status": "matched",
        "matched_by": matched_by,
        "source_id": str(row.get("source_id") or ""),
        "designation": str(row.get("designation") or ""),
        "astrometry": _field_group(row, GAIA_ASTROMETRY_FIELDS, units),
        "photometry": _field_group(row, GAIA_PHOTOMETRY_FIELDS, units),
        "radial_velocity": radial_velocity,
        "stellar_parameters": _field_group(row, GAIA_STELLAR_PARAMETER_FIELDS, units),
        "quality_flags": _field_group(row, GAIA_QUALITY_FIELDS, units),
        "raw_columns": _raw_columns(row),
        "column_units": {key: value for key, value in units.items() if key in row},
    }


def _provider_coordinate(provider: dict[str, Any]) -> SkyCoord | None:
    coordinates = provider.get("coordinates") or provider.get("astrometry")
    if not isinstance(coordinates, dict):
        return None
    ra_record = coordinates.get("ra")
    dec_record = coordinates.get("dec")
    if not isinstance(ra_record, dict) or not isinstance(dec_record, dict):
        return None
    ra = parse_float(ra_record.get("value"))
    dec = parse_float(dec_record.get("value"))
    if ra is None or dec is None:
        return None
    return SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")


def _candidate_field_values(record: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for candidate in record.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        core = candidate.get("core") if isinstance(candidate.get("core"), dict) else {}
        observed = core.get("observed_phase_space") if isinstance(core.get("observed_phase_space"), dict) else {}
        quantity = observed.get(field_name)
        if isinstance(quantity, dict) and _non_empty_json(quantity.get("value")):
            values.append({"source": str(candidate.get("source") or ""), "quantity": quantity})
    return values


def _value_comparisons(record: dict[str, Any], simbad_provider: dict[str, Any], gaia_provider: dict[str, Any]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    mappings = [
        ("parallax", gaia_provider.get("astrometry", {}).get("parallax") if isinstance(gaia_provider.get("astrometry"), dict) else None),
        ("proper_motion_ra", gaia_provider.get("astrometry", {}).get("pmra") if isinstance(gaia_provider.get("astrometry"), dict) else None),
        ("proper_motion_dec", gaia_provider.get("astrometry", {}).get("pmdec") if isinstance(gaia_provider.get("astrometry"), dict) else None),
        ("radial_velocity", gaia_provider.get("radial_velocity")),
        ("radial_velocity", simbad_provider.get("radial_velocity")),
    ]
    for literature_field, official in mappings:
        if not isinstance(official, dict) or not _non_empty_json(official.get("value")):
            continue
        official_value = parse_float(official.get("value"))
        if official_value is None:
            continue
        for item in _candidate_field_values(record, literature_field):
            lit_value = parse_float(item["quantity"].get("value"))
            if lit_value is None:
                continue
            comparisons.append(
                {
                    "source": item["source"],
                    "field": literature_field,
                    "literature_value": item["quantity"].get("value"),
                    "official_value": official.get("value"),
                    "difference": round(lit_value - official_value, 12),
                    "unit": official.get("unit") or item["quantity"].get("unit") or "",
                }
            )
    return comparisons


def _build_verification(
    record: dict[str, Any],
    simbad_provider: dict[str, Any],
    gaia_provider: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    identifiers = _candidate_identifier_values(record)
    normalized_ids = {normalize_identifier(value) for value in identifiers}
    aliases = set()
    if simbad_provider.get("status") == "matched":
        aliases = {normalize_identifier(value) for value in simbad_provider.get("aliases") or []}
    alias_matches = sorted(value for value in identifiers if normalize_identifier(value) in aliases)

    literature_gaia_numbers = _object_gaia_source_numbers(record)
    gaia_source_id = str(gaia_provider.get("source_id") or "")
    gaia_source_matches = bool(gaia_source_id and gaia_source_id in literature_gaia_numbers)
    if gaia_source_id and literature_gaia_numbers and not gaia_source_matches:
        warnings.append(
            {
                "type": "external_gaia_source_id_mismatch",
                "message": "Gaia DR3 source matched by coordinates does not match literature Gaia source id",
                "literature_gaia_source_numbers": literature_gaia_numbers,
                "external_gaia_source_id": gaia_source_id,
            }
        )

    object_coord = _object_coordinate(record)
    coordinate_separations: dict[str, float] = {}
    if object_coord is not None:
        for provider_name, provider in (("simbad", simbad_provider), ("gaia_dr3", gaia_provider)):
            provider_coord = _provider_coordinate(provider)
            if provider_coord is None:
                continue
            separation = round(float(provider_coord.separation(object_coord).arcsec), 6)
            coordinate_separations[provider_name] = separation
            if separation > ENRICHMENT_RADIUS_ARCSEC:
                warnings.append(
                    {
                        "type": f"{provider_name}_far_from_literature_coordinates",
                        "message": "External coordinates are farther than the enrichment match radius from literature coordinates",
                        "separation_arcsec": separation,
                    }
                )

    return (
        {
            "queried_identifiers": identifiers,
            "simbad_alias_matches": alias_matches,
            "simbad_identifier_match": bool(normalized_ids and alias_matches),
            "gaia_source_id_match": gaia_source_matches,
            "coordinate_separations_arcsec": coordinate_separations,
            "value_comparisons": _value_comparisons(record, simbad_provider, gaia_provider),
        },
        warnings,
    )


def _status_from_providers(simbad_provider: dict[str, Any], gaia_provider: dict[str, Any], warnings: list[dict[str, Any]]) -> str:
    matched = [
        provider
        for provider in (simbad_provider, gaia_provider)
        if isinstance(provider, dict) and provider.get("status") == "matched"
    ]
    errors = [warning for warning in warnings if str(warning.get("type") or "").endswith("_query_failed")]
    if matched and errors:
        return "partial"
    if matched:
        return "success"
    if errors:
        return "failed"
    return "not_found"


def enrich_object_records(
    object_records: list[dict[str, Any]],
    *,
    mode: str,
    clients: EnrichmentClients | None = None,
    queried_at: str | None = None,
) -> list[dict[str, Any]]:
    """Return object records with an external_enrichment section."""
    if mode not in ENRICHMENT_MODES:
        raise ValueError(f"unknown enrichment mode: {mode}")
    queried_at = queried_at or now_timestamp()
    records = [dict(record) for record in object_records]
    if mode == "off":
        for record in records:
            record["external_enrichment"] = disabled_enrichment()
        return records

    try:
        clients = clients or AstroqueryCatalogClients()
    except Exception as exc:
        if mode == "required":
            raise EnrichmentError(str(exc)) from exc
        message = f"{type(exc).__name__}: {exc}"
        for record in records:
            record["external_enrichment"] = failed_enrichment(message, queried_at=queried_at)
        return records

    try:
        return _enrich_with_clients(records, clients=clients, mode=mode, queried_at=queried_at)
    except Exception as exc:
        if mode == "required":
            raise EnrichmentError(f"{type(exc).__name__}: {exc}") from exc
        message = f"{type(exc).__name__}: {exc}"
        for record in records:
            record["external_enrichment"] = failed_enrichment(message, queried_at=queried_at)
        return records


def _query_provider(
    mode: str,
    warning_type: str,
    warnings_by_object: dict[str, list[dict[str, Any]]],
    object_ids: list[str],
    query_fn: Any,
    *args: Any,
) -> QueryRows:
    try:
        return rows_from_query_result(query_fn(*args))
    except Exception as exc:
        if mode == "required":
            raise EnrichmentError(f"{warning_type}: {type(exc).__name__}: {exc}") from exc
        warning = {"type": warning_type, "message": f"{type(exc).__name__}: {exc}"}
        for object_id in object_ids:
            warnings_by_object.setdefault(object_id, []).append(dict(warning))
        return QueryRows(rows=[], units={})


def _enrich_with_clients(
    records: list[dict[str, Any]],
    *,
    clients: EnrichmentClients,
    mode: str,
    queried_at: str,
) -> list[dict[str, Any]]:
    identifiers_by_object = {
        str(record.get("object_id") or ""): _candidate_identifier_values(record) for record in records
    }
    coordinates_by_object = {
        str(record.get("object_id") or ""): coordinate
        for record in records
        if (coordinate := _object_coordinate(record)) is not None
    }
    warnings_by_object: dict[str, list[dict[str, Any]]] = {str(record.get("object_id") or ""): [] for record in records}

    all_identifiers = _unique_preserve_order(
        [identifier for identifiers in identifiers_by_object.values() for identifier in identifiers]
    )
    object_ids = [str(record.get("object_id") or "") for record in records]
    simbad_identifier_result = _query_provider(
        mode,
        "simbad_identifier_query_failed",
        warnings_by_object,
        object_ids,
        clients.query_simbad_by_identifiers,
        all_identifiers,
    )
    simbad_rows_by_object: dict[str, tuple[dict[str, Any], str]] = {}
    simbad_claims: dict[str, list[str]] = {}
    for row in simbad_identifier_result.rows:
        row_key = str(row.get("oid") or row.get("main_id") or "")
        matched_objects = [
            object_id
            for object_id, identifiers in identifiers_by_object.items()
            if object_id and _row_matches_object_identifiers(row, identifiers)
        ]
        for object_id in matched_objects:
            simbad_rows_by_object.setdefault(object_id, (row, "identifier"))
        if row_key and len(matched_objects) > 1:
            simbad_claims.setdefault(row_key, []).extend(matched_objects)

    unresolved_simbad = [
        ObjectQueryCoordinate(object_id, coordinate)
        for object_id, coordinate in coordinates_by_object.items()
        if object_id not in simbad_rows_by_object
    ]
    simbad_region_result = _query_provider(
        mode,
        "simbad_region_query_failed",
        warnings_by_object,
        [item.object_id for item in unresolved_simbad],
        clients.query_simbad_by_regions,
        unresolved_simbad,
    )
    for item in unresolved_simbad:
        row, separation, match_count = _nearest_row_for_coordinate(simbad_region_result.rows, item.coordinate)
        if row is not None:
            simbad_rows_by_object[item.object_id] = (row, "coordinates")
            if separation is not None:
                warnings_by_object[item.object_id].append(
                    {
                        "type": "simbad_coordinate_match",
                        "message": "SIMBAD object matched by coordinates rather than identifier",
                        "separation_arcsec": round(separation, 6),
                    }
                )
            if match_count > 1:
                warnings_by_object[item.object_id].append(
                    {
                        "type": "multiple_simbad_coordinate_matches",
                        "message": "Multiple SIMBAD objects fall within the enrichment match radius; nearest row selected",
                        "match_count": match_count,
                    }
                )

    for simbad_key, claimed_objects in simbad_claims.items():
        claimed_unique = _unique_preserve_order(claimed_objects)
        if len(claimed_unique) <= 1:
            continue
        for object_id in claimed_unique:
            warnings_by_object[object_id].append(
                {
                    "type": "external_simbad_duplicate_object_match",
                    "message": "One SIMBAD object matched multiple Stella object records; review object merge inputs",
                    "simbad_object_key": simbad_key,
                    "matched_object_ids": claimed_unique,
                }
            )

    source_ids_by_object = {str(record.get("object_id") or ""): _object_gaia_source_numbers(record) for record in records}
    for object_id, (simbad_row, _match_kind) in simbad_rows_by_object.items():
        simbad_gaia_source_ids = []
        for alias in _aliases_from_simbad_row(simbad_row):
            match = GAIA_SOURCE_ID_RE.match(" ".join(str(alias or "").strip().split()))
            if match and match.group(1).upper() in {"DR3", "EDR3"}:
                simbad_gaia_source_ids.append(match.group(2))
        if simbad_gaia_source_ids:
            source_ids_by_object[object_id] = _unique_preserve_order(
                [*source_ids_by_object.get(object_id, []), *simbad_gaia_source_ids]
            )
    all_source_ids = _unique_preserve_order(
        [source_id for source_ids in source_ids_by_object.values() for source_id in source_ids]
    )
    gaia_id_result = _query_provider(
        mode,
        "gaia_source_id_query_failed",
        warnings_by_object,
        object_ids,
        clients.query_gaia_by_source_ids,
        all_source_ids,
    )
    gaia_rows_by_source_id = {str(row.get("source_id") or ""): row for row in gaia_id_result.rows if row.get("source_id")}
    gaia_rows_by_object: dict[str, tuple[dict[str, Any], str]] = {}
    for object_id, source_ids in source_ids_by_object.items():
        for source_id in source_ids:
            row = gaia_rows_by_source_id.get(source_id)
            if row is not None:
                gaia_rows_by_object[object_id] = (row, "source_id")
                break

    unresolved_gaia = [
        ObjectQueryCoordinate(object_id, coordinate)
        for object_id, coordinate in coordinates_by_object.items()
        if object_id not in gaia_rows_by_object
    ]
    gaia_region_result = _query_provider(
        mode,
        "gaia_region_query_failed",
        warnings_by_object,
        [item.object_id for item in unresolved_gaia],
        clients.query_gaia_by_regions,
        unresolved_gaia,
    )
    for item in unresolved_gaia:
        row, separation, match_count = _nearest_row_for_coordinate(gaia_region_result.rows, item.coordinate)
        if row is not None:
            gaia_rows_by_object[item.object_id] = (row, "coordinates")
            if separation is not None:
                warnings_by_object[item.object_id].append(
                    {
                        "type": "gaia_coordinate_match",
                        "message": "Gaia DR3 source matched by coordinates rather than literature Gaia source id",
                        "separation_arcsec": round(separation, 6),
                    }
                )
            if match_count > 1:
                warnings_by_object[item.object_id].append(
                    {
                        "type": "multiple_gaia_coordinate_matches",
                        "message": "Multiple Gaia DR3 sources fall within the enrichment match radius; nearest row selected",
                        "match_count": match_count,
                    }
                )

    for record in records:
        object_id = str(record.get("object_id") or "")
        simbad_row, simbad_match = simbad_rows_by_object.get(object_id, (None, ""))
        gaia_row, gaia_match = gaia_rows_by_object.get(object_id, (None, ""))
        simbad_provider = _simbad_provider(simbad_row, simbad_identifier_result.units | simbad_region_result.units, matched_by=simbad_match)
        gaia_provider = _gaia_provider(gaia_row, gaia_id_result.units | gaia_region_result.units, matched_by=gaia_match)
        verification, verification_warnings = _build_verification(record, simbad_provider, gaia_provider)
        warnings = [*warnings_by_object.get(object_id, []), *verification_warnings]
        record["external_enrichment"] = {
            "status": _status_from_providers(simbad_provider, gaia_provider, warnings),
            "queried_at": queried_at,
            "providers": {
                "simbad": simbad_provider,
                "gaia_dr3": gaia_provider,
            },
            "verification": verification,
            "warnings": warnings,
        }
    return records
