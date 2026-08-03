"""prepare_paper_context stage orchestration.

Builds the complete model-visible paper context for one paper before any
model call: the resolved and minimally cleaned TeX manuscript view, the
optional ECSV selection with its minimal mapping, bibliography discovery, and
the paper-level context-mode preflight. All failures are fail-closed
structured artifacts; this stage never writes into formal campaign paths.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.benchmark.context_pack import numbered_lines
from stella.hvs_extraction.bibliography import discover_bibliography
from stella.hvs_extraction.cleaning import (
    render_manuscript_view,
    strip_tex_comments,
)
from stella.hvs_extraction.ecsv import SelectedEcsv, select_ecsv_tables
from stella.hvs_extraction.method_config import HvsContextBudget
from stella.hvs_extraction.tex_graph import TexGraphError, resolve_tex_graph
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, schema_ref

# Conservative preflight estimate (delegated engineering default; the final
# per-request size check stays exact). Overestimating tokens is safe.
ESTIMATE_CHARS_PER_TOKEN = 3.0

STATUS_PREPARED = "prepared"
STATUS_INPUT_PREPARATION_FAILURE = "input_preparation_failure"
STATUS_INPUT_TOO_LARGE = "input_too_large"

MODE_FULL = "full"
MODE_TEX_ONLY = "tex_only_due_to_context_budget"
MODE_FIELD_TOO_LARGE = "field_input_too_large"

RUNS_RELATIVE_DIR = Path(
    f"benchmark/campaigns/{ACTIVE_BENCHMARK_CAMPAIGN}/runs"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / ESTIMATE_CHARS_PER_TOKEN)


def render_ecsv_block(selected: SelectedEcsv, content: str) -> str:
    """Render one ECSV block: minimal mapping, then line-numbered content."""

    mapping = [
        "----- ECSV SOURCE MAPPING -----",
        f"ecsv_path: {selected.ecsv_path}",
        f"source_tex_path: {selected.source_tex_path}",
        f"source_tex_start_line: {selected.source_tex_start_line}",
        f"source_tex_end_line: {selected.source_tex_end_line}",
    ]
    if selected.label:
        mapping.append(f"source_table_label: {selected.label}")
    return "\n".join(mapping) + "\n----- ECSV CONTENT -----\n" + numbered_lines(content)


def build_prepared_input(
    workspace: Path,
    arxiv_id: str,
    *,
    roster_budget: HvsContextBudget,
    field_budget: HvsContextBudget,
    literature_dir: Path | None = None,
) -> dict[str, Any]:
    """Build the prepared_input artifact for one paper (no model calls)."""

    arxiv_id = validate_unversioned_arxiv_id(arxiv_id)
    literature_dir = literature_dir or workspace / "literature"
    paper_dir = literature_dir / arxiv_id
    base: dict[str, Any] = {
        "schema": schema_ref("hvs_extraction.prepared_input"),
        "generated_at": _utc_now(),
        "paper": {"arxiv_id": arxiv_id},
    }

    source_dir = paper_dir / "arxiv_source"
    try:
        graph = resolve_tex_graph(source_dir)
    except TexGraphError as exc:
        return base | {
            "status": STATUS_INPUT_PREPARATION_FAILURE,
            "failure": {"code": exc.code, "detail": exc.detail},
        }

    cleaned_blocks = [
        (name, strip_tex_comments(graph.texts[name])) for name in graph.included
    ]
    manuscript_view = render_manuscript_view(cleaned_blocks)

    selection = select_ecsv_tables(workspace, paper_dir, graph)
    ecsv_blocks: list[str] = []
    selected_records: list[dict[str, Any]] = []
    for selected in selection.selected:
        content = (paper_dir / selected.ecsv_path).read_text(encoding="utf-8")
        ecsv_blocks.append(render_ecsv_block(selected, content))
        selected_records.append(
            {
                "ecsv_path": selected.ecsv_path,
                "source_tex_path": selected.source_tex_path,
                "source_tex_start_line": selected.source_tex_start_line,
                "source_tex_end_line": selected.source_tex_end_line,
                "label": selected.label,
                "sha256": selected.structure.sha256,
                "columns": list(selected.structure.columns),
                "column_row_line": selected.structure.column_row_line,
                "data_row_count": len(selected.structure.data_row_lines),
                "line_count": selected.structure.line_count,
            }
        )

    bibliography = [
        {"kind": item.kind, "path": item.path, "start_line": item.start_line, "end_line": item.end_line}
        for item in discover_bibliography(graph, source_dir)
    ]

    full_surface = manuscript_view + ("\n" + "\n\n".join(ecsv_blocks) + "\n" if ecsv_blocks else "")
    roster_fit = estimate_tokens(manuscript_view) <= roster_budget.input_budget()
    if not roster_fit:
        field_mode = MODE_FIELD_TOO_LARGE
    elif estimate_tokens(full_surface) <= field_budget.input_budget():
        field_mode = MODE_FULL
    elif estimate_tokens(manuscript_view) <= field_budget.input_budget():
        field_mode = MODE_TEX_ONLY
    else:
        field_mode = MODE_FIELD_TOO_LARGE

    effective_surface = full_surface if field_mode == MODE_FULL else manuscript_view
    status = STATUS_PREPARED if roster_fit else STATUS_INPUT_TOO_LARGE
    return base | {
        "status": status,
        "failure": None
        if roster_fit
        else {
            "code": STATUS_INPUT_TOO_LARGE,
            "detail": (
                f"manuscript view is {estimate_tokens(manuscript_view)} estimated "
                f"tokens, over the roster input budget {roster_budget.input_budget()}"
            ),
        },
        "manuscript": {
            "root": graph.root,
            "included": graph.included,
            "excluded": graph.excluded,
            "edges": graph.edges,
            "files": {
                name: {
                    "sha256": item.sha256,
                    "line_count": item.line_count,
                    "encoding": item.encoding,
                }
                for name, item in graph.files.items()
            },
            "non_tex_includes": [list(pair) for pair in graph.non_tex_includes],
            "diagnostics": graph.diagnostics,
            "view_sha256": hashlib.sha256(manuscript_view.encode("utf-8")).hexdigest(),
            "view_chars": len(manuscript_view),
            "view": manuscript_view,
        },
        "ecsv": {
            "status": selection.status,
            "selected": selected_records,
            "excluded": selection.excluded,
            "diagnostics": selection.diagnostics,
        },
        "bibliography": bibliography,
        "context": {
            "roster_fit": roster_fit,
            "field_context_mode": field_mode,
            "field_ecsv_context_status": selection.status
            if field_mode == MODE_FULL
            else "unavailable",
            "field_ecsv_exclusion_reason": None
            if field_mode == MODE_FULL
            else "context_budget_exceeded",
            "estimate_chars_per_token": ESTIMATE_CHARS_PER_TOKEN,
            "budget_inputs": {
                "roster_input_budget": roster_budget.input_budget(),
                "field_input_budget": field_budget.input_budget(),
                "manuscript_view_estimate_tokens": estimate_tokens(manuscript_view),
                "full_surface_estimate_tokens": estimate_tokens(full_surface),
            },
            "field_shared_prefix_sha256": hashlib.sha256(
                effective_surface.encode("utf-8")
            ).hexdigest(),
            "field_source_surface_chars": len(effective_surface),
        },
    }


def prepared_input_path(workspace: Path, run_id: str, arxiv_id: str) -> Path:
    return (
        workspace
        / RUNS_RELATIVE_DIR
        / run_id
        / "prepared_inputs"
        / f"{arxiv_id}.json"
    )


def write_prepared_input(workspace: Path, run_id: str, artifact: dict[str, Any]) -> Path:
    """Atomically persist one prepared_input artifact under the extraction tree."""

    arxiv_id = artifact["paper"]["arxiv_id"]
    path = prepared_input_path(workspace, run_id, arxiv_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path
