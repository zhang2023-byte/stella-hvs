#!/usr/bin/env python3
"""Run the contribution-first HVS extraction for one paper (pre-gold, local).

Default action is a preflight: it prepares the paper context in memory,
reports the size/status estimate, performs no API call, and writes no run.
A real provider call requires --execute together with an explicit provider,
model, and API-key environment variable; runs land only under the ignored,
non-formal contribution run root and never inside a benchmark campaign.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

import os  # noqa: E402

from stella.hvs_extraction.method_config import (  # noqa: E402
    HvsComponentHashes,
    HvsContextBudget,
    HvsModelRoute,
)
from stella.hvs_contribution_extraction.method_config import (  # noqa: E402
    HvsContributionMethodConfig,
)
from stella.hvs_contribution_extraction.run import (  # noqa: E402
    run_local_contribution_extraction,
)
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local, non-formal contribution-first HVS extraction (one paper).",
    )
    parser.add_argument("--arxiv-id", required=True, help="One unversioned arXiv id.")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Prepare and size the paper context without any API call or run (default when --execute is absent).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Authorize a real provider run; requires --provider, --model, and an API key.",
    )
    parser.add_argument("--provider", help="Explicit provider id for --execute.")
    parser.add_argument("--model", help="Explicit model id for --execute.")
    parser.add_argument(
        "--api-key-env",
        default="LLM_API_KEY",
        help="Environment variable holding the API key for --execute.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Explicit base URL for --execute (defaults to LLM_BASE_URL).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional fresh contribution run id; must be one safe path segment.",
    )
    parser.add_argument(
        "--fake-transport",
        action="store_true",
        help="Testing only: replay fixture responses instead of any network call.",
    )
    parser.add_argument(
        "--fake-roster-response",
        default=None,
        help="JSON file with the fake submit_contribution_roster payload (requires --fake-transport).",
    )
    parser.add_argument(
        "--fake-quantity-response",
        default=None,
        help="JSON file with the fake submit_object_quantities payload (requires --fake-transport).",
    )
    return parser


def preflight(workspace: Path, arxiv_id: str) -> int:
    from stella.hvs_extraction.prepare import build_prepared_input

    budget = HvsContextBudget(
        model_context_limit=900000,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=0,
        reserve_output=8000,
        reserve_provider_framing=1000,
    )
    artifact = build_prepared_input(
        workspace, arxiv_id, roster_budget=budget, field_budget=budget
    )
    print(f"preflight status: {artifact['status']}")
    if artifact["status"] != "prepared":
        print(json.dumps(artifact.get("failure"), ensure_ascii=False))
        return 1
    context = artifact["context"]["budget_inputs"]
    print(
        "manuscript view estimate: "
        f"{context['manuscript_view_estimate_tokens']} tokens "
        f"(roster budget {context['roster_input_budget']})"
    )
    print("no API call was made and no run was written")
    return 0


def fake_transport_from_files(roster_payload: dict, quantity_payload: dict):
    class _FakeTransport:
        def __call__(self, **kwargs):
            tools = kwargs.get("extra_body", {}).get("tools") or []
            name = tools[0]["function"]["name"] if tools else ""
            payload = (
                roster_payload
                if name == "submit_contribution_roster"
                else quantity_payload
            )
            return {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_fake",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(
                                            payload, ensure_ascii=False
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ]
            }

    return _FakeTransport()


def main(argv: list[str] | None = None, workspace: Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = workspace or WORKSPACE
    arxiv_id = validate_unversioned_arxiv_id(args.arxiv_id)

    if not args.execute and not args.fake_transport:
        return preflight(workspace, arxiv_id)

    if args.fake_transport:
        if not (args.fake_roster_response and args.fake_quantity_response):
            print(
                "--fake-transport requires --fake-roster-response and "
                "--fake-quantity-response",
                file=sys.stderr,
            )
            return 2
        roster_payload = json.loads(
            Path(args.fake_roster_response).read_text(encoding="utf-8")
        )
        quantity_payload = json.loads(
            Path(args.fake_quantity_response).read_text(encoding="utf-8")
        )
        transport = fake_transport_from_files(roster_payload, quantity_payload)
        api_key = ""
        base_url = ""
        route = HvsModelRoute(
            provider="deepseek",
            model="deepseek-v4-pro",
            structured_output_mode="tool_submission",
            temperature=0.0,
            top_p=1.0,
            seed_honored=False,
        )
    else:
        if not (args.provider and args.model):
            print(
                "--execute requires explicit --provider and --model authority",
                file=sys.stderr,
            )
            return 2
        api_key = os.environ.get(args.api_key_env, "")
        if not api_key:
            print(
                f"--execute requires the API key environment variable {args.api_key_env}",
                file=sys.stderr,
            )
            return 2
        base_url = args.base_url or os.environ.get("LLM_BASE_URL", "")
        if not base_url:
            print("--execute requires --base-url or LLM_BASE_URL", file=sys.stderr)
            return 2
        from stella.lit.llm_batch import chat_completion_raw

        transport = chat_completion_raw
        route = HvsModelRoute(
            provider=args.provider,
            model=args.model,
            structured_output_mode="tool_submission",
            temperature=0.0,
            top_p=1.0,
            seed_honored=False,
        )

    budget = HvsContextBudget(
        model_context_limit=900000,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=0,
        reserve_output=8000,
        reserve_provider_framing=1000,
    )
    config = HvsContributionMethodConfig(
        roster_model=route,
        quantity_model=route,
        roster_context_budget=budget,
        quantity_context_budget=budget,
        components=HvsComponentHashes(
            rule_profile_sha256={"hvs_contribution_v1": "pending"},
            prompt_template_sha256={"pending": "pending"},
            submission_schema_sha256={"pending": "pending"},
        ),
    )
    summary = run_local_contribution_extraction(
        workspace,
        [arxiv_id],
        config=config,
        transport=transport,
        run_id=args.run_id,
        api_key=api_key,
        base_url=base_url,
        sleep=lambda _: None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
