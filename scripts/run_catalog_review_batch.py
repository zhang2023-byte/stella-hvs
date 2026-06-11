#!/usr/bin/env python3
"""LLM-assisted batch catalog_review driver over archived papers.

For every paper in the month window whose catalog_assessment marks an
observational catalog, this builds the local table/resource inventory,
asks an OpenAI-compatible LLM to classify object-level catalog assets,
and writes literature/<arxiv_id>/catalog_review.json. Promoted from the
exploratory logs/catalog_review_driver_2023_2026.py one-off.
"""

from __future__ import annotations

import argparse
import json
import signal
from datetime import datetime
from pathlib import Path
from typing import Any

from stella.lit.catalog_review import (
    CATALOG_REVIEW_SCHEMA_VERSION,
    build_catalog_candidate_inventory,
    write_json,
)
from stella.lit.config import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL
from stella.lit.env import env_value, load_env_files
from stella.lit.llm_batch import chat_completion_json, shard_items

WORKSPACE = Path(__file__).resolve().parents[1]
REVIEW_TIMEOUT_SECONDS = 240
MAX_EXCERPT_CHARS = 1400
MAX_EXTERNAL_MENTIONS = 40

SYSTEM_PROMPT = "You are reviewing astrophysics paper inventories for object-level high-velocity-star catalog data."
REVIEW_PROMPT = (
    "Review one Stella high-velocity-star paper inventory. Decide which listed TeX tables, local "
    "machine-readable files, or explicit external-resource mentions are true object-level catalogs "
    "for high-velocity, hypervelocity, runaway, unbound, escaping, or ejected stellar objects.\n\n"
    "Include only resources that list or directly provide object-level stellar data: names/source IDs, "
    "coordinates, astrometry, radial velocities, spectra, abundances, orbit quantities, candidate flags, "
    "or follow-up measurements. Reject model tables, simulation summaries, observing logs, general survey "
    "descriptions, stellar-parameter tables unrelated to high-velocity/runaway context, and generic URLs.\n\n"
    "Return only this JSON object shape:\n"
    "{\n"
    '  "status": "reviewed|partial|needs_review|source_missing",\n'
    '  "summary": "short summary",\n'
    '  "tables": [{"id": "t1", "catalog_role": "new_catalog|compiled_catalog|followup_observations|uses_existing_catalog|unclear", "object_scope": "single_object|multiple_objects|none|unclear", "data_products": ["source_ids"], "meaning": "...", "evidence": "...", "confidence": 0.0, "comments": ""}],\n'
    '  "resources": [{"id": "f1 or e1", "meaning": "...", "evidence": "...", "confidence": 0.0, "comments": ""}],\n'
    '  "rejections": [{"id": "t2", "reason": "short reason"}]\n'
    "}\n\nInventory:\n"
)


class ReviewTimeout(Exception):
    pass


def on_alarm(signum: int, frame: Any) -> None:
    raise ReviewTimeout("per-paper catalog review timeout")


def compact(text: Any, limit: int = MAX_EXCERPT_CHARS) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 20] + " ... [truncated]"


def selected_ids(notes_dir: Path, *, month_from: str, month_to: str) -> list[str]:
    ids: list[str] = []
    for path in sorted(notes_dir.glob("[0-9][0-9][0-9][0-9]/*/*.json")):
        if path.name.endswith(".title-triage.json") or path.name == "index.json":
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        month = str(record.get("month") or "")
        if not (month_from <= month <= month_to):
            continue
        for paper in record.get("papers") or []:
            if (paper.get("catalog_assessment") or {}).get("has_observational_catalog") is not True:
                continue
            arxiv_id = str(paper.get("arxiv_id") or "").strip()
            if arxiv_id and arxiv_id not in ids:
                ids.append(arxiv_id)
    return ids


def llm_item_from_inventory(inventory: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    table_map: dict[str, dict[str, Any]] = {}
    file_map: dict[str, dict[str, Any]] = {}
    external_map: dict[str, dict[str, Any]] = {}
    tables = []
    for index, candidate in enumerate(inventory.get("table_candidates") or [], 1):
        cid = f"t{index}"
        table_map[cid] = candidate
        tables.append(
            {
                "id": cid,
                "environment": candidate.get("environment"),
                "path": candidate.get("path"),
                "start_line": candidate.get("start_line"),
                "end_line": candidate.get("end_line"),
                "caption": compact(candidate.get("caption"), 700),
                "label": candidate.get("label"),
                "excerpt": compact(candidate.get("latex_excerpt")),
            }
        )
    files = []
    for index, resource in enumerate(inventory.get("local_machine_readable_files") or [], 1):
        cid = f"f{index}"
        file_map[cid] = resource
        files.append(resource | {"id": cid})
    mentions = []
    for index, mention in enumerate((inventory.get("external_resource_mentions") or [])[:MAX_EXTERNAL_MENTIONS], 1):
        cid = f"e{index}"
        external_map[cid] = mention
        mentions.append(
            {
                "id": cid,
                "path": mention.get("path"),
                "line": mention.get("line"),
                "url": mention.get("url"),
                "context": compact(mention.get("context"), 900),
            }
        )
    return (
        {
            "paper": inventory.get("paper") or {},
            "source": inventory.get("source") or {},
            "tables": tables,
            "local_machine_readable_files": files,
            "external_resource_mentions": mentions,
        },
        {"tables": table_map, "files": file_map, "external": external_map},
    )


def table_review_item(output: dict[str, Any], candidate: dict[str, Any], ordinal: int) -> dict[str, Any]:
    return {
        "id": f"table-{ordinal}",
        "kind": "latex_table",
        "catalog_role": str(output.get("catalog_role") or "unclear"),
        "object_scope": str(output.get("object_scope") or "unclear"),
        "data_products": [str(item) for item in (output.get("data_products") or [])],
        "source_refs": [
            {
                "path": candidate.get("path") or "",
                "start_line": int(candidate.get("start_line") or 0),
                "end_line": int(candidate.get("end_line") or 0),
                "caption": candidate.get("caption") or "",
                "label": candidate.get("label") or "",
            }
        ],
        "latex_excerpt": candidate.get("latex_excerpt") or "",
        "meaning": str(output.get("meaning") or ""),
        "evidence": str(output.get("evidence") or ""),
        "confidence": float(output.get("confidence") or 0),
        "comments": str(output.get("comments") or ""),
    }


def resource_review_item(output: dict[str, Any], resource: dict[str, Any], ordinal: int, *, external: bool) -> dict[str, Any]:
    return {
        "id": f"resource-{ordinal}",
        "kind": "external_url" if external else "local_machine_readable_file",
        "url": resource.get("url") or "",
        "local_path": resource.get("path") or "",
        "meaning": str(output.get("meaning") or ""),
        "evidence": str(output.get("evidence") or ""),
        "confidence": float(output.get("confidence") or 0),
        "comments": str(output.get("comments") or ""),
    }


def build_review_record(inventory: dict[str, Any], llm_output: dict[str, Any], maps: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    paper = inventory.get("paper") or {}
    source = inventory.get("source") or {}
    selected_table_ids = set()
    selected_resource_ids = set()
    catalog_candidates = []
    for ordinal, item in enumerate(llm_output.get("tables") or [], 1):
        cid = str(item.get("id") or "")
        candidate = maps["tables"].get(cid)
        if not candidate:
            continue
        selected_table_ids.add(cid)
        catalog_candidates.append(table_review_item(item, candidate, ordinal))
    external_resources = []
    resource_ordinal = 1
    for item in llm_output.get("resources") or []:
        cid = str(item.get("id") or "")
        if cid in maps["files"]:
            selected_resource_ids.add(cid)
            external_resources.append(resource_review_item(item, maps["files"][cid], resource_ordinal, external=False))
            resource_ordinal += 1
        elif cid in maps["external"]:
            selected_resource_ids.add(cid)
            external_resources.append(resource_review_item(item, maps["external"][cid], resource_ordinal, external=True))
            resource_ordinal += 1

    rejection_reasons = {str(item.get("id") or ""): str(item.get("reason") or "") for item in llm_output.get("rejections") or []}
    rejected = []
    for cid, candidate in maps["tables"].items():
        if cid in selected_table_ids:
            continue
        rejected.append(
            {
                "id": f"rejected-{len(rejected) + 1}",
                "kind": "latex_table",
                "source_ref": {
                    "path": candidate.get("path") or "",
                    "start_line": int(candidate.get("start_line") or 0),
                    "end_line": int(candidate.get("end_line") or 0),
                    "caption": candidate.get("caption") or "",
                    "label": candidate.get("label") or "",
                },
                "decision": "rejected",
                "reason": rejection_reasons.get(cid) or "LLM-assisted review did not identify this as a high-velocity-star object catalog.",
            }
        )

    status = str(llm_output.get("status") or "reviewed")
    if not source.get("source_available"):
        status = "source_missing"
    return {
        "schema_version": CATALOG_REVIEW_SCHEMA_VERSION,
        "paper": {
            "arxiv_id": paper.get("arxiv_id") or "",
            "title": paper.get("title") or "",
            "month": paper.get("month") or "",
            "source_note_json": paper.get("source_note_json") or "",
            "links": paper.get("links") or {},
        },
        "source": source,
        "review": {
            "status": status,
            "reviewed_at": datetime.now().isoformat(timespec="seconds"),
            "reviewer": "agent",
            "summary": str(llm_output.get("summary") or ""),
        },
        "catalog_candidates": catalog_candidates,
        "external_resources": external_resources,
        "rejected_candidates": rejected,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="month_from", required=True, metavar="YYYY-MM", help="First month (inclusive).")
    parser.add_argument("--to", dest="month_to", required=True, metavar="YYYY-MM", help="Last month (inclusive).")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--notes-dir", type=Path, default=WORKSPACE / "notes")
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--log-path", type=Path, default=WORKSPACE / "logs" / "catalog_review_batch.jsonl")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    load_env_files(WORKSPACE)
    api_key = env_value("LLM_API_KEY", "OPENAI_API_KEY", "DEEPXIV_AGENT_API_KEY")
    if not api_key:
        raise SystemExit("LLM_API_KEY, OPENAI_API_KEY, or DEEPXIV_AGENT_API_KEY is required")
    base_url = env_value("LLM_BASE_URL", "OPENAI_BASE_URL", "DEEPXIV_AGENT_BASE_URL", default=DEFAULT_LLM_BASE_URL)
    model = env_value("LLM_MODEL", "OPENAI_MODEL", "DEEPXIV_AGENT_MODEL", default=DEFAULT_LLM_MODEL)
    thinking = env_value("LLM_THINKING")
    reasoning_effort = env_value("LLM_REASONING_EFFORT")

    ids = shard_items(
        selected_ids(args.notes_dir, month_from=args.month_from, month_to=args.month_to),
        shard_index=args.shard_index,
        shard_count=args.shard_count,
    )
    signal.signal(signal.SIGALRM, on_alarm)
    args.log_path.parent.mkdir(exist_ok=True)
    shard_log_path = args.log_path.with_name(
        f"{args.log_path.stem}.shard-{args.shard_index + 1}-of-{args.shard_count}{args.log_path.suffix}"
    )

    with shard_log_path.open("a", encoding="utf-8") as log:
        for index, arxiv_id in enumerate(ids, 1):
            print(f"[{index}/{len(ids)}] review {arxiv_id}", flush=True)
            entry: dict[str, Any] = {"arxiv_id": arxiv_id, "ok": False}
            try:
                signal.alarm(REVIEW_TIMEOUT_SECONDS)
                inventory = build_catalog_candidate_inventory(
                    literature_dir=args.literature_dir, arxiv_id=arxiv_id, workspace=WORKSPACE
                )
                llm_item, maps = llm_item_from_inventory(inventory)
                if not inventory.get("source", {}).get("source_available"):
                    llm_output = {"status": "source_missing", "summary": "Source archive is not available.", "tables": [], "resources": [], "rejections": []}
                elif not llm_item["tables"] and not llm_item["local_machine_readable_files"] and not llm_item["external_resource_mentions"]:
                    llm_output = {"status": "reviewed", "summary": "No TeX tables or explicit data-resource mentions were inventoried.", "tables": [], "resources": [], "rejections": []}
                else:
                    llm_output = chat_completion_json(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        thinking=thinking,
                        reasoning_effort=reasoning_effort,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": REVIEW_PROMPT + json.dumps(llm_item, ensure_ascii=False)},
                        ],
                    )
                review = build_review_record(inventory, llm_output, maps)
                review_path = args.literature_dir / arxiv_id / "catalog_review.json"
                write_json(review_path, review)
                signal.alarm(0)
                entry.update(
                    {
                        "ok": True,
                        "status": review["review"]["status"],
                        "catalog_candidates": len(review["catalog_candidates"]),
                        "external_resources": len(review["external_resources"]),
                        "review_path": str(review_path.relative_to(WORKSPACE)),
                    }
                )
                print(
                    f"  ok status={entry['status']} candidates={entry['catalog_candidates']} resources={entry['external_resources']}",
                    flush=True,
                )
            except Exception as exc:
                signal.alarm(0)
                entry.update({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
                print(f"  ERROR {type(exc).__name__}: {exc}", flush=True)
            finally:
                log.write(json.dumps(entry, ensure_ascii=False) + "\n")
                log.flush()


if __name__ == "__main__":
    main()
