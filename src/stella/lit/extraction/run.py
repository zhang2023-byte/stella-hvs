"""Local, non-formal contribution extraction runs.

Each run reserves a never-reusable id under the ignored contribution run
root, freezes the method configuration (rules, prompts, schemas, semantic
implementations, model
routes, budgets, and request policies) into
the method fingerprint before any provider call, and writes an aggregate
run summary. These are local production/engineering artifacts, never benchmark
results, and never touch a benchmark campaign.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.lit.extraction.method_config import (
    CONTRIBUTION_RULE_PROFILE,
    HvsContributionMethodConfig,
    HvsModelRoute,
)
from stella.lit.extraction.quantity_prompts import (
    QUANTITY_SYSTEM_TEMPLATE,
    QUANTITY_USER_TEMPLATE,
)
from stella.lit.extraction.quantity_schema import (
    build_quantity_submission_schema,
)
from stella.lit.extraction.paper_runner import run_contribution_paper
from stella.lit.extraction.roster_prompts import (
    EXTRACTOR_SYSTEM_TEMPLATE,
    EXTRACTOR_USER_TEMPLATE,
    JSON_OBJECT_SYSTEM_AMENDMENT,
    JSON_OBJECT_SYSTEM_REPLACEMENT,
    JSON_OBJECT_USER_AMENDMENT,
    JSON_OBJECT_USER_REPLACEMENT,
)
from stella.lit.extraction.roster_stage import _atomic_write_json
from stella.lit.extraction.run_policy import (
    new_contribution_run_id,
    reserve_contribution_run_dir,
)
from stella.lit.extraction.submission_schema import (
    build_contribution_roster_submission_schema,
)
from stella.lit.extraction.bounded_call import Transport
from stella.lit.extraction_rules import rule_profile_sha256
from stella.schema_registry import schema_ref


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_contribution_components(workspace: Path) -> dict[str, dict[str, str]]:
    """Compute the deterministic component hashes of the contribution method."""

    # Representative path lists so every schema branch participates in
    # the component hash: the ECSV evidence branch only exists when an
    # ECSV path is allowed, so freezing with empty lists would hide it.
    roster_schema = build_contribution_roster_submission_schema(
        ["main.tex"]
    )
    quantity_schema = build_quantity_submission_schema(
        ["main.tex"], ["catalog_tables/table.ecsv"]
    )
    implementation_root = Path(__file__).resolve().parent
    semantic_files = (
        "bounded_call.py",
        "field_validate.py",
        "quantity_validate.py",
        "range_expand.py",
        "roster_validate.py",
        "schema_check.py",
        "roster_stage.py",
        "quantity_stage.py",
        "structured_output.py",
        "transport.py",
    )
    return {
        "rule_profile_sha256": {
            CONTRIBUTION_RULE_PROFILE: rule_profile_sha256(
                workspace, CONTRIBUTION_RULE_PROFILE
            ),
        },
        "prompt_template_sha256": {
            "contribution_roster_model": _sha256(
                json.dumps(
                    {
                        "system": EXTRACTOR_SYSTEM_TEMPLATE,
                        "user": EXTRACTOR_USER_TEMPLATE,
                        "json_object_system_amendment": JSON_OBJECT_SYSTEM_AMENDMENT,
                        "json_object_system_replacement": JSON_OBJECT_SYSTEM_REPLACEMENT,
                        "json_object_user_amendment": JSON_OBJECT_USER_AMENDMENT,
                        "json_object_user_replacement": JSON_OBJECT_USER_REPLACEMENT,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            ),
            "contribution_quantity_model": _sha256(
                json.dumps(
                    {
                        "system": QUANTITY_SYSTEM_TEMPLATE,
                        "user": QUANTITY_USER_TEMPLATE,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            ),
        },
        "submission_schema_sha256": {
            "submit_contribution_roster": _sha256(
                json.dumps(roster_schema, ensure_ascii=False, sort_keys=True)
            ),
            "submit_object_quantities": _sha256(
                json.dumps(quantity_schema, ensure_ascii=False, sort_keys=True)
            ),
        },
        "semantic_implementation_sha256": {
            name: _sha256_file(implementation_root / name)
            for name in semantic_files
        },
    }


def freeze_contribution_method_config(
    workspace: Path, config: HvsContributionMethodConfig
) -> HvsContributionMethodConfig:
    """Return the config with computed component hashes frozen in."""

    config.assert_frozen()
    return config.model_copy(
        update={"components": type(config.components)(
            **freeze_contribution_components(workspace)
        )}
    )


def run_local_contribution_extraction(
    workspace: Path,
    arxiv_ids: list[str],
    *,
    config: HvsContributionMethodConfig,
    transport: Transport,
    run_id: str | None = None,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    progress=None,
) -> dict[str, Any]:
    """Execute one fresh immutable local contribution run exactly once."""

    config.assert_frozen()
    frozen = freeze_contribution_method_config(workspace, config)
    method_fingerprint = frozen.method_fingerprint()
    resolved_run_id = run_id or new_contribution_run_id()
    run_dir = reserve_contribution_run_dir(workspace, resolved_run_id)
    _atomic_write_json(
        run_dir / "method_config.json",
        frozen.model_dump(mode="json", by_alias=True)
        | {"method_fingerprint": method_fingerprint},
    )

    papers: dict[str, dict[str, Any]] = {}
    for arxiv_id in arxiv_ids:
        papers[arxiv_id] = run_contribution_paper(
            workspace,
            resolved_run_id,
            arxiv_id,
            config=frozen,
            transport=transport,
            api_key=api_key,
            base_url=base_url,
            sleep=sleep,
            progress=progress,
            run_dir=run_dir,
        )

    statuses = [paper["status"] for paper in papers.values()]
    if not statuses or any(status == "failed" for status in statuses):
        summary_status = "failed"
    elif any(status == "partial" for status in statuses):
        summary_status = "partial"
    else:
        summary_status = "complete"
    summary = {
        "schema": schema_ref("hvs_contribution_extraction.run_summary"),
        "generated_at": _utc_now(),
        "run_id": resolved_run_id,
        "status": summary_status,
        "papers": papers,
        "method_fingerprint": method_fingerprint,
        "non_formal_note": (
            "pre-campaign local contribution run; not a benchmark result"
        ),
    }
    _atomic_write_json(run_dir / "run_summary.json", summary)
    return summary
