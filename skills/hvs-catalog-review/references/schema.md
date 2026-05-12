# `catalog_review.json` Schema

Use `schema_version: "stella.article_data_assets.review.v1"`.

`catalog_review.json` is a data-asset inventory for one archived paper. It does
not decide whether an asset is an HVS catalog and does not represent extracted
ECSV tables.

## Top Level

```json
{
  "schema_version": "stella.article_data_assets.review.v1",
  "paper": {
    "arxiv_id": "2402.10714",
    "title": "",
    "month": "2024-02",
    "source_note_json": "notes/2024/2024-02/2024-02.json",
    "links": {"abs": "", "pdf": ""}
  },
  "source": {
    "paper_dir": "literature/2402.10714",
    "audit_path": "literature/2402.10714/audit.json",
    "source_dir": "literature/2402.10714/arxiv_source",
    "tex_root": "literature/2402.10714/arxiv_source/main.tex",
    "source_available": true
  },
  "review": {
    "status": "reviewed",
    "reviewed_at": "YYYY-MM-DDTHH:MM:SS",
    "reviewer": "agent",
    "summary": ""
  },
  "internal_tables": [],
  "external_resources": []
}
```

Allowed `review.status` values:

- `reviewed`
- `partial`
- `needs_review`
- `source_missing`

## Internal Tables

Use `internal_tables[]` for structured tables visible in the paper source,
including object/candidate tables, observation logs, sample summaries,
model-parameter tables, fit-result tables, and other structured data.

```json
{
  "id": "table-1",
  "kind": "latex_table",
  "asset_type": "object_measurement_table",
  "role_in_paper": "",
  "source_refs": [
    {
      "path": "literature/2402.10714/arxiv_source/main.tex",
      "start_line": 10,
      "end_line": 40,
      "caption": "",
      "label": ""
    }
  ],
  "columns": [
    {
      "name": "",
      "meaning": "",
      "unit_text": "",
      "source_of_definition": "",
      "confidence": 0.0
    }
  ],
  "evidence": "",
  "comments": ""
}
```

Suggested `asset_type` values:

- `object_measurement_table`
- `observation_log`
- `sample_summary`
- `model_parameter_table`
- `fit_result_table`
- `external_machine_readable_table`
- `readme_or_metadata`
- `data_availability_resource`
- `other_structured_data`

For every internal table, record its full-paper role and visible column
meanings. Do not add later HVS semantics or normalized object schema in this
stage.

## External Resources

Use `external_resources[]` for external or local resources mentioned by the
paper. Record only the paper-grounded resource description.

```json
{
  "id": "resource-1",
  "kind": "external_url",
  "url": "",
  "local_path": "",
  "description": "",
  "source_refs": [
    {
      "path": "",
      "start_line": 0,
      "end_line": 0,
      "context": ""
    }
  ],
  "evidence": "",
  "comments": ""
}
```

Rules:

- Copy `url` verbatim from the paper source. Leave it empty if the paper does
  not give a concrete URL.
- Use `local_path` only when it points to an already archived local resource.
- Do not download, resolve, parse, or infer remote resource structure.
- Do not record generic database acknowledgements as external resources.
