---
name: hvs-candidates-extraction
description: Extract paper-level high-velocity-star and unbound-star candidates for Stella after catalog_review.json and catalog_extraction.json exist. Use when an agent needs to read archived paper sources, reviewed table inventories, and ECSV table extractions to write literature/{arxiv_id}/literature_hvs_candidates.json with per-value provenance and the paper's method chain.
---

# HVS Candidate Extraction

Use this skill after one archived paper has both:

```text
literature/<arxiv_id>/catalog_review.json
literature/<arxiv_id>/catalog_extraction.json
```

The output is:

```text
literature/<arxiv_id>/literature_hvs_candidates.json
```

This stage identifies and normalizes HVS/unbound candidates from one paper. It
does not merge objects across papers and does not download or parse new external
resources.

## Reference

Read `references/schema.md` before writing the JSON. It defines the required
`stella.literature_hvs_candidates.v1` shape, provenance rules, and examples.

## Workflow

1. Inspect inputs:
   - `literature/<arxiv_id>/audit.json`
   - `catalog_review.json`
   - `catalog_extraction.json`
   - relevant `catalog_tables/*.ecsv`
   - relevant `catalog_sources/*/excerpt.tex`
   - paper source under `arxiv_source/`
   - the monthly JSON referenced by `audit.source_note_json`, if present
2. Use `catalog_review.json` and `catalog_extraction.json` as a reading map.
   They show which tables exist, how the paper describes them, and which ECSV
   files preserve the table rows.
3. Decide candidate inclusion by paper evidence, not by a standalone threshold.
   Include only objects that the paper explicitly presents as HVS, unbound,
   escaping, hyper-runaway, or equivalent candidates, or objects whose unbound
   status is directly assessed by the paper.
4. Prefer ECSV cells for numerical values. Use paper text and LaTeX source for
   candidate rationale, method steps, field definitions, and values missing from
   ECSV.
5. Merge rows for the same candidate inside the paper. Prefer stable identifiers
   in this order: Gaia source ID, explicit object name, paper candidate number,
   and only then a table-row relation documented by the paper.
6. Extract a paper-level `method_chain[]`:
   - input surveys or catalogs
   - cross-matching or sample construction
   - quality cuts and flags
   - distance and velocity calculations
   - Galactic potential or escape-speed assumptions
   - bound/unbound probability or candidate ranking
   - follow-up or manual validation
7. For every candidate, fill standard `core` fields where the paper provides
   them, put other useful values in `extra[]`, and reference relevant method
   steps with `method_chain_refs`.
8. Validate:

   ```bash
   conda run -n stella-env python scripts/validate_hvs_candidates.py --arxiv-id <arxiv_id>
   ```

## Boundaries

- Do not infer a candidate only because one velocity exceeds a generic cutoff.
- Do not make a bound/unbound decision that the paper does not make.
- Do not normalize units by recomputing values unless the paper explicitly gives
  the converted value. Preserve the paper value and unit text.
- Do not silently drop missing 6D components; leave the field absent and mention
  the gap in `candidate_assessment` or `extraction.summary`.
- Do not hand-edit ECSV or catalog extraction artifacts to make validation pass.
- Do not force-add generated `literature/` files to Git unless the user asks.

## Provenance Rules

Every value in `core` and `extra[]` must include `source_refs`.

For ECSV values, cite the exact cell:

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

Use the ECSV cell content as `raw_value` after removing ECSV quote delimiters;
for example `"891 +/- 124"` in the file becomes `891 +/- 124`.

For paper text, cite the exact source lines:

```json
{
  "kind": "text",
  "path": "literature/2402.10714/arxiv_source/hvsDR2DR3_arXiv.tex",
  "start_line": 2198,
  "end_line": 2206,
  "context": "paper discussion of candidate status"
}
```

If one ECSV cell contains `value +/- error`, split it into `value` and `error`
fields only when the split is mechanical; both fields keep the same cell
provenance and the original cell text stays in `raw_value`.

## Empty Results

If the paper has no included candidates, still write
`literature_hvs_candidates.json` with:

```json
{
  "extraction": {"status": "no_candidates"},
  "candidates": [],
  "candidate_groups_considered": [
    {
      "group_id": "table-1",
      "description": "Reviewed object table or candidate-like group.",
      "decision": "excluded",
      "reason": "The paper does not present these objects as HVS/unbound candidates.",
      "source_refs": [
        {
          "kind": "text",
          "path": "literature/<arxiv_id>/arxiv_source/main.tex",
          "start_line": 10,
          "end_line": 20,
          "context": "table caption or surrounding text"
        }
      ]
    }
  ]
}
```

Use `candidate_groups_considered[]` to record the tables or object groups that
were reviewed and why they were excluded.
