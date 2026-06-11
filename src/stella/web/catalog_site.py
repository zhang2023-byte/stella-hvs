"""Build HTML-facing view data for the object-level HVS catalog."""

from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path
from typing import Any


OBJECT_SCHEMA_VERSION = "stella.hvs_candidate_catalog.object.v0.1"
READABLE_OBJECT_SCHEMA_VERSIONS = {OBJECT_SCHEMA_VERSION}
INDEX_JSON_FILENAME = "03_hvs_candidates_index.json"
CANDIDATES_DIRNAME = "candidates"
LEGACY_INDEX_JSON_FILENAMES = ("hvs_candidates_index.json",)

OBSERVED_FIELDS = (
    "ra",
    "dec",
    "parallax",
    "proper_motion_ra",
    "proper_motion_dec",
    "radial_velocity",
    "distance",
)

DERIVED_FIELDS = ("total_velocity",)
PROBABILITY_FIELDS = ("unbound_probability",)

FIELD_LABELS = {
    "ra": "RA",
    "dec": "Dec",
    "parallax": "plx",
    "proper_motion_ra": "pmRA",
    "proper_motion_dec": "pmDec",
    "radial_velocity": "RV",
    "distance": "distance",
    "total_velocity": "total velocity",
    "unbound_probability": "P(unbound)",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _compact(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _first_item(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _ads_doc(payload: dict[str, Any]) -> dict[str, Any]:
    response = _as_mapping(payload.get("response"))
    docs = _as_list(response.get("docs"))
    if docs and isinstance(docs[0], dict):
        return docs[0]
    return payload


def _author_label(first_author: Any, authors: Any, year: Any) -> str:
    raw_author = _compact(first_author)
    author_list = [str(item) for item in _as_list(authors) if str(item).strip()]
    if not raw_author and author_list:
        raw_author = author_list[0]
    surname = raw_author.split(",", 1)[0].strip() or raw_author.strip()
    year_text = _compact(year)
    if not surname and not year_text:
        return ""
    if surname and year_text:
        suffix = " et al." if len(author_list) != 1 else ""
        return f"{surname}{suffix} {year_text}"
    return surname or year_text


def paper_metadata_for_arxiv(literature_dir: Path | None, arxiv_id: str) -> dict[str, Any]:
    """Read local ADS metadata for a paper without making network calls."""
    arxiv_id = _compact(arxiv_id)
    if not arxiv_id or literature_dir is None:
        return {}
    path = literature_dir.expanduser() / arxiv_id / "ads_metadata.json"
    if not path.exists():
        return {}
    try:
        doc = _ads_doc(read_json(path))
    except (OSError, json.JSONDecodeError):
        return {}
    authors = _as_list(doc.get("author"))
    first_author = _compact(doc.get("first_author") or (authors[0] if authors else ""))
    year = _compact(doc.get("year"))
    return {
        "arxiv_id": arxiv_id,
        "bibcode": _compact(doc.get("bibcode")),
        "title": _compact(_first_item(doc.get("title"))),
        "first_author": first_author,
        "author_count": len(authors),
        "year": year,
        "pubdate": _compact(doc.get("pubdate")),
        "citation_count": _number(doc.get("citation_count")),
        "reported_by": _author_label(first_author, authors, year),
    }


def collect_paper_metadata(records: list[dict[str, Any]], literature_dir: Path | None) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    if literature_dir is None:
        return metadata
    for record in records:
        for source in _as_list(record.get("sources")):
            paper = _as_mapping(_as_mapping(source).get("paper"))
            arxiv_id = _compact(paper.get("arxiv_id"))
            if arxiv_id and arxiv_id not in metadata:
                metadata[arxiv_id] = paper_metadata_for_arxiv(literature_dir, arxiv_id)
    return metadata


def fallback_reported_by(paper: dict[str, Any], metadata: dict[str, Any]) -> str:
    label = _compact(metadata.get("reported_by"))
    if label:
        return label
    year = _compact(metadata.get("year")) or _compact(paper.get("month"))[:4]
    arxiv_id = _compact(paper.get("arxiv_id"))
    return f"arXiv {arxiv_id} {year}".strip()


def quantity_text(quantity: Any) -> str:
    """Render a compact value string for index cells, with units kept in headers."""
    if not isinstance(quantity, dict):
        return ""
    value = str(quantity.get("value") or "").strip()
    if not value:
        return ""
    text = value
    error = str(quantity.get("error") or "").strip()
    lower = str(quantity.get("lower_error") or "").strip()
    upper = str(quantity.get("upper_error") or "").strip()
    if error:
        text = f"{text} ± {error}"
    elif lower or upper:
        lower_text = lower if lower.startswith(("-", "+")) else f"-{lower or '?'}"
        upper_text = upper if upper.startswith(("-", "+")) else f"+{upper or '?'}"
        text = f"{text} {lower_text} {upper_text}"
    return text


def interval_summary(value: Any) -> dict[str, Any]:
    """Return display and numeric fields for posterior interval payloads."""
    payload = _as_mapping(value)
    median = _number(payload.get("median"))
    p16 = _number(payload.get("p16"))
    p84 = _number(payload.get("p84"))
    if median is None:
        return {"text": "", "median": None, "p16": p16, "p84": p84}
    text = f"{median:.3g}"
    if p16 is not None and p84 is not None:
        text = f"{text} [{p16:.3g}, {p84:.3g}]"
    return {"text": text, "median": median, "p16": p16, "p84": p84}


def _unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _compact(value)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _best_source_quantity(record: dict[str, Any], group: str, field: str) -> dict[str, Any]:
    """Pick the first source-specific quantity for compact object-level display."""
    for candidate in _as_list(record.get("candidates")):
        candidate_map = _as_mapping(candidate)
        core = _as_mapping(candidate_map.get("core"))
        quantity = _as_mapping(_as_mapping(core.get(group)).get(field))
        if quantity:
            return quantity
    return {}


def candidate_for_source(record: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    for candidate in record.get("candidates") or []:
        if isinstance(candidate, dict) and candidate.get("source") == source_id:
            return candidate
    return None


def source_summary(
    record: dict[str, Any],
    source: dict[str, Any],
    paper_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract source-specific index quantities without merging across papers."""
    source_id = str(source.get("source") or "")
    candidate = candidate_for_source(record, source_id) or {}
    core = candidate.get("core") if isinstance(candidate.get("core"), dict) else {}
    observed = core.get("observed_phase_space") if isinstance(core.get("observed_phase_space"), dict) else {}
    derived = core.get("derived_kinematics") if isinstance(core.get("derived_kinematics"), dict) else {}
    bound_assessment = core.get("bound_assessment") if isinstance(core.get("bound_assessment"), dict) else {}
    paper = source.get("paper") if isinstance(source.get("paper"), dict) else {}
    arxiv_id = str(paper.get("arxiv_id") or "")
    metadata = (paper_metadata or {}).get(arxiv_id, {})
    candidate_context = candidate.get("candidate_context") if isinstance(candidate.get("candidate_context"), dict) else {}
    return {
        "source": source_id,
        "record_id": str(source.get("record_id") or ""),
        "paper_candidate_id": str(source.get("paper_candidate_id") or ""),
        "gaia_source_id": str(source.get("gaia_source_id") or ""),
        "arxiv_id": arxiv_id,
        "bibcode": str(paper.get("bibcode") or ""),
        "paper": {
            "arxiv_id": arxiv_id,
            "bibcode": str(paper.get("bibcode") or ""),
            "title": str(paper.get("title") or ""),
            "month": str(paper.get("month") or ""),
            "links": _as_mapping(paper.get("links")),
        },
        "paper_metadata": {
            **metadata,
            "reported_by": fallback_reported_by(paper, metadata),
        },
        "phase_space": {field: quantity_text(observed.get(field)) for field in OBSERVED_FIELDS},
        "total_velocity": quantity_text(derived.get("total_velocity")),
        "unbound_probability": quantity_text(bound_assessment.get("unbound_probability")),
        "bound_claim": str(candidate_context.get("galactic_bound_claim") or ""),
        "paper_labels": _unique(_as_list(candidate_context.get("paper_labels"))),
        "origin_type": str(candidate_context.get("origin_type") or ""),
        "extraction_confidence": str(candidate_context.get("extraction_confidence") or ""),
    }


def candidate_context_summary(record: dict[str, Any]) -> dict[str, Any]:
    contexts = [
        _as_mapping(_as_mapping(candidate).get("candidate_context"))
        for candidate in _as_list(record.get("candidates"))
        if isinstance(candidate, dict)
    ]
    labels = _unique([label for context in contexts for label in _as_list(context.get("paper_labels"))])
    bound_claims = _unique([context.get("galactic_bound_claim") for context in contexts])
    origin_types = _unique([context.get("origin_type") for context in contexts])
    confidence = _unique([context.get("extraction_confidence") for context in contexts])
    return {
        "paper_labels": labels,
        "bound_claims": bound_claims,
        "origin_types": origin_types,
        "extraction_confidence": confidence,
        "reassessed_source_count": sum(1 for context in contexts if context.get("paper_reassesses_unbound_status") is True),
    }


def dynamics_summary(record: dict[str, Any]) -> dict[str, Any]:
    dynamics = _as_mapping(record.get("dynamics"))
    astrometry = _as_mapping(dynamics.get("astrometry"))
    posterior = _as_mapping(dynamics.get("posterior"))
    rv_source = _as_mapping(dynamics.get("radial_velocity_source"))
    p_unbound = interval_summary(dynamics.get("p_unbound_beta"))
    p_bound = interval_summary(dynamics.get("p_bound_beta"))
    total_velocity = interval_summary(dynamics.get("total_velocity_grf_kms"))
    escape_velocity = interval_summary(dynamics.get("escape_velocity_kms"))
    velocity_margin = None
    if total_velocity["median"] is not None and escape_velocity["median"] is not None:
        velocity_margin = float(total_velocity["median"]) - float(escape_velocity["median"])
    return {
        "status": str(dynamics.get("status") or "not_computed"),
        "status_reason": str(dynamics.get("status_reason") or ""),
        "gaia_source_id": str(dynamics.get("gaia_source_id") or ""),
        "p_unbound": p_unbound,
        "p_bound": p_bound,
        "total_velocity_grf_kms": total_velocity,
        "escape_velocity_kms": escape_velocity,
        "heliocentric_distance_kpc": interval_summary(posterior.get("heliocentric_distance_kpc")),
        "velocity_margin_kms": velocity_margin,
        "lower_limit": bool(dynamics.get("lower_limit")),
        "graveyard": bool(dynamics.get("graveyard")),
        "radial_velocity_source": {
            "source": str(rv_source.get("source") or ""),
            "source_detail": str(rv_source.get("source_detail") or ""),
            "value": _number(rv_source.get("value")),
            "error": _number(rv_source.get("error")),
            "unit": str(rv_source.get("unit") or ""),
            "bibcode": str(rv_source.get("bibcode") or ""),
            "lower_limit": bool(rv_source.get("lower_limit")),
        },
        "corrected_parallax_mas": _number(astrometry.get("corrected_parallax_mas")),
        "parallax_error_mas": _number(astrometry.get("parallax_error_mas")),
        "corrected_parallax_over_error": _number(astrometry.get("corrected_parallax_over_error")),
        "warning_count": len(_as_list(dynamics.get("warnings"))),
        "sample_count": _number(_as_mapping(dynamics.get("sampling")).get("sample_count")),
    }


def external_summary(record: dict[str, Any]) -> dict[str, Any]:
    enrichment = _as_mapping(record.get("external_enrichment"))
    providers = _as_mapping(enrichment.get("providers"))
    simbad = _as_mapping(providers.get("simbad"))
    gaia = _as_mapping(providers.get("gaia_dr3"))
    verification = _as_mapping(enrichment.get("verification"))
    separations = _as_mapping(verification.get("coordinate_separations_arcsec"))
    return {
        "status": str(enrichment.get("status") or ""),
        "queried_at": str(enrichment.get("queried_at") or ""),
        "warning_count": len(_as_list(enrichment.get("warnings"))),
        "value_comparison_count": len(_as_list(verification.get("value_comparisons"))),
        "simbad": {
            "status": str(simbad.get("status") or ""),
            "matched_by": str(simbad.get("matched_by") or ""),
            "main_id": str(simbad.get("main_id") or ""),
            "object_type": str(simbad.get("object_type") or ""),
            "separation_arcsec": _number(separations.get("simbad")),
        },
        "gaia_dr3": {
            "status": str(gaia.get("status") or ""),
            "matched_by": str(gaia.get("matched_by") or ""),
            "source_id": str(gaia.get("source_id") or ""),
            "designation": str(gaia.get("designation") or ""),
            "separation_arcsec": _number(separations.get("gaia_dr3")),
        },
    }


def quantity_coverage_summary(record: dict[str, Any]) -> dict[str, int]:
    coverage = {
        "photometry": 0,
        "spectroscopy": 0,
        "stellar_parameters": 0,
        "abundances": 0,
        "quality_flags": 0,
        "orbit": 0,
        "astrophysical_origin": 0,
        "extra": 0,
    }
    for candidate in _as_list(record.get("candidates")):
        candidate_map = _as_mapping(candidate)
        for key in ("photometry", "spectroscopy", "abundances", "quality_flags", "extra"):
            coverage[key] += len(_as_list(candidate_map.get(key)))
        for key in ("stellar_parameters", "orbit", "astrophysical_origin"):
            group = _as_mapping(candidate_map.get(key))
            coverage[key] += sum(1 for value in group.values() if value not in (None, "", [], {}))
    return coverage


def build_index_row(record: dict[str, Any], paper_metadata: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    canonical = record.get("canonical_identifier") if isinstance(record.get("canonical_identifier"), dict) else {}
    sources = [source for source in record.get("sources") or [] if isinstance(source, dict)]
    source_rows = [source_summary(record, source, paper_metadata=paper_metadata) for source in sources]
    bibcodes = []
    for source in source_rows:
        bibcode = source.get("bibcode") or ""
        if bibcode and bibcode not in bibcodes:
            bibcodes.append(bibcode)
    gaia_ids = []
    paper_ids = []
    for source in source_rows:
        gaia_id = source.get("gaia_source_id") or ""
        paper_id = source.get("paper_candidate_id") or ""
        if gaia_id and gaia_id not in gaia_ids:
            gaia_ids.append(gaia_id)
        if paper_id and paper_id not in paper_ids:
            paper_ids.append(paper_id)
    enrichment = record.get("external_enrichment") if isinstance(record.get("external_enrichment"), dict) else {}
    external = external_summary(record)
    dynamics = dynamics_summary(record)
    candidate_context = candidate_context_summary(record)
    merge = record.get("merge") if isinstance(record.get("merge"), dict) else {}
    best_observed = {
        field: quantity_text(_best_source_quantity(record, "observed_phase_space", field))
        for field in OBSERVED_FIELDS
    }
    best_derived = {
        "total_velocity": quantity_text(_best_source_quantity(record, "derived_kinematics", "total_velocity")),
        "unbound_probability": quantity_text(_best_source_quantity(record, "bound_assessment", "unbound_probability")),
    }
    months = _unique([_as_mapping(source.get("paper")).get("month") for source in sources])
    return {
        "object_id": str(record.get("object_id") or ""),
        "identifier": str(canonical.get("value") or record.get("object_id") or ""),
        "identifier_kind": str(canonical.get("kind") or ""),
        "gaia_source_ids": gaia_ids,
        "paper_candidate_ids": paper_ids,
        "bibcodes": bibcodes,
        "sources": source_rows,
        "source_count": len(source_rows),
        "discovery_month": min(months) if months else "",
        "enrichment_status": str(enrichment.get("status") or ""),
        "enrichment_warning_count": len(enrichment.get("warnings") or []) if isinstance(enrichment, dict) else 0,
        "warning_count": len(merge.get("warnings") or []),
        "evidence_count": len(merge.get("evidence") or []),
        "best_source_values": {**best_observed, **best_derived},
        "candidate_context": candidate_context,
        "dynamics": dynamics,
        "external": external,
        "merge": {
            "match_strategy": str(merge.get("match_strategy") or ""),
            "warning_count": len(merge.get("warnings") or []),
            "evidence_count": len(merge.get("evidence") or []),
        },
        "quantity_coverage": quantity_coverage_summary(record),
    }


def method_lineage(steps: list[dict[str, Any]], method_refs: list[str]) -> dict[str, list[str]]:
    """Return direct method refs, recursive ancestors, and highlighted edges."""
    by_id = {str(step.get("id") or ""): step for step in steps if isinstance(step, dict)}
    direct = [step_id for step_id in method_refs if step_id in by_id]
    ancestors: set[str] = set()
    edges: set[tuple[str, str]] = set()

    def visit(step_id: str) -> None:
        step = by_id.get(step_id)
        if not step:
            return
        for dep in step.get("depends_on") or []:
            dep_id = str(dep)
            if dep_id not in by_id:
                continue
            edges.add((dep_id, step_id))
            if dep_id not in ancestors and dep_id not in direct:
                ancestors.add(dep_id)
            visit(dep_id)

    for step_id in direct:
        visit(step_id)
    return {
        "direct": direct,
        "ancestors": sorted(ancestors),
        "edges": [f"{left}->{right}" for left, right in sorted(edges)],
    }


def load_catalog_snapshot(catalog_dir: Path, *, literature_dir: Path | None = None) -> dict[str, Any]:
    """Load index and object JSON files into a static-site snapshot."""
    catalog_dir = catalog_dir.expanduser()
    index_path = catalog_dir / INDEX_JSON_FILENAME
    if not index_path.exists():
        for filename in LEGACY_INDEX_JSON_FILENAMES:
            legacy_path = catalog_dir / filename
            if legacy_path.exists():
                index_path = legacy_path
                break
    index_record: dict[str, Any] = {}
    if index_path.exists():
        try:
            index_record = read_json(index_path)
        except (OSError, json.JSONDecodeError):
            index_record = {}

    records: list[dict[str, Any]] = []
    candidate_paths = list((catalog_dir / CANDIDATES_DIRNAME).glob("*.json"))
    legacy_paths = list(catalog_dir.glob("*.json"))
    for path in sorted([*candidate_paths, *legacy_paths]):
        if path.name == INDEX_JSON_FILENAME or path.name in LEGACY_INDEX_JSON_FILENAMES:
            continue
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("schema_version") in READABLE_OBJECT_SCHEMA_VERSIONS:
            records.append(payload)

    order = [
        str(item.get("object_id") or "")
        for item in index_record.get("objects") or []
        if isinstance(item, dict) and item.get("object_id")
    ]
    order_index = {object_id: index for index, object_id in enumerate(order)}
    records.sort(key=lambda record: (order_index.get(str(record.get("object_id") or ""), len(order_index)), str(record.get("object_id") or "")))

    paper_metadata = collect_paper_metadata(records, literature_dir)
    rows = [build_index_row(record, paper_metadata=paper_metadata) for record in records]
    summary = index_record.get("summary") if isinstance(index_record.get("summary"), dict) else {}
    if not summary:
        summary = {
            "object_count": len(records),
            "source_count": sum(len(record.get("sources") or []) for record in records),
            "candidate_count": sum(len(record.get("candidates") or []) for record in records),
            "objects_with_gaia_count": sum(1 for row in rows if row.get("gaia_source_ids")),
            "warning_count": sum(int(row.get("warning_count") or 0) for row in rows),
            "skipped_count": 0,
        }

    return {
        "schema_version": "stella.hvs_catalog_site.snapshot.v0.1",
        "summary": summary,
        "index": index_record,
        "rows": rows,
        "objects": records,
        "paper_metadata": paper_metadata,
        "field_labels": FIELD_LABELS,
    }


def json_script_payload(payload: dict[str, Any]) -> str:
    """Serialize JSON for direct inclusion in a script tag."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _asset_data_uri(path: Path, mime_type: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def inline_css(css_path: Path, *, hero_path: Path | None = None) -> str:
    css = css_path.read_text(encoding="utf-8")
    if hero_path is not None and hero_path.exists():
        css = css.replace("url(\"stella-hero.svg\")", f"url(\"{_asset_data_uri(hero_path, 'image/svg+xml')}\")")
        mime_type = "image/png" if hero_path.suffix.lower() == ".png" else "image/svg+xml"
        css = css.replace("url(\"stella-hvs-hero.png\")", f"url(\"{_asset_data_uri(hero_path, mime_type)}\")")
    return css


def render_live_index_html(*, catalog_root: str = "../..", paper_metadata_path: str = "assets/paper-metadata.json") -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stella HVS Catalog</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="assets/stella.css">
</head>
<body data-catalog-root="{catalog_root}" data-paper-metadata="{paper_metadata_path}">
  <div id="app" class="app-shell" aria-live="polite"></div>
  <script src="assets/catalog-viewer.js"></script>
</body>
</html>
""".format(catalog_root=catalog_root, paper_metadata_path=paper_metadata_path)


def render_static_index_html(snapshot: dict[str, Any], *, css: str, js: str) -> str:
    payload = json_script_payload(snapshot)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stella HVS Catalog Snapshot</title>
  <link rel="icon" href="data:,">
  <style>
{css}
  </style>
</head>
<body>
  <div id="app" class="app-shell" aria-live="polite"></div>
  <script>
window.STELLA_CATALOG_SNAPSHOT = {payload};
  </script>
  <script>
{js}
  </script>
</body>
</html>
"""


def has_external_html_dependencies(html: str) -> bool:
    """Return True if static HTML uses external scripts, stylesheets, or remote image URLs."""
    patterns = [
        r"<script\b[^>]*\bsrc\s*=",
        r"<link\b[^>]*\brel\s*=\s*[\"']?stylesheet[^>]*\bhref\s*=",
        r"<link\b[^>]*\bhref\s*=\s*[\"']?https?://",
        r"<img\b[^>]*\bsrc\s*=\s*[\"']https?://",
        r"url\(\s*[\"']?https?://",
    ]
    return any(re.search(pattern, html, flags=re.IGNORECASE) for pattern in patterns)


def build_static_html(
    catalog_dir: Path,
    css_path: Path,
    js_path: Path,
    hero_path: Path | None = None,
    *,
    literature_dir: Path | None = None,
) -> str:
    snapshot = load_catalog_snapshot(catalog_dir, literature_dir=literature_dir)
    css = inline_css(css_path, hero_path=hero_path)
    js = js_path.read_text(encoding="utf-8")
    return render_static_index_html(snapshot, css=css, js=js)


def render_static_index_html_v2() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stella HVS Catalog Snapshot</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="stella.css">
</head>
<body>
  <div id="app" class="app-shell" aria-live="polite"></div>
  <script src="catalog-data.js"></script>
  <script src="catalog-viewer.js"></script>
</body>
</html>
"""


def build_static_site(
    output_dir: Path,
    catalog_dir: Path,
    css_path: Path,
    js_path: Path,
    hero_path: Path | None = None,
    *,
    literature_dir: Path | None = None,
) -> Path:
    """Build a multi-file static site into *output_dir*.

    Produces:
      - index.html        (small shell referencing sibling assets)
      - stella.css        (copied from *css_path*)
      - catalog-viewer.js (copied from *js_path*)
      - catalog-data.js   (snapshot serialized as window.STELLA_CATALOG_SNAPSHOT)
      - <hero-image>      (copied from *hero_path*, if provided)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = load_catalog_snapshot(catalog_dir, literature_dir=literature_dir)

    # 1. Catalog data as a JS file that sets the global snapshot variable
    payload = json_script_payload(snapshot)
    (output_dir / "catalog-data.js").write_text(
        f"window.STELLA_CATALOG_SNAPSHOT = {payload};", encoding="utf-8"
    )

    # 2. CSS (keep external image references intact)
    shutil.copy2(css_path, output_dir / "stella.css")

    # 3. Hero image (CSS references it by filename)
    if hero_path is not None and hero_path.exists():
        shutil.copy2(hero_path, output_dir / hero_path.name)

    # 4. JS viewer
    shutil.copy2(js_path, output_dir / "catalog-viewer.js")

    # 5. HTML shell
    (output_dir / "index.html").write_text(render_static_index_html_v2(), encoding="utf-8")

    return output_dir / "index.html"
