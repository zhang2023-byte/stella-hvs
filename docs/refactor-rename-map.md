# Refactor Rename Map (2026-06, pre-benchmark cleanup)

Permanent record of the technical-debt cleanup renames performed before the
benchmark freeze. Use this table when reading older commits, logs, or notes
that mention the previous names.

## Python packages (merged into a single `stella` package)

| Old | New |
|---|---|
| `src/high_velocity_lit/` | `src/stella/lit/` |
| `src/high_velocity_dyn/` | `src/stella/dyn/` |
| `src/stella_html/` | `src/stella/html/` |
| `src/stella_benchmark/` (empty placeholder) | `src/stella/benchmark/` |

Imports changed accordingly, e.g. `from high_velocity_lit.config import ...`
is now `from stella.lit.config import ...`. The package is installed editable
via `pyproject.toml` (`pip install -e .`); the previous per-file
`sys.path.insert` hacks in `scripts/` and `tests/` were removed.

## Scripts

| Old | New |
|---|---|
| `scripts/fetch_high_velocity_lit.py` | `scripts/fetch_literature.py` |
| `scripts/render_lit_notes.py` | `scripts/render_literature_notes.py` |
| `scripts/migrate_external_resource_source_refs.py` | deleted (dead, unreferenced duplicate of `scripts/cleanup_catalog_workflow_outputs.py`) |

## Skills

| Old | New |
|---|---|
| `skills/hvs_dynamics_calculate/` | `skills/hvs-dynamics-calculate/` (directory and SKILL.md `name:`; the workflow id `hvs_dynamics_calculate` is unchanged — workflow ids are snake_case by convention) |

## Other

| Old | New |
|---|---|
| `env.example` | `.env.example` |
| `workflows/stella_workflows.yaml` content | was JSON, converted to true YAML (same path, same data) |
| Dependency list in `environment.yml` | moved to `pyproject.toml`; `environment.yml` now installs `-e .` |

Data layout under `literature/`, `notes/`, and `catalog/` is intentionally
unchanged: existing `source_refs` in extracted JSON reference those paths.
