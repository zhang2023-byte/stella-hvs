"""Calculate object-level HVS Galactocentric dynamics from Gaia DR3 astrometry."""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np

from stella.lit.catalog_review import read_json, write_json
from stella.lit.hvs_candidate_catalog import CANDIDATES_DIRNAME, OBJECT_SCHEMA_VERSION


DYNAMICS_SCHEMA_VERSION = "stella.hvs_dynamics.v0.1"
DEFAULT_MCMC_SAMPLES = 10000
DEFAULT_HP_LEVEL = 5
DEFAULT_PRIOR_PATH = Path(__file__).resolve().parent / "data" / "prior_summary.csv"
EXTERNAL_CACHE_MODES = ("required", "refresh")
GAIA_SOURCE_ID_RE = re.compile(r"^Gaia\s+((?:E)?DR\d+)\s+(\d+)$", re.IGNORECASE)
NUMERIC_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")

SOLAR_PROVENANCE = {
    "galcen_distance_kpc": 8.122,
    "z_sun_kpc": 0.0208,
    "galcen_v_sun_kms": [11.1, 245.0, 7.25],
    "references": [
        "GRAVITY Collaboration 2018",
        "Bennett & Bovy 2019",
        "Schoenrich et al. 2010",
        "McMillan 2017",
    ],
}
POTENTIAL_PROVENANCE = {
    "name": "McMillan17",
    "implementation": "galpy",
    "escape_velocity_evaluation": "per-object RegularGridInterpolator over sampled R,z range",
}
MCMILLAN17_RO_KPC = 8.21
MCMILLAN17_VO_KMS = 233.1

GAIA_REQUIRED_ASTROMETRY = (
    "source_id",
    "ra",
    "dec",
    "parallax",
    "parallax_error",
    "pmra",
    "pmra_error",
    "pmdec",
    "pmdec_error",
)
ZERO_POINT_BASE_COLUMNS = (
    "phot_g_mean_mag",
    "ecl_lat",
    "astrometric_params_solved",
)
GAIA_QUERY_COLUMNS = (
    "source_id",
    "designation",
    "ra",
    "dec",
    "parallax",
    "parallax_error",
    "pmra",
    "pmra_error",
    "pmdec",
    "pmdec_error",
    "parallax_pmra_corr",
    "parallax_pmdec_corr",
    "pmra_pmdec_corr",
    "phot_g_mean_mag",
    "nu_eff_used_in_astrometry",
    "pseudocolour",
    "ecl_lat",
    "astrometric_params_solved",
)


class DynamicsError(RuntimeError):
    """Raised when a strict dynamics calculation cannot continue."""


@dataclass(frozen=True)
class QueryRows:
    rows: list[dict[str, Any]]
    units: dict[str, str]


class DynamicsClients(Protocol):
    def query_gaia_by_source_ids(self, source_ids: list[str]) -> QueryRows:
        ...


@dataclass(frozen=True)
class GaiaSourceId:
    release: str
    source_id: str
    raw: str

    @property
    def release_family(self) -> str:
        return "DR3" if self.release in {"DR3", "EDR3"} else self.release

    @property
    def canonical_value(self) -> str:
        return f"Gaia {self.release_family} {self.source_id}"


@dataclass(frozen=True)
class RadialVelocityChoice:
    value: float | None
    error: float | None
    source: str
    source_detail: str
    bibcode: str = ""
    lower_limit: bool = False
    warning: str = ""


@dataclass(frozen=True)
class AstrometryInput:
    gaia_source_id: str
    source_id_number: str
    row: dict[str, Any]
    corrected_parallax_mas: float
    zero_point_mas: float
    parallax_error_mas: float
    ra_deg: float
    dec_deg: float
    pmra_masyr: float
    pmdec_masyr: float
    pmra_error_masyr: float
    pmdec_error_masyr: float
    row_source: str = "external_enrichment.providers.gaia_dr3.raw_columns"


@dataclass(frozen=True)
class DistancePrior:
    alpha: float
    beta: float
    length_kpc: float
    healpix: int


@dataclass(frozen=True)
class KinematicArrays:
    total_velocity_kms: np.ndarray
    escape_velocity_kms: np.ndarray
    galactocentric_radius_kpc: np.ndarray
    heliocentric_distance_kpc: np.ndarray
    radial_velocity_kms: np.ndarray


def now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError("expected True or False")


def parse_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if hasattr(value, "mask") and bool(getattr(value, "mask", False)):
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
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


def json_scalar(value: Any) -> Any:
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


def rows_from_query_result(result: Any) -> QueryRows:
    if result is None:
        return QueryRows(rows=[], units={})
    if isinstance(result, QueryRows):
        return result
    if isinstance(result, list):
        return QueryRows(rows=[{str(key): json_scalar(value) for key, value in row.items()} for row in result], units={})
    if isinstance(result, tuple) and len(result) == 2:
        rows, units = result
        if isinstance(rows, list) and isinstance(units, dict):
            return QueryRows(
                rows=[{str(key): json_scalar(value) for key, value in row.items()} for row in rows],
                units={str(key): str(value) for key, value in units.items()},
            )

    colnames = list(getattr(result, "colnames", []) or [])
    units: dict[str, str] = {}
    for name in colnames:
        unit = getattr(result[name], "unit", None)
        if unit:
            units[str(name)] = str(unit)
    rows: list[dict[str, Any]] = []
    for row in result:
        rows.append({str(name): json_scalar(row[name]) for name in colnames})
    return QueryRows(rows=rows, units=units)


def parse_gaia_source_id(value: Any) -> GaiaSourceId | None:
    text = " ".join(str(value or "").strip().split())
    match = GAIA_SOURCE_ID_RE.match(text)
    if not match:
        return None
    return GaiaSourceId(release=match.group(1).upper(), source_id=match.group(2), raw=text)


def _unique_preserve_order(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").strip().split())
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            output.append(text)
    return output


def object_identifier_values(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    canonical = record.get("canonical_identifier") if isinstance(record.get("canonical_identifier"), dict) else {}
    for value in (canonical.get("value"), record.get("object_id")):
        if value:
            values.append(str(value))
    for source in record.get("sources") or []:
        if not isinstance(source, dict):
            continue
        for key in ("gaia_source_id", "paper_candidate_id", "record_id"):
            if source.get(key):
                values.append(str(source[key]))
    for candidate in record.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
        for key in ("gaia_source_id", "paper_candidate_id", "record_id"):
            if identifiers.get(key):
                values.append(str(identifiers[key]))
        values.extend(str(value) for value in identifiers.get("all") or [] if str(value).strip())
    return _unique_preserve_order(values)


def select_gaia_dr3_source(record: dict[str, Any]) -> tuple[GaiaSourceId | None, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    parsed: list[GaiaSourceId] = []
    for value in object_identifier_values(record):
        gaia_id = parse_gaia_source_id(value)
        if gaia_id is not None and gaia_id.release_family == "DR3":
            parsed.append(gaia_id)
    parsed = list({item.source_id: item for item in parsed}.values())
    if not parsed:
        return None, warnings

    canonical = record.get("canonical_identifier") if isinstance(record.get("canonical_identifier"), dict) else {}
    canonical_parsed = parse_gaia_source_id(canonical.get("value"))
    if canonical_parsed is not None and canonical_parsed.release_family == "DR3":
        selected = canonical_parsed
    else:
        selected = parsed[0]
    if len({item.source_id for item in parsed}) > 1:
        warnings.append(
            {
                "type": "multiple_gaia_dr3_source_ids",
                "message": "Multiple DR3-family Gaia source ids are present; selected the canonical/first source id.",
                "gaia_source_ids": [item.canonical_value for item in parsed],
            }
        )
    return selected, warnings


def cached_gaia_dr3_source(record: dict[str, Any]) -> GaiaSourceId | None:
    external = record.get("external_enrichment") if isinstance(record.get("external_enrichment"), dict) else {}
    providers = external.get("providers") if isinstance(external.get("providers"), dict) else {}
    gaia = providers.get("gaia_dr3") if isinstance(providers.get("gaia_dr3"), dict) else {}
    if gaia.get("status") != "matched":
        return None
    raw = gaia.get("raw_columns") if isinstance(gaia.get("raw_columns"), dict) else {}
    source_id = str(raw.get("source_id") or gaia.get("source_id") or "").strip()
    if not source_id.isdigit():
        return None
    return GaiaSourceId(release="DR3", source_id=source_id, raw=f"Gaia DR3 {source_id}")


def _quantity_candidates(record: dict[str, Any]) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    candidates = [item for item in record.get("candidates") or [] if isinstance(item, dict)]
    sources = {
        str(item.get("source") or ""): item
        for item in record.get("sources") or []
        if isinstance(item, dict) and item.get("source")
    }
    output: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for index, candidate in enumerate(candidates):
        source = sources.get(str(candidate.get("source") or ""), {})
        output.append((index, candidate, source if isinstance(source, dict) else {}))
    return output


def _rv_choice_from_quantity(quantity: dict[str, Any], source: dict[str, Any], index: int) -> RadialVelocityChoice | None:
    value = parse_float(quantity.get("value"))
    if value is None:
        return None
    error = parse_float(quantity.get("error"))
    warning = "" if error is not None and error > 0 else "radial_velocity_uncertainty_missing"
    paper = source.get("paper") if isinstance(source.get("paper"), dict) else {}
    source_detail = " ".join(
        part
        for part in (
            str(source.get("source_json_path") or ""),
            str(source.get("record_id") or ""),
            str(paper.get("arxiv_id") or ""),
        )
        if part
    )
    return RadialVelocityChoice(
        value=value,
        error=error if error is not None and error > 0 else None,
        source="literature",
        source_detail=source_detail or f"candidate[{index}]",
        warning=warning,
    )


def select_literature_radial_velocity(record: dict[str, Any]) -> RadialVelocityChoice | None:
    choices: list[tuple[int, RadialVelocityChoice]] = []
    for index, candidate, source in _quantity_candidates(record):
        core = candidate.get("core") if isinstance(candidate.get("core"), dict) else {}
        observed = core.get("observed_phase_space") if isinstance(core.get("observed_phase_space"), dict) else {}
        rv = observed.get("radial_velocity")
        if isinstance(rv, dict):
            choice = _rv_choice_from_quantity(rv, source, index)
            if choice is not None:
                choices.append((index, choice))
        for spectrum in candidate.get("spectroscopy") or []:
            if not isinstance(spectrum, dict):
                continue
            if spectrum.get("measurement_type") != "radial_velocity_follow_up":
                continue
            choice = _rv_choice_from_quantity(spectrum, source, index)
            if choice is not None:
                choices.append((index, choice))
    if not choices:
        return None
    with_errors = [(index, choice) for index, choice in choices if choice.error is not None]
    if with_errors:
        return sorted(with_errors, key=lambda item: (float(item[1].error or math.inf), item[0]))[0][1]
    return choices[0][1]


def cached_gaia_row(record: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    external = record.get("external_enrichment") if isinstance(record.get("external_enrichment"), dict) else {}
    providers = external.get("providers") if isinstance(external.get("providers"), dict) else {}
    gaia = providers.get("gaia_dr3") if isinstance(providers.get("gaia_dr3"), dict) else {}
    if gaia.get("status") != "matched":
        return None
    raw = gaia.get("raw_columns") if isinstance(gaia.get("raw_columns"), dict) else {}
    if not raw:
        return None
    raw_source_id = str(raw.get("source_id") or gaia.get("source_id") or "").strip()
    if raw_source_id and raw_source_id != source_id:
        return None
    return dict(raw)


def select_radial_velocity(
    record: dict[str, Any],
    clients: DynamicsClients | None = None,
    *,
    fail_on_query_error: bool = False,
) -> tuple[RadialVelocityChoice, list[dict[str, Any]]]:
    _ = clients, fail_on_query_error
    warnings: list[dict[str, Any]] = []
    literature = select_literature_radial_velocity(record)
    if literature is not None:
        if literature.warning:
            warnings.append({"type": literature.warning, "message": "Literature radial velocity has no usable uncertainty; RV is held fixed."})
        return literature, warnings

    warnings.append(
        {
            "type": "minimum_grf_velocity_assumption",
            "message": "No literature RV was available; the missing radial velocity is chosen per posterior sample to minimize Galactocentric rest-frame speed. SIMBAD RV is intentionally ignored for dynamics.",
        }
    )
    return RadialVelocityChoice(
        value=None,
        error=None,
        source="minimum_grf_velocity",
        source_detail="Boubert et al. 2018 missing-RV convention",
        lower_limit=True,
    ), warnings


def _as_required_float(row: dict[str, Any], key: str) -> float | None:
    value = parse_float(row.get(key))
    if value is None or not math.isfinite(value):
        return None
    return value


def select_gaia_row(rows: QueryRows, source_id: str) -> dict[str, Any] | None:
    for row in rows.rows:
        if str(row.get("source_id") or "").strip() == source_id:
            return row
    return rows.rows[0] if len(rows.rows) == 1 else None


def validate_gaia_astrometry_row(row: dict[str, Any]) -> str:
    for key in GAIA_REQUIRED_ASTROMETRY:
        value = _as_required_float(row, key)
        if value is None:
            return f"missing or invalid Gaia astrometry field: {key}"
    for key in ("parallax_error", "pmra_error", "pmdec_error"):
        value = _as_required_float(row, key)
        if value is None or value <= 0:
            return f"missing or non-positive Gaia uncertainty field: {key}"
    return ""


def _zero_point_value_input(row: dict[str, Any], key: str) -> float | None:
    value = parse_float(row.get(key))
    return value if value is not None and math.isfinite(value) else None


def corrected_parallax(row: dict[str, Any], *, zero_point_module: Any | None = None) -> tuple[float | None, float | None, str]:
    missing = [key for key in ZERO_POINT_BASE_COLUMNS if key not in row]
    if missing:
        return None, None, "missing Gaia zero-point columns: " + ", ".join(missing)

    g_mag = _zero_point_value_input(row, "phot_g_mean_mag")
    ecl_lat = _zero_point_value_input(row, "ecl_lat")
    astrometric_params_solved = _zero_point_value_input(row, "astrometric_params_solved")
    parallax = _zero_point_value_input(row, "parallax")
    if g_mag is None or ecl_lat is None or astrometric_params_solved is None or parallax is None:
        return None, None, "missing required Gaia zero-point values"

    solution = int(astrometric_params_solved)
    nu_eff = _zero_point_value_input(row, "nu_eff_used_in_astrometry")
    pseudocolour = _zero_point_value_input(row, "pseudocolour")
    if solution == 31 and nu_eff is None:
        return None, None, "missing nu_eff_used_in_astrometry for 5p solution"
    if solution == 95 and pseudocolour is None:
        return None, None, "missing pseudocolour for 6p solution"
    if solution not in {31, 95}:
        return None, None, f"unsupported astrometric_params_solved value: {solution}"

    try:
        if zero_point_module is None:
            from zero_point import zpt as zero_point_module  # type: ignore[no-redef]
        zero_point_module.load_tables()
        values = zero_point_module.get_zpt(
            np.array([g_mag], dtype=float),
            np.array([nu_eff if nu_eff is not None else np.nan], dtype=float),
            np.array([pseudocolour if pseudocolour is not None else np.nan], dtype=float),
            np.array([ecl_lat], dtype=float),
            np.array([solution], dtype=int),
        )
        zero_point = float(np.asarray(values, dtype=float).reshape(-1)[0])
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}"
    if not math.isfinite(zero_point):
        return None, None, "zero-point correction is not finite"
    return parallax - zero_point, zero_point, ""


def build_astrometry_input(gaia_source_id: GaiaSourceId, row: dict[str, Any], *, zero_point_module: Any | None = None) -> tuple[AstrometryInput | None, str]:
    validation_error = validate_gaia_astrometry_row(row)
    if validation_error:
        return None, validation_error
    parallax_corrected, zero_point, zero_point_error = corrected_parallax(row, zero_point_module=zero_point_module)
    if parallax_corrected is None or zero_point is None:
        return None, zero_point_error
    parallax_error = float(_as_required_float(row, "parallax_error") or math.nan)
    if not math.isfinite(parallax_error) or parallax_error <= 0:
        return None, "missing or non-positive parallax_error"
    if parallax_corrected / parallax_error <= 5:
        return None, "parallax uncertainty too large"
    return (
        AstrometryInput(
            gaia_source_id=gaia_source_id.canonical_value,
            source_id_number=gaia_source_id.source_id,
            row=row,
            corrected_parallax_mas=parallax_corrected,
            zero_point_mas=zero_point,
            parallax_error_mas=parallax_error,
            ra_deg=float(_as_required_float(row, "ra") or math.nan),
            dec_deg=float(_as_required_float(row, "dec") or math.nan),
            pmra_masyr=float(_as_required_float(row, "pmra") or math.nan),
            pmdec_masyr=float(_as_required_float(row, "pmdec") or math.nan),
            pmra_error_masyr=float(_as_required_float(row, "pmra_error") or math.nan),
            pmdec_error_masyr=float(_as_required_float(row, "pmdec_error") or math.nan),
            row_source=str(row.get("_stella_row_source") or "external_enrichment.providers.gaia_dr3.raw_columns"),
        ),
        "",
    )


def parallax_quality_payload(
    gaia_source_id: GaiaSourceId,
    row: dict[str, Any],
    *,
    zero_point_module: Any | None = None,
) -> dict[str, Any] | None:
    parallax_corrected, zero_point, _zero_point_error = corrected_parallax(row, zero_point_module=zero_point_module)
    parallax_error = _as_required_float(row, "parallax_error")
    if parallax_corrected is None or zero_point is None or parallax_error is None or parallax_error <= 0:
        return None
    return {
        "provider": str(row.get("_stella_row_source") or "external_enrichment.providers.gaia_dr3.raw_columns"),
        "source_id": gaia_source_id.source_id,
        "parallax_mas": parse_float(row.get("parallax")),
        "zero_point_mas": zero_point,
        "corrected_parallax_mas": parallax_corrected,
        "parallax_error_mas": parallax_error,
        "corrected_parallax_over_error": parallax_corrected / parallax_error,
    }


def _skip_record(
    reason: str,
    *,
    generated_at: str,
    warnings: list[dict[str, Any]] | None = None,
    gaia_source_id: str = "",
    provenance_extra: dict[str, Any] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = {
        "gaia_astrometry": {"provider": "external_enrichment.providers.gaia_dr3.raw_columns", "source_id": gaia_source_id},
        "potential": POTENTIAL_PROVENANCE,
        "solar": SOLAR_PROVENANCE,
    }
    if provenance_extra:
        provenance.update(provenance_extra)
    record = {
        "schema_version": DYNAMICS_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "skipped",
        "status_reason": reason,
        "gaia_source_id": gaia_source_id,
        "warnings": warnings or [],
        "provenance": provenance,
    }
    if extra_fields:
        record.update(extra_fields)
    return record


@lru_cache(maxsize=4)
def _prior_rows(prior_path: str) -> dict[int, DistancePrior]:
    path = Path(prior_path)
    rows: dict[int, DistancePrior] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                healpix = int(float(row["healpix"]))
                rows[healpix] = DistancePrior(
                    alpha=float(row["GGDalpha"]),
                    beta=float(row["GGDbeta"]),
                    length_kpc=1e-3 * float(row["GGDrlen"]),
                    healpix=healpix,
                )
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def healpix_from_source_id(source_id: str, *, hp_level: int = DEFAULT_HP_LEVEL) -> int:
    return int(math.floor(int(source_id) / (2**35 * 4 ** (12 - hp_level))))


def distance_prior_for_source(source_id: str, *, prior_path: Path = DEFAULT_PRIOR_PATH, hp_level: int = DEFAULT_HP_LEVEL) -> DistancePrior | None:
    healpix = healpix_from_source_id(source_id, hp_level=hp_level)
    prior = _prior_rows(str(prior_path)).get(healpix)
    if prior is None or prior.length_kpc <= 0 or not all(math.isfinite(v) for v in (prior.alpha, prior.beta, prior.length_kpc)):
        return None
    return prior


def log_ggd_distance_prior(distance_kpc: float, prior: DistancePrior) -> float:
    if distance_kpc <= 0:
        return -math.inf
    return (
        -((distance_kpc / prior.length_kpc) ** prior.alpha)
        + prior.beta * math.log(distance_kpc)
        + math.log(prior.alpha)
        - (prior.beta + 1) * math.log(prior.length_kpc)
        - math.lgamma((prior.beta + 1) / prior.alpha)
    )


def log_multivariate_gaussian(x: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> float:
    diff = x - mu
    try:
        solved = np.linalg.solve(cov, diff)
    except np.linalg.LinAlgError:
        solved = np.linalg.solve(cov + np.eye(cov.shape[0]) * 1e-12, diff)
    return float(-0.5 * np.dot(diff, solved))


def covariance_matrix(astrometry: AstrometryInput, rv: RadialVelocityChoice) -> tuple[list[str], np.ndarray, list[dict[str, Any]]]:
    fields = ["parallax", "pmra", "pmdec"]
    errors = [astrometry.parallax_error_mas, astrometry.pmra_error_masyr, astrometry.pmdec_error_masyr]
    row = astrometry.row
    corr_keys = {
        (0, 1): "parallax_pmra_corr",
        (0, 2): "parallax_pmdec_corr",
        (1, 2): "pmra_pmdec_corr",
    }
    warnings: list[dict[str, Any]] = []
    cov = np.diag(np.square(errors))
    for (left, right), key in corr_keys.items():
        corr = parse_float(row.get(key))
        if corr is None:
            corr = 0.0
            warnings.append({"type": "gaia_correlation_missing", "message": f"{key} missing; covariance term set to zero."})
        cov[left, right] = corr * errors[left] * errors[right]
        cov[right, left] = cov[left, right]
    if rv.error is not None and rv.error > 0:
        fields.append("radial_velocity")
        new_cov = np.zeros((4, 4), dtype=float)
        new_cov[:3, :3] = cov
        new_cov[3, 3] = rv.error**2
        cov = new_cov
    return fields, cov, warnings


def draw_mcmc_samples(
    astrometry: AstrometryInput,
    rv: RadialVelocityChoice,
    *,
    samples: int = DEFAULT_MCMC_SAMPLES,
    seed: int | None = None,
    prior_path: Path = DEFAULT_PRIOR_PATH,
) -> dict[str, np.ndarray]:
    if samples <= 0:
        raise ValueError("samples must be positive")
    try:
        import emcee
    except Exception as exc:  # pragma: no cover - depends on runtime env.
        raise DynamicsError(f"emcee import failed: {type(exc).__name__}: {exc}") from exc

    prior = distance_prior_for_source(astrometry.source_id_number, prior_path=prior_path)
    if prior is None:
        raise DynamicsError("distance prior not available")

    rv_value = 0.0 if rv.value is None else float(rv.value)
    fields, cov, _warnings = covariance_matrix(astrometry, rv)
    try:
        inv_cov = np.linalg.inv(cov)
    except np.linalg.LinAlgError:
        inv_cov = np.linalg.inv(cov + np.eye(cov.shape[0]) * 1e-12)
    values = {
        "parallax": astrometry.corrected_parallax_mas,
        "pmra": astrometry.pmra_masyr,
        "pmdec": astrometry.pmdec_masyr,
        "radial_velocity": rv_value,
    }
    pos = np.array([values[field] for field in fields], dtype=float)
    rng = np.random.default_rng(seed)
    if seed is not None:
        np.random.seed(seed)
    ndim = len(fields)
    nwalkers = max(16, 4 * ndim)
    scale = np.maximum(np.abs(pos) * 3e-3, np.sqrt(np.maximum(np.diag(cov), 1e-12)) * 0.05)
    p0 = pos + scale * rng.normal(size=(nwalkers, ndim))
    p0[:, 0] = np.maximum(p0[:, 0], astrometry.parallax_error_mas * 0.1)
    prior_log_norm = (
        math.log(prior.alpha)
        - (prior.beta + 1) * math.log(prior.length_kpc)
        - math.lgamma((prior.beta + 1) / prior.alpha)
    )

    def log_prob(theta: np.ndarray) -> float:
        parallax = float(theta[0])
        if parallax <= 0:
            return -math.inf
        distance = 1.0 / parallax
        prior_value = -((distance / prior.length_kpc) ** prior.alpha) + prior.beta * math.log(distance) + prior_log_norm
        if not math.isfinite(prior_value):
            return -math.inf
        diff = pos - theta
        return float(prior_value - 0.5 * np.dot(diff, inv_cov @ diff))

    sampler = emcee.EnsembleSampler(nwalkers, ndim, log_prob)
    state = sampler.run_mcmc(p0, 500, progress=False)
    sampler.reset()
    production_steps = max(1, math.ceil(samples / nwalkers))
    sampler.run_mcmc(state, production_steps, progress=False)
    flat = sampler.get_chain(flat=True)
    while len(flat) < samples:
        state = sampler.run_mcmc(None, 1, progress=False)
        flat = sampler.get_chain(flat=True)
    selected = np.array(flat[:samples], dtype=float)

    result = {
        "parallax": selected[:, fields.index("parallax")],
        "pmra": selected[:, fields.index("pmra")],
        "pmdec": selected[:, fields.index("pmdec")],
        "radial_velocity": np.full(samples, rv_value, dtype=float),
    }
    if "radial_velocity" in fields:
        result["radial_velocity"] = selected[:, fields.index("radial_velocity")]
    return result


def galactocentric_frame() -> Any:
    try:
        import astropy.units as u
        from astropy.coordinates import CartesianDifferential, Galactocentric
    except Exception as exc:  # pragma: no cover - depends on runtime env.
        raise DynamicsError(f"astropy import failed: {type(exc).__name__}: {exc}") from exc
    return Galactocentric(
        galcen_distance=SOLAR_PROVENANCE["galcen_distance_kpc"] * u.kpc,
        z_sun=SOLAR_PROVENANCE["z_sun_kpc"] * u.kpc,
        galcen_v_sun=CartesianDifferential(SOLAR_PROVENANCE["galcen_v_sun_kms"] * u.km / u.s),
    )


def _skycoord_from_samples(astrometry: AstrometryInput, posterior: dict[str, np.ndarray], rv_samples: np.ndarray) -> Any:
    try:
        import astropy.units as u
        from astropy.coordinates import SkyCoord
    except Exception as exc:  # pragma: no cover - depends on runtime env.
        raise DynamicsError(f"astropy import failed: {type(exc).__name__}: {exc}") from exc
    parallax = np.asarray(posterior["parallax"], dtype=float)
    distance_kpc = 1.0 / parallax
    return SkyCoord(
        ra=np.full(len(parallax), astrometry.ra_deg) * u.deg,
        dec=np.full(len(parallax), astrometry.dec_deg) * u.deg,
        distance=distance_kpc * u.kpc,
        pm_ra_cosdec=np.asarray(posterior["pmra"], dtype=float) * u.mas / u.yr,
        pm_dec=np.asarray(posterior["pmdec"], dtype=float) * u.mas / u.yr,
        radial_velocity=np.asarray(rv_samples, dtype=float) * u.km / u.s,
        frame="icrs",
    )


def _velocity_array(gc: Any) -> np.ndarray:
    return np.vstack([gc.v_x.to_value("km/s"), gc.v_y.to_value("km/s"), gc.v_z.to_value("km/s")]).T


def lower_limit_radial_velocity_samples(astrometry: AstrometryInput, posterior: dict[str, np.ndarray]) -> np.ndarray:
    zero = np.zeros(len(posterior["parallax"]), dtype=float)
    one = np.ones(len(posterior["parallax"]), dtype=float)
    frame = galactocentric_frame()
    gc0 = _skycoord_from_samples(astrometry, posterior, zero).transform_to(frame)
    gc1 = _skycoord_from_samples(astrometry, posterior, one).transform_to(frame)
    v0 = _velocity_array(gc0)
    direction = _velocity_array(gc1) - v0
    denom = np.sum(direction * direction, axis=1)
    denom = np.where(denom <= 0, 1.0, denom)
    return -np.sum(direction * v0, axis=1) / denom


def _load_mcmillan17() -> tuple[Any, Callable[..., Any]]:
    try:
        from galpy.potential import evaluatePotentials
    except Exception as exc:  # pragma: no cover - depends on runtime env.
        raise DynamicsError(f"galpy import failed: {type(exc).__name__}: {exc}") from exc
    try:
        from galpy.potential.mwpotentials import McMillan17
    except Exception:
        try:
            from galpy.potential import McMillan17  # type: ignore[no-redef]
        except Exception as exc:  # pragma: no cover - depends on galpy version.
            raise DynamicsError(f"galpy McMillan17 import failed: {type(exc).__name__}: {exc}") from exc
    return McMillan17, evaluatePotentials


@lru_cache(maxsize=1)
def _mcmillan17_phi_inf_internal() -> float:
    potential, evaluate_potentials = _load_mcmillan17()
    return float(
        evaluate_potentials(
            potential,
            1e6 / MCMILLAN17_RO_KPC,
            0.0,
            quantity=False,
            use_physical=False,
        )
    )


def _grid_axis(values: np.ndarray, *, min_points: int = 5) -> np.ndarray:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return np.linspace(0.0, 1.0, min_points)
    low = float(np.min(finite))
    high = float(np.max(finite))
    span = high - low
    if span <= 0:
        pad = max(abs(low) * 1e-6, 1e-4)
    else:
        pad = max(span * 0.05, 1e-4)
    low -= pad
    high += pad
    if low < 0 and np.all(finite >= 0):
        low = 0.0
    return np.linspace(low, high, min_points)


def mcmillan17_escape_velocity_interpolated(radius_kpc: np.ndarray, z_kpc: np.ndarray) -> np.ndarray:
    try:
        from scipy.interpolate import RegularGridInterpolator
    except Exception as exc:  # pragma: no cover - depends on runtime env.
        raise DynamicsError(f"scipy import failed: {type(exc).__name__}: {exc}") from exc
    potential, evaluate_potentials = _load_mcmillan17()
    radius_axis = _grid_axis(radius_kpc)
    z_axis = _grid_axis(z_kpc)
    radius_grid, z_grid = np.meshgrid(radius_axis, z_axis, indexing="ij")
    phi_grid = evaluate_potentials(
        potential,
        radius_grid / MCMILLAN17_RO_KPC,
        z_grid / MCMILLAN17_RO_KPC,
        quantity=False,
        use_physical=False,
    )
    interpolator = RegularGridInterpolator(
        (radius_axis, z_axis),
        np.asarray(phi_grid, dtype=float),
        bounds_error=False,
        fill_value=None,
    )
    phi = interpolator(np.column_stack([radius_kpc, z_kpc]))
    return np.sqrt(2 * (_mcmillan17_phi_inf_internal() - phi)) * MCMILLAN17_VO_KMS


def calculate_kinematic_arrays(astrometry: AstrometryInput, rv: RadialVelocityChoice, posterior: dict[str, np.ndarray]) -> KinematicArrays:
    try:
        import astropy.units as u
    except Exception as exc:  # pragma: no cover - depends on runtime env.
        raise DynamicsError(f"astropy import failed: {type(exc).__name__}: {exc}") from exc
    rv_samples = (
        lower_limit_radial_velocity_samples(astrometry, posterior)
        if rv.lower_limit
        else np.asarray(posterior["radial_velocity"], dtype=float)
    )
    frame = galactocentric_frame()
    gc = _skycoord_from_samples(astrometry, posterior, rv_samples).transform_to(frame)
    total_velocity = np.sqrt(gc.v_x**2 + gc.v_y**2 + gc.v_z**2).to_value(u.km / u.s)
    radius = np.sqrt(gc.x**2 + gc.y**2 + gc.z**2).to_value(u.kpc)
    cylindrical_radius = np.sqrt(gc.x**2 + gc.y**2)
    z = gc.z

    escape_velocity = mcmillan17_escape_velocity_interpolated(
        cylindrical_radius.to_value(u.kpc),
        z.to_value(u.kpc),
    )
    return KinematicArrays(
        total_velocity_kms=np.asarray(total_velocity, dtype=float),
        escape_velocity_kms=np.asarray(escape_velocity, dtype=float),
        galactocentric_radius_kpc=np.asarray(radius, dtype=float),
        heliocentric_distance_kpc=1.0 / np.asarray(posterior["parallax"], dtype=float),
        radial_velocity_kms=np.asarray(rv_samples, dtype=float),
    )


def percentile_summary(values: np.ndarray) -> dict[str, float]:
    p16, p50, p84 = np.percentile(np.asarray(values, dtype=float), [16, 50, 84])
    return {"p16": round(float(p16), 10), "median": round(float(p50), 10), "p84": round(float(p84), 10)}


def beta_distribution_summary(success_count: int, total_count: int) -> dict[str, Any]:
    alpha = success_count + 0.5
    beta = total_count - success_count + 0.5
    summary: dict[str, Any] = {"alpha": alpha, "beta": beta}
    try:
        from scipy.stats import beta as beta_distribution

        distribution = beta_distribution(alpha, beta)
        summary.update(
            {
                "p16": round(float(distribution.ppf(0.16)), 12),
                "median": round(float(distribution.ppf(0.5)), 12),
                "p84": round(float(distribution.ppf(0.84)), 12),
            }
        )
    except Exception:
        summary.update({"mean": round(float(alpha / (alpha + beta)), 12), "summary_method": "mean_only_scipy_unavailable"})
    return summary


def build_computed_dynamics_record(
    *,
    generated_at: str,
    astrometry: AstrometryInput,
    rv: RadialVelocityChoice,
    posterior: dict[str, np.ndarray],
    kinematics: KinematicArrays,
    warnings: list[dict[str, Any]],
    sample_count: int,
) -> dict[str, Any]:
    total_count = int(sample_count)
    unbound = np.asarray(kinematics.total_velocity_kms) > np.asarray(kinematics.escape_velocity_kms)
    unbound_count = int(np.count_nonzero(unbound))
    bound_count = int(total_count - unbound_count)
    p_bound = beta_distribution_summary(bound_count, total_count)
    p_unbound = beta_distribution_summary(unbound_count, total_count)
    raw_unbound_fraction = unbound_count / total_count if total_count else math.nan
    raw_bound_fraction = bound_count / total_count if total_count else math.nan
    beta_median = p_unbound.get("median", p_unbound.get("mean"))
    if isinstance(beta_median, float):
        sanity_delta = abs(beta_median - raw_unbound_fraction)
    else:
        sanity_delta = ""

    return {
        "schema_version": DYNAMICS_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "computed",
        "status_reason": "",
        "gaia_source_id": astrometry.gaia_source_id,
        "radial_velocity_source": {
            "source": rv.source,
            "source_detail": rv.source_detail,
            "value": rv.value if rv.value is not None else "",
            "error": rv.error if rv.error is not None else "",
            "unit": "km/s",
            "bibcode": rv.bibcode,
            "lower_limit": rv.lower_limit,
        },
        "astrometry": {
            "provider": astrometry.row_source,
            "source_id": astrometry.source_id_number,
            "ra_deg": astrometry.ra_deg,
            "dec_deg": astrometry.dec_deg,
            "parallax_mas": parse_float(astrometry.row.get("parallax")),
            "zero_point_mas": astrometry.zero_point_mas,
            "corrected_parallax_mas": astrometry.corrected_parallax_mas,
            "parallax_error_mas": astrometry.parallax_error_mas,
            "pmra_masyr": astrometry.pmra_masyr,
            "pmdec_masyr": astrometry.pmdec_masyr,
        },
        "sampling": {
            "method": "emcee Bayesian kinematics",
            "sample_count": total_count,
            "posterior_fields": ["parallax", "pmra", "pmdec", "radial_velocity"],
            "single_sample_set_for_velocity_probability_and_graveyard": True,
        },
        "posterior": {
            "heliocentric_distance_kpc": percentile_summary(kinematics.heliocentric_distance_kpc),
            "galactocentric_radius_kpc": percentile_summary(kinematics.galactocentric_radius_kpc),
            "radial_velocity_kms": percentile_summary(kinematics.radial_velocity_kms),
        },
        "total_velocity_grf_kms": percentile_summary(kinematics.total_velocity_kms),
        "escape_velocity_kms": percentile_summary(kinematics.escape_velocity_kms),
        "p_bound_beta": p_bound,
        "p_unbound_beta": p_unbound,
        "mc_counts": {
            "sample_count": total_count,
            "bound_count": bound_count,
            "unbound_count": unbound_count,
            "bound_fraction": round(raw_bound_fraction, 12),
            "unbound_fraction": round(raw_unbound_fraction, 12),
            "p_unbound_beta_vs_raw_delta": round(float(sanity_delta), 12) if isinstance(sanity_delta, float) else "",
        },
        "graveyard": unbound_count == 0,
        "lower_limit": rv.lower_limit,
        "warnings": warnings,
        "provenance": {
            "gaia_astrometry": {"provider": astrometry.row_source, "source_id": astrometry.source_id_number},
            "zero_point": {"package": "gaiadr3-zeropoint", "import": "zero_point.zpt"},
            "potential": POTENTIAL_PROVENANCE,
            "solar": SOLAR_PROVENANCE,
            "probability": {
                "reference": "Boubert et al. 2018; Brown, Cai & DasGupta 2001",
                "bound_probability_posterior": "Beta(N_bound + 1/2, N - N_bound + 1/2)",
            },
        },
    }


class AstroqueryDynamicsClients:
    """Official Gaia DR3 TAP query client."""

    def __init__(self) -> None:
        try:
            from astroquery.gaia import GaiaClass
        except Exception as exc:  # pragma: no cover - depends on runtime env.
            raise DynamicsError(f"astroquery import failed: {type(exc).__name__}: {exc}") from exc
        try:
            self._gaia = GaiaClass(show_server_messages=False)
        except TypeError:  # pragma: no cover - older astroquery compatibility.
            self._gaia = GaiaClass()
        try:
            self._gaia.MAIN_GAIA_TABLE = "gaiadr3.gaia_source"
            self._gaia.ROW_LIMIT = -1
        except Exception:
            pass

    def query_gaia_by_source_ids(self, source_ids: list[str]) -> QueryRows:
        values = ", ".join(str(int(value)) for value in source_ids if str(value).isdigit())
        if not values:
            return QueryRows(rows=[], units={})
        columns = ", ".join(GAIA_QUERY_COLUMNS)
        query = f"SELECT {columns} FROM gaiadr3.gaia_source WHERE source_id IN ({values})"
        job = self._gaia.launch_job_async(query, verbose=False)
        return rows_from_query_result(job.get_results())


SampleProvider = Callable[[AstrometryInput, RadialVelocityChoice, int, int | None], dict[str, np.ndarray]]
KinematicsProvider = Callable[[AstrometryInput, RadialVelocityChoice, dict[str, np.ndarray]], KinematicArrays]


def compute_dynamics_for_object(
    record: dict[str, Any],
    *,
    clients: DynamicsClients | None = None,
    samples: int = DEFAULT_MCMC_SAMPLES,
    seed: int | None = None,
    generated_at: str | None = None,
    zero_point_module: Any | None = None,
    sample_provider: SampleProvider | None = None,
    kinematics_provider: KinematicsProvider | None = None,
    fail_on_network_error: bool = False,
    external_cache_mode: str = "required",
    prior_path: Path = DEFAULT_PRIOR_PATH,
) -> dict[str, Any]:
    if external_cache_mode not in EXTERNAL_CACHE_MODES:
        raise ValueError(f"unknown external cache mode: {external_cache_mode}")
    generated_at = generated_at or now_timestamp()
    warnings: list[dict[str, Any]] = []
    selected_gaia, gaia_warnings = select_gaia_dr3_source(record)
    warnings.extend(gaia_warnings)
    if selected_gaia is None:
        selected_gaia = cached_gaia_dr3_source(record)
        if selected_gaia is not None:
            warnings.append(
                {
                    "type": "gaia_source_id_from_external_cache",
                    "message": "No DR3-family Gaia identifier was present; using the matched external_enrichment Gaia DR3 source_id.",
                    "gaia_source_id": selected_gaia.canonical_value,
                }
            )
    if selected_gaia is None:
        return _skip_record("gaia astrometry not available", generated_at=generated_at, warnings=warnings)
    row: dict[str, Any] | None = None
    if external_cache_mode == "required":
        row = cached_gaia_row(record, selected_gaia.source_id)
        if row is None:
            warnings.append(
                {
                    "type": "gaia_external_cache_missing",
                    "message": "external_enrichment.providers.gaia_dr3.raw_columns is missing, incomplete, or does not match the selected source id.",
                }
            )
            return _skip_record(
                "gaia astrometry not available",
                generated_at=generated_at,
                warnings=warnings,
                gaia_source_id=selected_gaia.canonical_value,
            )
        row["_stella_row_source"] = "external_enrichment.providers.gaia_dr3.raw_columns"
    elif clients is None:
        clients = AstroqueryDynamicsClients()

    if external_cache_mode == "refresh":
        try:
            assert clients is not None
            gaia_rows = clients.query_gaia_by_source_ids([selected_gaia.source_id])
        except Exception as exc:
            if fail_on_network_error:
                raise
            warnings.append({"type": "gaia_query_failed", "message": f"{type(exc).__name__}: {exc}"})
            return _skip_record(
                "gaia astrometry not available",
                generated_at=generated_at,
                warnings=warnings,
                gaia_source_id=selected_gaia.canonical_value,
            )
        row = select_gaia_row(gaia_rows, selected_gaia.source_id)
        if row is not None:
            row["_stella_row_source"] = "Gaia DR3 TAP refresh"
    if row is None:
        return _skip_record(
            "gaia astrometry not available",
            generated_at=generated_at,
            warnings=warnings,
            gaia_source_id=selected_gaia.canonical_value,
        )

    astrometry, astrometry_error = build_astrometry_input(selected_gaia, row, zero_point_module=zero_point_module)
    if astrometry is None:
        extra_fields: dict[str, Any] = {}
        if astrometry_error == "parallax uncertainty too large":
            reason = astrometry_error
            quality = parallax_quality_payload(selected_gaia, row, zero_point_module=zero_point_module)
            if quality is not None:
                extra_fields["astrometry"] = quality
        elif astrometry_error.startswith("missing or invalid Gaia astrometry") or astrometry_error.startswith("missing or non-positive"):
            reason = "gaia astrometry not available"
            warnings.append({"type": "gaia_astrometry_invalid", "message": astrometry_error})
        else:
            reason = "zero point correction not available"
            warnings.append({"type": "zero_point_correction_failed", "message": astrometry_error})
        return _skip_record(
            reason,
            generated_at=generated_at,
            warnings=warnings,
            gaia_source_id=selected_gaia.canonical_value,
            extra_fields=extra_fields,
        )

    rv, rv_warnings = select_radial_velocity(record)
    warnings.extend(rv_warnings)
    fields, _cov, covariance_warnings = covariance_matrix(astrometry, rv)
    warnings.extend(covariance_warnings)

    try:
        posterior = (
            sample_provider(astrometry, rv, samples, seed)
            if sample_provider is not None
            else draw_mcmc_samples(astrometry, rv, samples=samples, seed=seed, prior_path=prior_path)
        )
        sample_lengths = {len(np.asarray(values)) for values in posterior.values()}
        if sample_lengths != {samples}:
            raise DynamicsError(f"posterior sample arrays must all have length {samples}; got {sorted(sample_lengths)}")
        kinematics = (
            kinematics_provider(astrometry, rv, posterior)
            if kinematics_provider is not None
            else calculate_kinematic_arrays(astrometry, rv, posterior)
        )
    except Exception as exc:
        warnings.append({"type": "dynamics_calculation_failed", "message": f"{type(exc).__name__}: {exc}"})
        return _skip_record("dynamics calculation failed", generated_at=generated_at, warnings=warnings, gaia_source_id=astrometry.gaia_source_id)

    if "radial_velocity" not in fields and not rv.lower_limit:
        warnings.append({"type": "radial_velocity_held_fixed", "message": "RV was held fixed because no usable uncertainty was available."})
    return build_computed_dynamics_record(
        generated_at=generated_at,
        astrometry=astrometry,
        rv=rv,
        posterior=posterior,
        kinematics=kinematics,
        warnings=warnings,
        sample_count=samples,
    )


def _object_paths(catalog_dir: Path, object_id: str = "") -> list[Path]:
    candidates_dir = catalog_dir / CANDIDATES_DIRNAME
    if object_id:
        return [candidates_dir / f"{object_id}.json"]
    return sorted(candidates_dir.glob("*.json")) if candidates_dir.exists() else []


def calculate_catalog_dynamics(
    catalog_dir: Path,
    *,
    object_id: str = "",
    clients: DynamicsClients | None = None,
    samples: int = DEFAULT_MCMC_SAMPLES,
    seed: int | None = None,
    write: bool = False,
    dry_run: bool = False,
    fail_on_network_error: bool = False,
    external_cache_mode: str = "required",
    zero_point_module: Any | None = None,
    sample_provider: SampleProvider | None = None,
    kinematics_provider: KinematicsProvider | None = None,
    generated_at: str | None = None,
    prior_path: Path = DEFAULT_PRIOR_PATH,
) -> dict[str, Any]:
    if external_cache_mode not in EXTERNAL_CACHE_MODES:
        raise ValueError(f"unknown external cache mode: {external_cache_mode}")
    paths = _object_paths(catalog_dir, object_id=object_id)
    generated_at = generated_at or now_timestamp()
    results: list[dict[str, Any]] = []
    written_paths: list[str] = []
    planned_write_paths: list[str] = []
    skipped_inputs: list[dict[str, str]] = []
    for path in paths:
        if not path.exists():
            skipped_inputs.append({"path": str(path), "error": "object JSON does not exist"})
            continue
        try:
            record = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            skipped_inputs.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        dynamics = compute_dynamics_for_object(
            record,
            clients=clients,
            samples=samples,
            seed=seed,
            generated_at=generated_at,
            zero_point_module=zero_point_module,
            sample_provider=sample_provider,
            kinematics_provider=kinematics_provider,
            fail_on_network_error=fail_on_network_error,
            external_cache_mode=external_cache_mode,
            prior_path=prior_path,
        )
        record["schema_version"] = OBJECT_SCHEMA_VERSION
        record["dynamics"] = dynamics
        item = {
            "object_id": str(record.get("object_id") or path.stem),
            "path": str(path),
            "status": dynamics.get("status"),
            "status_reason": dynamics.get("status_reason", ""),
            "graveyard": dynamics.get("graveyard", False),
            "lower_limit": dynamics.get("lower_limit", False),
        }
        results.append(item)
        if write and not dry_run:
            write_json(path, record)
            written_paths.append(str(path))
        else:
            planned_write_paths.append(str(path))

    status_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for item in results:
        status = str(item.get("status") or "missing")
        status_counts[status] = status_counts.get(status, 0) + 1
        reason = str(item.get("status_reason") or "")
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "generated_at": generated_at,
        "catalog_dir": str(catalog_dir),
        "object_id": object_id,
        "samples": samples,
        "write": write,
        "dry_run": dry_run,
        "external_cache_mode": external_cache_mode,
        "summary": {
            "processed_count": len(results),
            "computed_count": status_counts.get("computed", 0),
            "skipped_count": status_counts.get("skipped", 0),
            "graveyard_count": sum(1 for item in results if item.get("graveyard") is True),
            "lower_limit_count": sum(1 for item in results if item.get("lower_limit") is True),
            "status_counts": status_counts,
            "status_reason_counts": reason_counts,
            "skipped_input_count": len(skipped_inputs),
        },
        "objects": results,
        "skipped_inputs": skipped_inputs,
        "written_paths": written_paths,
        "planned_write_paths": planned_write_paths if dry_run or not write else [],
    }
