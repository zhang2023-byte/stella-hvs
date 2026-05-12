# `literature_hvs_candidates.json` Schema

Use `schema_version: "stella.literature_hvs_candidates.v1"`.

The file is paper-level: one JSON file describes all HVS/unbound candidates
extracted from one literature source. It is not an object-level merged catalog.

## Top Level

```json
{
  "schema_version": "stella.literature_hvs_candidates.v1",
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

## Method Chain

Write method steps once at the paper level. Candidate records refer to these
steps through `method_chain_refs`.

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
    "summary": "Why the paper treats this object as an HVS/unbound candidate.",
    "candidate_status": "hvs_candidate",
    "confidence": "high",
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

Suggested `candidate_status` values: `hvs_candidate`, `unbound_candidate`,
`hyper_runaway_candidate`, `escaping_candidate`, `rejected_by_paper`,
`ambiguous`. Use `rejected_by_paper` only inside
`candidate_groups_considered[]` unless the user asks for rejected objects.

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
  "value": "703",
  "error": "",
  "lower_error": "",
  "upper_error": "",
  "unit": "km/s",
  "kind": "vtan_g",
  "description": "Galactocentric tangential velocity",
  "source_refs": []
}
```

Store numeric values as strings to preserve the source precision. Use `error`
for symmetric errors and `lower_error` / `upper_error` for asymmetric errors.

## Extra Fields

Use `extra[]` for useful non-core values such as photometry, stellar
parameters, object quality flags, neighbor checks, orbital traceback values,
sample membership labels, or paper-specific ranking metrics.

```json
{
  "name": "ruwe",
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

Validation requires ECSV references to use the machine column name (`col_001`,
`col_002`, ...) and the physical file line number. Use the parsed cell content
as `raw_value`, without ECSV quote delimiters, so a file cell like
`"891 +/- 124"` is recorded as `891 +/- 124`. Use `nl -ba <file>` when checking
line numbers manually.

## Candidate Groups Considered

Use this list to document reviewed tables or object groups, especially in
`no_candidates` outputs.

```json
{
  "group_id": "table-1",
  "description": "Observation log table",
  "decision": "excluded",
  "reason": "Contains spectra exposure metadata, not HVS candidate objects.",
  "source_refs": []
}
```
