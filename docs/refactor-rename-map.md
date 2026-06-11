# Refactor Rename Map (2026-06, pre-benchmark cleanup)

Permanent record of the technical-debt cleanup renames performed before the
benchmark freeze. Use this table when reading older commits, logs, or notes
that mention the previous names.

## Python packages (merged into a single `stella` package)

| Old | New |
|---|---|
| `src/high_velocity_lit/` | `src/stella/lit/` |
| `src/high_velocity_dyn/` | `src/stella/dyn/` |
| `src/stella_html/` | `src/stella/web/` |
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

## Web layer (2026-06, post-freeze; display/deploy layer is outside the frozen surface)

Three roles, three names: `stella.web` (rendering code) generates
`catalog/web/` (regenerable web view), which is snapshotted into `pages/`
(committed GitHub Pages publish directory).

| Old | New |
|---|---|
| `src/stella/html/` (earlier `src/stella_html/`) | `src/stella/web/` |
| `catalog/html/` (generated, git-ignored) | `catalog/web/` |
| `site/` (committed Pages snapshot) | `pages/` |
| `scripts/build_hvs_catalog_html.py` (`--html-dir`) | `scripts/build_hvs_catalog_web.py` (`--web-dir`) |
| `scripts/serve_catalog_site.py` | `scripts/serve_catalog_web.py` |
| workflow id `hvs_catalog_html_build` | `hvs_catalog_web_build` |
| `prepare_pages_site.py --site-dir` | `--pages-dir` (script name unchanged) |
| bare `html/` entry in `.gitignore` | removed (`catalog/` already covers `catalog/web`; a bare `web/` entry would wrongly ignore `src/stella/web`) |

The site snapshot schema version string `stella.hvs_catalog_site.snapshot.v0.1`
is an internal identifier and intentionally unchanged (see schema-v0.2-notes).

## Other

| Old | New |
|---|---|
| `env.example` | `.env.example` |
| `workflows/stella_workflows.yaml` content | was JSON, converted to true YAML (same path, same data) |
| Dependency list in `environment.yml` | moved to `pyproject.toml`; `environment.yml` now installs `-e .` |

Data layout under `literature/`, `notes/`, and `catalog/` is intentionally
unchanged: existing `source_refs` in extracted JSON reference those paths.
