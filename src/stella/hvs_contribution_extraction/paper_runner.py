"""One paper's full contribution extraction chain.

prepare -> contribution roster -> per-object measurement extraction ->
finalize -> canonical ``literature_hvs_contributions`` document. The
preparation reuses the neutral TeX/ECSV machinery; the artifact is stamped
with the contribution pipeline's own transient schema and written only into
the caller's non-formal run directory.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from stella.hvs_extraction.prepare import (
    build_prepared_input,
    write_prepared_input,
)
from stella.hvs_contribution_extraction.core_document import (
    write_contribution_document,
)
from stella.hvs_contribution_extraction.finalize import (
    PAPER_FAILED,
    assemble_contribution_paper_result,
)
from stella.hvs_contribution_extraction.measurement_stage import (
    run_measurement_stage,
)
from stella.hvs_contribution_extraction.method_config import (
    HvsContributionMethodConfig,
)
from stella.hvs_contribution_extraction.roster_stage import (
    ROSTER_COMPLETE,
    run_contribution_roster_stage,
)
from stella.hvs_contribution_extraction.schema_check import (
    validate_contribution_document,
)
from stella.hvs_extraction.bounded_call import Transport
from stella.schema_registry import schema_ref


def prepare_contribution_input(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    config: HvsContributionMethodConfig,
    run_dir: Path,
) -> dict[str, Any]:
    """Build and persist the contribution prepared_input (no model calls)."""

    artifact = build_prepared_input(
        workspace,
        arxiv_id,
        roster_budget=config.roster_context_budget,
        field_budget=config.measurement_context_budget,
    )
    artifact["schema"] = schema_ref("hvs_contribution_extraction.prepared_input")
    write_prepared_input(workspace, run_id, artifact, run_dir=run_dir)
    return artifact


def run_contribution_paper(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    config: HvsContributionMethodConfig,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    progress=None,
    run_dir: Path,
) -> dict[str, Any]:
    """Run the complete contribution chain for one paper."""

    if run_dir is None:
        raise ValueError(
            "run_dir is required: the contribution pipeline never writes "
            "into a benchmark campaign"
        )
    run_dir = Path(run_dir)
    paper_dir = run_dir / "papers" / arxiv_id

    prepared = prepare_contribution_input(
        workspace, run_id, arxiv_id, config=config, run_dir=run_dir
    )
    paper_context_sha256 = (prepared.get("manuscript") or {}).get("view_sha256", "")

    roster = run_contribution_roster_stage(
        workspace,
        run_id,
        arxiv_id,
        config=config,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
        progress=progress,
        run_dir=run_dir,
    )
    if roster["status"] == ROSTER_COMPLETE and prepared["status"] == "prepared":
        run_measurement_stage(
            workspace,
            run_id,
            arxiv_id,
            config=config,
            transport=transport,
            api_key=api_key,
            base_url=base_url,
            sleep=sleep,
            progress=progress,
            run_dir=run_dir,
        )
    elif roster["status"] == ROSTER_COMPLETE and prepared["status"] != "prepared":
        # A non-preparable input cannot reach a trusted measurement stage.
        pass

    result = assemble_contribution_paper_result(
        workspace, run_id, arxiv_id, run_dir=run_dir
    )
    document = write_contribution_document(
        paper_dir / "paper_result.json",
        method_fingerprint=config.method_fingerprint(),
        component_hashes=config.components.model_dump(mode="json"),
        paper_context_sha256=paper_context_sha256,
    )
    validate_contribution_document(document)
    return {
        "status": result["status"],
        "roster_status": result.get("roster_status"),
        "document_status": document["extraction"]["status"],
        "paper_dir": str(paper_dir),
        "canonical_path": str(paper_dir / "literature_hvs_contributions.json"),
    }
