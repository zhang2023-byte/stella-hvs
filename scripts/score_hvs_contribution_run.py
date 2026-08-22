#!/usr/bin/env python3
"""Score a contribution run against contribution gold (pre-activation).

Explicit inputs only: one or more contribution gold YAML files, one or more
``literature_hvs_contributions`` documents, and explicit output paths. The
public scorecard contains aggregates and hashes only; item-level details go
to the private output. V6 ``benchmark.gold_annotation`` payloads are
rejected. This tool has not been run against real gold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

from stella.benchmark.hvs_contribution_scoring import (
    build_private_details,
    build_public_scorecard,
    leak_guard,
    score_contribution_suite,
)
from stella.benchmark.hvs_contribution_gold import HvsContributionGoldAnnotation

WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Layered contribution benchmark scoring (pre-activation).",
    )
    parser.add_argument(
        "--gold-yaml",
        action="append",
        required=True,
        type=Path,
        help="Contribution gold annotation YAML (benchmark.hvs_contribution_annotation).",
    )
    parser.add_argument(
        "--ai-doc",
        action="append",
        required=True,
        type=Path,
        help="literature_hvs_contributions.json document from a contribution run.",
    )
    parser.add_argument(
        "--output-public",
        required=True,
        type=Path,
        help="Public scorecard output path (aggregates and hashes only).",
    )
    parser.add_argument(
        "--output-details",
        type=Path,
        default=None,
        help="Private per-item details output path.",
    )
    return parser


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    gold_payloads = []
    input_hashes: dict[str, str] = {}
    for gold_path in args.gold_yaml:
        payload = yaml.safe_load(gold_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SystemExit(f"{gold_path}: gold annotation must be a YAML mapping")
        name = (payload.get("schema") or {}).get("name")
        if name != "benchmark.hvs_contribution_annotation":
            raise SystemExit(
                f"{gold_path}: expected schema benchmark.hvs_contribution_annotation, "
                f"got {name!r}; V6 annotations are rejected by this scorer"
            )
        try:
            annotation = HvsContributionGoldAnnotation.model_validate(payload)
        except Exception as exc:
            raise SystemExit(f"{gold_path}: invalid contribution gold: {exc}") from exc
        validated_payload = annotation.model_dump(mode="json", by_alias=True)
        if any(item.get("arxiv_id") == validated_payload["arxiv_id"] for item in gold_payloads):
            raise SystemExit(
                f"{gold_path}: duplicate contribution gold arxiv_id "
                f"{validated_payload['arxiv_id']}"
            )
        gold_payloads.append(validated_payload)
        input_hashes[gold_path.name] = _sha256_file(gold_path)

    ai_documents: dict[str, dict | None] = {}
    for ai_path in args.ai_doc:
        document = json.loads(ai_path.read_text(encoding="utf-8"))
        name = (document.get("schema") or {}).get("name")
        if name != "literature_hvs_contributions":
            raise SystemExit(
                f"{ai_path}: expected schema literature_hvs_contributions, got {name!r}"
            )
        ai_documents[document["paper"]["arxiv_id"]] = document
        input_hashes[ai_path.name] = _sha256_file(ai_path)

    suite = score_contribution_suite(gold_payloads, ai_documents)
    scorecard = build_public_scorecard(suite, input_hashes=input_hashes)

    forbidden = set()
    for gold_payload in gold_payloads:
        for contribution in gold_payload.get("contributions") or []:
            for key in ("paper_candidate_id", "gaia_source_id"):
                if contribution.get(key):
                    forbidden.add(contribution[key])
            for alias in contribution.get("aliases") or []:
                forbidden.add(alias)
            for group in contribution.get("measurements") or []:
                for value in group.get("values") or []:
                    if value.get("value"):
                        forbidden.add(str(value.get("value")))
    leaks = leak_guard(scorecard, forbidden)
    if leaks:
        print(f"leak guard failed: {leaks}", file=sys.stderr)
        return 3

    args.output_public.parent.mkdir(parents=True, exist_ok=True)
    args.output_public.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {args.output_public}")
    if args.output_details is not None:
        details = build_private_details(suite, input_hashes=input_hashes)
        args.output_details.parent.mkdir(parents=True, exist_ok=True)
        args.output_details.write_text(
            json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Wrote {args.output_details}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
