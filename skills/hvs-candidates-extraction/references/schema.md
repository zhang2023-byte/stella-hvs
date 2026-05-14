# `literature_hvs_candidates.json` Schema

Use `schema_version: "stella.literature_hvs_candidates.v2"`.

The file is paper-level: one JSON file describes all candidates that the paper
treats as possibly unbound from the Milky Way / Galactic potential. It is not an
object-level merged catalog.

## Top Level

```json
{
  "schema_version": "stella.literature_hvs_candidates.v2",
  "generated_at": "YYYY-MM-DDTHH:MM:SS",
  "paper": {
    "arxiv_id": "2402.10714",
    "bibcode": "2024A&A...681A..22M",
    "title": "",
    "month": "2024-02",
    "source_note_json": "notes/2024/2024-02/2024-02.json",
    "links": {"abs": "", "pdf": ""}
  },
  "inputs": {
    "paper_dir": "literature/2402.10714",
    "audit_path": "literature/2402.10714/audit.json",
    "catalog_review_path": "literature/2402.10714/catalog_review.json",
    "catalog_extraction_path": "literature/2402.10714/catalog_extraction.json",
    "ecsv_paths": ["literature/2402.10714/catalog_tables/table-1.ecsv"]
  },
  "extraction": {
    "status": "candidates_found",
    "extracted_at": "YYYY-MM-DDTHH:MM:SS",
    "extractor": "agent",
    "summary": ""
  },
  "method_chain": [],
  "candidates": [],
  "candidate_groups_considered": []
}
```

Allowed `extraction.status` values:

- `candidates_found`
- `no_candidates`
- `partial`
- `needs_review`
- `source_missing`

## Inclusion Boundary

Candidate inclusion is driven by paper text, not by tables alone. Include only
objects the paper itself treats as possibly unbound from the Milky Way /
Galactic potential, escaping the Galaxy, HVS candidates, or hyper-runaway
candidates with Galactic-unbound status.

Do not include ordinary runaways, cluster escapers, high-velocity halo stars,
objects listed only because they exceed a velocity cut, locally unbound
Galactic-center objects that the paper says remain Galaxy-bound, or objects the
paper concludes are bound to the Galaxy.

`candidate_assessment.source_refs` must contain paper text lines supporting the
Galactic-unbound candidate status. `catalog_review.json`, `catalog_extraction.json`,
and ECSV files are table maps and value sources only; they cannot justify
inclusion by themselves.

Allowed `candidate_assessment.candidate_status` values:

- `hvs_candidate`
- `unbound_candidate`
- `hyper_runaway_candidate`
- `escaping_galaxy_candidate`

## Candidate Origin

Every candidate has `candidate_origin`.

```json
{
  "origin_type": "introduced_by_this_paper",
  "paper_reassesses_unbound_status": true,
  "source_refs": []
}
```

Allowed `candidate_origin.origin_type` values:

- `introduced_by_this_paper`
- `cited_from_literature`

Use `introduced_by_this_paper` only when this paper first proposes the object as
a Galactic-unbound/HVS candidate. If a previous work already proposed that
status, use `cited_from_literature`, even when this paper reassesses the object.
Set `paper_reassesses_unbound_status` to `true` when the paper performs its own
unbound/orbit/velocity assessment.

For cited candidates, `candidate_origin.citation` is required:

```json
{
  "bibkey": "Erkal2019",
  "title": "",
  "year": "2019",
  "authors": ["Erkal, D."],
  "bibcode": "",
  "doi": "",
  "arxiv_id": "",
  "source_refs": []
}
```

`citation.source_refs` must include both the paper text cite line and the
matching `.bib` or `.bbl` bibliography entry when those source files are
available.

## Method Chain

Write method steps once at the paper level. Introduced candidates must refer to
at least one method step through `method_chain_refs`; cited candidates may leave
`method_chain_refs` empty when this paper only compiles them from prior work.

```json
{
  "id": "method-1",
  "step_type": "survey_input",
  "summary": "Gaia DR3 astrometry is used as the input catalog.",
  "inputs": ["Gaia DR3"],
  "outputs": ["candidate astrometry"],
  "source_refs": [
    {
      "kind": "text",
      "path": "literature/2402.10714/arxiv_source/main.tex",
      "start_line": 10,
      "end_line": 20,
      "context": "data source description"
    }
  ]
}
```

Suggested `step_type` values: `survey_input`, `sample_construction`,
`cross_match`, `quality_filter`, `distance_estimation`,
`velocity_calculation`, `galactic_potential`, `bound_probability`,
`candidate_ranking`, `follow_up`, `manual_validation`, `other`.

## Candidate Record

```json
{
  "candidate_id": "2402.10714:candidate-001",
  "identifiers": {
    "primary": "Gaia DR3 1180569514761870720",
    "paper_id": "No.01",
    "gaia_dr3_source_id": "1180569514761870720",
    "aliases": [
      {
        "value": "Gaia DR3 1180569514761870720",
        "source_refs": []
      }
    ]
  },
  "candidate_assessment": {
    "summary": "Why the paper treats this object as possibly unbound from the Galaxy.",
    "candidate_status": "unbound_candidate",
    "confidence": "high",
    "source_refs": []
  },
  "candidate_origin": {
    "origin_type": "introduced_by_this_paper",
    "paper_reassesses_unbound_status": true,
    "source_refs": []
  },
  "method_chain_refs": ["method-1", "method-2"],
  "core": {
    "observed_phase_space": {},
    "derived_kinematics": {},
    "probabilities": {}
  },
  "extra": []
}
```

## Core Fields

Use these names when available. Omit unavailable fields rather than inventing
values.

`core.observed_phase_space`:

- `ra`
- `dec`
- `distance`
- `parallax`
- `proper_motion_ra`
- `proper_motion_dec`
- `radial_velocity`

`core.derived_kinematics`:

- `galactocentric_x`
- `galactocentric_y`
- `galactocentric_z`
- `galactocentric_vx`
- `galactocentric_vy`
- `galactocentric_vz`
- `tangential_velocity`
- `galactocentric_tangential_velocity`
- `total_velocity`
- `galactic_rest_frame_velocity`
- `escape_velocity`
- `escape_velocity_ratio`

`core.probabilities`:

- `bound_probability`
- `unbound_probability`
- `classification_probability`

Each quantity record follows this shape:

```json
{
  "raw_value": "891 +/- 124",
  "value": "891",
  "error": "124",
  "lower_error": "",
  "upper_error": "",
  "unit": "km/s",
  "kind": "vtan",
  "description": "Heliocentric tangential velocity",
  "source_refs": []
}
```

`raw_value` preserves the source value exactly, after removing only ECSV quote
delimiters. `value`, `error`, `lower_error`, and `upper_error` are cleaned
machine-readable strings and must not contain LaTeX commands, braces, `$`, `_`,
`^`, `+/-`, or plus-minus symbols. Store numeric values as strings to preserve
source precision. Use `error` for symmetric errors and `lower_error` /
`upper_error` for asymmetric errors.

## Extra Fields

Use `extra[]` for useful non-core values such as photometry, stellar parameters,
object quality flags, neighbor checks, orbital traceback values, sample
membership labels, or paper-specific ranking metrics.

```json
{
  "name": "ruwe",
  "raw_value": "4.02",
  "value": "4.02",
  "unit": "",
  "kind": "Gaia DR3 quality",
  "description": "Renormalised unit weight error",
  "source_refs": []
}
```

Every `extra[]` item must have per-value provenance, just like core fields.

## Source References

ECSV cell reference:

```json
{
  "kind": "ecsv_cell",
  "path": "literature/2402.10714/catalog_tables/table-tab-72dr3.ecsv",
  "line": 69,
  "column": "col_019",
  "column_header": "vtan_g | [km/s]",
  "raw_value": "703"
}
```

For ECSV values, the quantity `raw_value`, the source reference `raw_value`, and
the parsed ECSV cell text must match exactly. Validation requires ECSV
references to use the machine column name (`col_001`, `col_002`, ...) and the
physical file line number. Use `nl -ba <file>` when checking line numbers
manually.

Paper text reference:

```json
{
  "kind": "text",
  "path": "literature/2402.10714/arxiv_source/hvsDR2DR3_arXiv.tex",
  "start_line": 2198,
  "end_line": 2206,
  "context": "candidate discussion"
}
```

Bibliography references use the same line-range shape and point to `.bib` or
`.bbl` files.

## Candidate Groups Considered

Use this list to document reviewed tables or object groups, especially in
`no_candidates` outputs.

```json
{
  "group_id": "table-1",
  "description": "Observation log table",
  "decision": "excluded",
  "reason": "Contains spectra exposure metadata, not Galactic-unbound HVS candidate objects.",
  "source_refs": []
}
```
