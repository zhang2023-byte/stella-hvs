#!/usr/bin/env python3
"""Regenerate the public V4 comparison block in benchmark/README.md."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "benchmark" / "README.md"
PRE_RELATIVE = Path(
    "benchmark/campaigns/hvs-extraction-v4/scoring/"
    "v4-dev-pre-engineering-b-core-r1-score-v1/scorecard.json"
)
POST_RELATIVE = Path(
    "benchmark/campaigns/hvs-extraction-v4/scoring/"
    "v4-dev-post-engineering-b-core-r1-score-v1/scorecard.json"
)
BEGIN = "<!-- BEGIN GENERATED: benchmark-v4-comparison -->"
END = "<!-- END GENERATED: benchmark-v4-comparison -->"


def _load(relative: Path) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _signed(delta: float) -> str:
    return f"{delta:+.3f}"


def _metrics(card: dict) -> dict[str, float]:
    return {
        "precision": card["l1"]["micro"]["precision"],
        "recall": card["l1"]["micro"]["recall"],
        "f1": card["l1"]["micro"]["f1"],
        "coverage": card["l2"]["micro"]["coverage"],
        "agreement": card["l2"]["micro"]["agreement_over_compared_strict"],
        "delivery": card["l2"]["micro"]["delivery_end_to_end_strict"],
        "fill_precision": card["l2"]["micro"]["fill_precision_strict"],
    }


def render_block() -> str:
    pre = _load(PRE_RELATIVE)
    post = _load(POST_RELATIVE)
    pre_metrics = _metrics(pre)
    post_metrics = _metrics(post)
    pre_delivery = pre["delivery_counts"]
    post_delivery = post["delivery_counts"]
    rows = [
        (
            "Valid / invalid / missing",
            f"{pre_delivery['valid']} / {pre_delivery['invalid']} / {pre_delivery['missing']}",
            f"{post_delivery['valid']} / {post_delivery['invalid']} / {post_delivery['missing']}",
            f"valid {post_delivery['valid'] - pre_delivery['valid']:+d}",
        ),
        *[
            (
                label,
                f"{pre_metrics[key]:.3f}",
                f"{post_metrics[key]:.3f}",
                _signed(post_metrics[key] - pre_metrics[key]),
            )
            for label, key in (
                ("L1 micro precision", "precision"),
                ("L1 micro recall", "recall"),
                ("L1 micro F1", "f1"),
                ("L2 coverage", "coverage"),
                ("L2 agreement over compared, strict", "agreement"),
                ("L2 delivery end-to-end, strict", "delivery"),
                ("L2 fill precision, strict", "fill_precision"),
            )
        ],
    ]
    table = [
        BEGIN,
        "| Metric | Pre-engineering | Post-engineering | Change |",
        "|---|---:|---:|---:|",
        *[f"| {label} | {pre_value} | {post_value} | {delta} |" for label, pre_value, post_value, delta in rows],
        "",
        "Sources:",
        "",
        f"- [Pre-engineering scorecard]({PRE_RELATIVE.relative_to('benchmark')})",
        f"- [Post-engineering scorecard]({POST_RELATIVE.relative_to('benchmark')})",
        END,
    ]
    return "\n".join(table)


def updated_readme() -> str:
    text = README.read_text(encoding="utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise RuntimeError("benchmark README must contain exactly one generated comparison block")
    prefix, remainder = text.split(BEGIN, 1)
    _, suffix = remainder.split(END, 1)
    return prefix + render_block() + suffix


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when the committed block is stale")
    args = parser.parse_args()
    expected = updated_readme()
    current = README.read_text(encoding="utf-8")
    if args.check:
        if current != expected:
            raise SystemExit("benchmark/README.md comparison block is stale")
        return 0
    README.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
