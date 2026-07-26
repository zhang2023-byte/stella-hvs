#!/usr/bin/env python3
"""Regenerate the historical comparison in benchmark_implementation.md."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "benchmark" / "benchmark_implementation.md"
SCORING_ROOT = ROOT / "benchmark" / "campaigns" / "hvs-extraction-v4" / "scoring"
BEGIN = "<!-- BEGIN GENERATED: benchmark-history-comparison -->"
END = "<!-- END GENERATED: benchmark-history-comparison -->"


def _cards() -> list[dict]:
    paths = sorted(SCORING_ROOT.glob("*/scorecard.json"))
    if len(paths) != 2:
        raise RuntimeError("expected exactly two frozen V4 scorecards")
    cards = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    return sorted(
        cards,
        key=lambda card: card["delivery_counts"]["valid"],
        reverse=True,
    )


def _metrics(card: dict) -> dict[str, float]:
    return {
        "delivery": card["delivery_counts"]["valid"],
        "precision": card["l1"]["micro"]["precision"],
        "recall": card["l1"]["micro"]["recall"],
        "f1": card["l1"]["micro"]["f1"],
        "coverage": card["l2"]["micro"]["coverage"],
        "agreement": card["l2"]["micro"]["agreement_over_compared_strict"],
        "end_to_end": card["l2"]["micro"]["delivery_end_to_end_strict"],
    }


def render_block() -> str:
    higher_delivery, lower_delivery = map(_metrics, _cards())
    rows = [
        ("Valid paper delivery", str(higher_delivery["delivery"]), str(lower_delivery["delivery"])),
        ("L1 precision", f"{higher_delivery['precision']:.3f}", f"{lower_delivery['precision']:.3f}"),
        ("L1 recall", f"{higher_delivery['recall']:.3f}", f"{lower_delivery['recall']:.3f}"),
        ("L1 F1", f"{higher_delivery['f1']:.3f}", f"{lower_delivery['f1']:.3f}"),
        ("L2 coverage", f"{higher_delivery['coverage']:.3f}", f"{lower_delivery['coverage']:.3f}"),
        ("L2 strict agreement", f"{higher_delivery['agreement']:.3f}", f"{lower_delivery['agreement']:.3f}"),
        (
            "L2 strict end-to-end delivery",
            f"{higher_delivery['end_to_end']:.3f}",
            f"{lower_delivery['end_to_end']:.3f}",
        ),
    ]
    return "\n".join(
        [
            BEGIN,
            "Historical V4 scorecards remain useful context but are not V5 runs:",
            "",
            "| Metric | Higher-delivery V4 run | Lower-delivery V4 run |",
            "|---|---:|---:|",
            *[f"| {label} | {first} | {second} |" for label, first, second in rows],
            END,
        ]
    )


def updated_document() -> str:
    text = TARGET.read_text(encoding="utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise RuntimeError("implementation document must contain one generated block")
    prefix, remainder = text.split(BEGIN, 1)
    _, suffix = remainder.split(END, 1)
    return prefix + render_block() + suffix


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = updated_document()
    if args.check:
        if TARGET.read_text(encoding="utf-8") != expected:
            raise SystemExit("benchmark implementation comparison block is stale")
        return 0
    TARGET.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
