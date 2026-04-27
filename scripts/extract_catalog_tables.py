#!/usr/bin/env python3
"""Extract reviewed catalog tables into CSV plus provenance JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.catalog_extraction import (  # noqa: E402
    AGENT_LOCATOR_ALWAYS,
    AGENT_LOCATOR_OFF,
    LLMExternalPageLocator,
    MAX_EXTERNAL_BYTES,
    UnavailableExternalPageLocator,
    extract_all_reviewed_catalog_tables,
    extract_catalog_tables,
)
from high_velocity_lit.config import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL  # noqa: E402
from high_velocity_lit.env import env_value, load_env_files  # noqa: E402
from high_velocity_lit.title_classifier import load_llm_api_key  # noqa: E402


load_env_files(WORKSPACE)


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected True or False")


def parse_fetch_external(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "auto":
        return "Auto"
    if normalized in {"true", "t", "1", "yes", "y"}:
        return "True"
    if normalized in {"false", "f", "0", "no", "n"}:
        return "False"
    raise argparse.ArgumentTypeError("expected Auto, True, or False")


def parse_agent_locator(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"off", "false", "f", "0", "no", "n"}:
        return AGENT_LOCATOR_OFF
    if normalized in {"always", "auto", "true", "t", "1", "yes", "y"}:
        return AGENT_LOCATOR_ALWAYS
    raise argparse.ArgumentTypeError("expected Off or Always")


def fetch_external_enabled(value: str, *, all_reviewed: bool) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    return not all_reviewed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract reviewed high-velocity-star catalog tables and external catalog resources to CSV."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--arxiv-id", help="Extract reviewed catalog candidates for one arXiv ID.")
    selection.add_argument("--all-reviewed", action="store_true", help="Extract all reviewed papers with catalog candidates.")
    parser.add_argument("--candidate-id", default=None, help="Extract one catalog candidate ID. Requires --arxiv-id.")
    parser.add_argument("--resource-id", default=None, help="Extract one external_resources[].id. Requires --arxiv-id.")
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--fetch-external", type=parse_fetch_external, default="Auto", metavar="Auto|True|False", help="Network policy for external resources. Auto enables network for --arxiv-id and disables it for --all-reviewed.")
    parser.add_argument("--max-external-files", type=int, default=5, help="Maximum downloaded external files per resource. Default: 5.")
    parser.add_argument("--max-external-bytes", type=int, default=MAX_EXTERNAL_BYTES, help="Maximum bytes per downloaded external file. Default: 52428800.")
    parser.add_argument("--external-timeout", type=int, default=30, help="HTTP timeout in seconds for external resources. Default: 30.")
    parser.add_argument("--agent-locator", type=parse_agent_locator, default=AGENT_LOCATOR_ALWAYS, metavar="Off|Always", help="Use an LLM agent to choose bounded landing-page download candidates. Default: Always.")
    parser.add_argument("--llm-api-key", default=env_value("LLM_API_KEY", "OPENAI_API_KEY", "DEEPXIV_AGENT_API_KEY"), help="OpenAI-compatible API key for the Agent locator. Defaults to environment or .env.")
    parser.add_argument("--llm-base-url", default=env_value("LLM_BASE_URL", "OPENAI_BASE_URL", "DEEPXIV_AGENT_BASE_URL", default=DEFAULT_LLM_BASE_URL))
    parser.add_argument("--llm-model", default=env_value("LLM_MODEL", "OPENAI_MODEL", "DEEPXIV_AGENT_MODEL", default=DEFAULT_LLM_MODEL))
    parser.add_argument("--llm-thinking", default=env_value("LLM_THINKING"))
    parser.add_argument("--llm-reasoning-effort", default=env_value("LLM_REASONING_EFFORT"))
    parser.add_argument("--dry-run", type=parse_bool, default=False, metavar="True|False", help="Parse and report without writing files. Default: False.")
    parser.add_argument("--overwrite", type=parse_bool, default=False, metavar="True|False", help="Rewrite existing source excerpts and CSV files. Default: False.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    literature_dir = args.literature_dir.expanduser()
    if args.candidate_id and args.resource_id:
        raise SystemExit("--candidate-id and --resource-id are mutually exclusive")
    if (args.candidate_id or args.resource_id) and args.all_reviewed:
        raise SystemExit("--candidate-id and --resource-id require --arxiv-id")
    if not literature_dir.exists():
        raise SystemExit(f"literature directory does not exist: {literature_dir}")
    if args.max_external_files < 1:
        raise SystemExit("--max-external-files must be at least 1")
    if args.max_external_bytes < 1:
        raise SystemExit("--max-external-bytes must be at least 1")
    fetch_external = fetch_external_enabled(args.fetch_external, all_reviewed=args.all_reviewed)
    agent_locator = None
    if args.agent_locator != AGENT_LOCATOR_OFF:
        api_key = load_llm_api_key(args.llm_api_key)
        if api_key:
            agent_locator = LLMExternalPageLocator(
                api_key=api_key,
                base_url=args.llm_base_url,
                model=args.llm_model,
                thinking=args.llm_thinking,
                reasoning_effort=args.llm_reasoning_effort,
                timeout=args.external_timeout,
            )
        else:
            agent_locator = UnavailableExternalPageLocator(
                stopped_reason="missing_api_key",
                error="agent locator enabled but no LLM API key is configured",
            )

    try:
        if args.all_reviewed:
            payload = extract_all_reviewed_catalog_tables(
                literature_dir=literature_dir,
                workspace=WORKSPACE,
                fetch_external=fetch_external,
                max_external_files=args.max_external_files,
                max_external_bytes=args.max_external_bytes,
                external_timeout=args.external_timeout,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
                agent_locator_mode=args.agent_locator,
                agent_locator=agent_locator,
            )
        else:
            payload = extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id=str(args.arxiv_id),
                workspace=WORKSPACE,
                candidate_id=args.candidate_id,
                resource_id=args.resource_id,
                fetch_external=fetch_external,
                max_external_files=args.max_external_files,
                max_external_bytes=args.max_external_bytes,
                external_timeout=args.external_timeout,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
                agent_locator_mode=args.agent_locator,
                agent_locator=agent_locator,
            )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
