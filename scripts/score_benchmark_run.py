#!/usr/bin/env python3
"""Score an archived extraction run (or legacy extractions) against gold.

Phase 4 scorer CLI. Reads expert gold from the external private gold store
(STELLA_GOLD_DIR), the AI side from either an archived run directory
(benchmark/runs/<run_id>/<arxiv_id>/literature_hvs_candidates.json) or the
legacy per-paper files under literature/, then writes:

- public scorecard (counts and rates only, no gold content):
      benchmark/scoring/<run_label>/scorecard.json
- private per-candidate details (quotes gold identities and values):
      $STELLA_GOLD_DIR/../scoring-details/<run_label>/details.json

A built-in leak guard refuses to write a public scorecard that contains any
gold candidate identifier or canary string.

Usage:
    conda run -n stella-env python scripts/score_benchmark_run.py \
        --run-dir benchmark/runs/<run_id>
    conda run -n stella-env python scripts/score_benchmark_run.py \
        --legacy-literature
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from stella.benchmark.scoring import (
    load_ai_document,
    load_gold_annotations,
    load_sampling_weights,
    score_run,
)
from stella.lit.env import load_env_files

WORKSPACE = Path(__file__).resolve().parents[1]
GOLD_DIR_ENV = "STELLA_GOLD_DIR"
DEFAULT_MANIFEST = WORKSPACE / "benchmark" / "manifest" / "sampling_manifest.json"
DEFAULT_SCORING_DIR = WORKSPACE / "benchmark" / "scoring"


def default_gold_dir() -> Path | None:
    value = os.environ.get(GOLD_DIR_ENV, "").strip()
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score archived AI extractions against expert gold."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Archived run directory, e.g. benchmark/runs/<run_id>.",
    )
    source.add_argument(
        "--legacy-literature",
        action="store_true",
        help="Score the legacy per-paper files under literature/ instead of a run.",
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=None,
        help=f"External private gold annotation root. Default: ${GOLD_DIR_ENV}.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Sampling manifest for per-paper weights.",
    )
    parser.add_argument(
        "--run-label",
        default=None,
        help="Scorecard directory name. Default: run dir name or 'legacy-literature'.",
    )
    parser.add_argument(
        "--scoring-dir",
        type=Path,
        default=DEFAULT_SCORING_DIR,
        help="Public scorecard root. Default: benchmark/scoring/.",
    )
    parser.add_argument(
        "--details-dir",
        type=Path,
        default=None,
        help="Private details root. Default: <gold-dir>/../scoring-details/.",
    )
    return parser


def _value_marker(text: str) -> str:
    """Gold value/note strings count as leak markers only when they carry
    letters (units, qualifiers, names). Bare numbers would false-positive
    against the scorecard's own aggregate rates."""

    text = text.strip()
    return text if any(ch.isalpha() for ch in text) else ""


def gold_marker_strings(private_details: dict) -> set[str]:
    """Identity and value strings that must never leak into the public
    scorecard."""

    markers: set[str] = set()
    for paper in private_details.get("papers", []):
        for pair in paper.get("pairs", []):
            markers.add(str(pair.get("gold_id") or ""))
            for row in pair.get("l2", []):
                markers.add(_value_marker(str(row.get("gold") or "")))
                markers.add(_value_marker(str(row.get("gold_note") or "")))
        for missed in paper.get("unmatched_gold", []):
            if isinstance(missed, dict):
                markers.add(str(missed.get("gold_id") or ""))
                for row in missed.get("l2", []):
                    markers.add(_value_marker(str(row.get("gold") or "")))
            else:
                markers.add(str(missed))
    return {marker for marker in markers if len(marker) >= 4}


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    gold_dir = args.gold_dir if args.gold_dir is not None else default_gold_dir()
    if gold_dir is None:
        raise SystemExit(
            f"Set {GOLD_DIR_ENV} or pass --gold-dir to the external private "
            "gold annotation root."
        )
    gold_dir = gold_dir.expanduser().resolve()
    if not gold_dir.is_dir():
        raise SystemExit(f"gold directory not found: {gold_dir}")

    gold_annotations = load_gold_annotations(gold_dir)
    if not gold_annotations:
        raise SystemExit(f"no gold annotations found under {gold_dir}")

    if args.legacy_literature:
        run_label = args.run_label or "legacy-literature"
        run_source: dict = {"mode": "legacy_literature"}
        ai_documents = {
            arxiv_id: load_ai_document(
                WORKSPACE / "literature" / arxiv_id / "literature_hvs_candidates.json"
            )
            for arxiv_id in gold_annotations
        }
    else:
        run_dir = args.run_dir.expanduser().resolve()
        if not run_dir.is_dir():
            raise SystemExit(f"run directory not found: {run_dir}")
        run_label = args.run_label or run_dir.name
        config_path = run_dir / "run_config.json"
        config = (
            json.loads(config_path.read_text(encoding="utf-8"))
            if config_path.is_file()
            else {}
        )
        run_source = {
            "mode": "benchmark_run",
            "run_id": config.get("run_id", run_dir.name),
            "pipeline": config.get("pipeline"),
            "model": config.get("model"),
            "prompt_version": config.get("prompt_version"),
            "created_at": config.get("created_at"),
        }
        ai_documents = {
            arxiv_id: load_ai_document(
                run_dir / arxiv_id / "literature_hvs_candidates.json"
            )
            for arxiv_id in gold_annotations
        }

    weights = load_sampling_weights(args.manifest.expanduser())
    scorecard, private_details = score_run(
        gold_annotations=gold_annotations,
        ai_documents=ai_documents,
        weights=weights,
        run_label=run_label,
        run_source=run_source,
    )

    scorecard_text = json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n"
    leaked = [
        marker
        for marker in sorted(gold_marker_strings(private_details))
        if marker in scorecard_text
    ]
    if leaked:
        raise SystemExit(
            "leak guard: public scorecard contains gold identity strings: "
            + ", ".join(leaked)
        )

    scoring_dir = args.scoring_dir.expanduser() / run_label
    scoring_dir.mkdir(parents=True, exist_ok=True)
    scorecard_path = scoring_dir / "scorecard.json"
    scorecard_path.write_text(scorecard_text, encoding="utf-8")

    details_root = (
        args.details_dir.expanduser()
        if args.details_dir is not None
        else gold_dir.parent / "scoring-details"
    )
    details_dir = details_root / run_label
    details_dir.mkdir(parents=True, exist_ok=True)
    details_path = details_dir / "details.json"
    details_path.write_text(
        json.dumps(private_details, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    micro = scorecard["l1"]["micro"]
    negative = scorecard["l1"]["negative_papers"]
    l2 = scorecard["l2"]["micro"]
    print(f"Wrote {scorecard_path}")
    print(f"Wrote {details_path} (private)")
    print(
        f"L1 micro: P={micro['precision']} R={micro['recall']} F1={micro['f1']} "
        f"(tp={micro['tp']} fp={micro['fp']} fn={micro['fn']})"
    )
    print(
        f"negative papers: {negative['count']}, with FP: "
        f"{negative['papers_with_false_positives']}"
    )
    # The three layered headline numbers (never combined into one score).
    print(
        "L2 agreement over compared (strict): "
        f"{l2['agreement_over_compared_strict']} "
        f"(lenient {l2['agreement_over_compared_lenient']})"
    )
    print(
        "L2 delivery end-to-end (strict): "
        f"{l2['delivery_end_to_end_strict']} "
        f"(coverage {l2['coverage']})"
    )
    print(
        "L2 fill precision (strict): "
        f"{l2['fill_precision_strict']} (ai_only {l2['ai_only']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
