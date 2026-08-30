"""One paper's full contribution extraction chain.

prepare -> contribution roster -> per-object quantity extraction ->
finalize -> canonical ``literature_hvs_contributions`` document. The
preparation reuses the neutral TeX/ECSV machinery; the artifact is stamped
with the contribution pipeline's own transient schema and written only into
the caller's non-formal run directory.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from stella.lit.extraction.prepare import (
    build_prepared_input,
    write_prepared_input,
)
from stella.lit.extraction.core_document import (
    write_contribution_document,
)
from stella.lit.extraction.finalize import (
    PAPER_FAILED,
    assemble_contribution_paper_result,
)
from stella.lit.extraction.quantity_stage import (
    resume_quantity_stage,
    retryable_quantity_record_ids,
    run_quantity_stage,
)
from stella.lit.extraction.method_config import (
    HvsContributionMethodConfig,
)
from stella.lit.extraction.roster_stage import (
    ROSTER_COMPLETE,
    run_contribution_roster_stage,
)
from stella.lit.extraction.run_policy import (
    assert_contribution_run_dir,
)
from stella.lit.extraction.schema_check import (
    validate_contribution_document,
)
from stella.lit.extraction.bounded_call import Transport
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
        field_budget=config.quantity_context_budget,
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
    quantity_transport_factory: Callable[[], Transport] | None = None,
    quantity_concurrency: int = 1,
    run_dir: Path,
) -> dict[str, Any]:
    """Run the complete contribution chain for one paper."""

    run_dir = assert_contribution_run_dir(workspace, run_id, run_dir)
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
        run_quantity_stage(
            workspace,
            run_id,
            arxiv_id,
            config=config,
            transport=transport,
            api_key=api_key,
            base_url=base_url,
            sleep=sleep,
            progress=progress,
            transport_factory=quantity_transport_factory,
            quantity_concurrency=quantity_concurrency,
            run_dir=run_dir,
        )
    elif roster["status"] == ROSTER_COMPLETE and prepared["status"] != "prepared":
        # A non-preparable input cannot reach a trusted quantity stage.
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
    resumable_record_ids = retryable_quantity_record_ids(paper_dir)
    return {
        "status": result["status"],
        "roster_status": result.get("roster_status"),
        "document_status": document["extraction"]["status"],
        "paper_dir": str(paper_dir),
        "canonical_path": str(paper_dir / "literature_hvs_contributions.json"),
        "resumable_quantity_record_ids": resumable_record_ids,
    }


def resume_contribution_paper_quantities(
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
    quantity_transport_factory: Callable[[], Transport] | None = None,
    quantity_concurrency: int = 1,
    run_dir: Path,
) -> dict[str, Any]:
    """Resume only retryable quantity objects in an active benchmark attempt."""

    run_dir = assert_contribution_run_dir(workspace, run_id, run_dir)
    paper_dir = run_dir / "papers" / arxiv_id
    prepared = json.loads(
        (run_dir / "prepared_inputs" / f"{arxiv_id}.json").read_text(
            encoding="utf-8"
        )
    )
    resume_result = resume_quantity_stage(
        workspace,
        run_id,
        arxiv_id,
        config=config,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
        progress=progress,
        transport_factory=quantity_transport_factory,
        quantity_concurrency=quantity_concurrency,
        run_dir=run_dir,
    )
    result = assemble_contribution_paper_result(
        workspace, run_id, arxiv_id, run_dir=run_dir
    )
    paper_context_sha256 = (prepared.get("manuscript") or {}).get(
        "view_sha256", ""
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
        "canonical_path": str(
            paper_dir / "literature_hvs_contributions.json"
        ),
        "resumed_quantity_record_ids": resume_result.get(
            "resumed_record_ids", []
        ),
        "resumable_quantity_record_ids": retryable_quantity_record_ids(
            paper_dir
        ),
    }
