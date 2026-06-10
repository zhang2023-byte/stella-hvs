"""Build the static expert review site under benchmark/review/."""

from __future__ import annotations

import shutil
from pathlib import Path

from .paths import review_dir

_SRC_ASSETS = Path(__file__).resolve().parent / "assets"
_STELLA_CSS = Path(__file__).resolve().parents[1] / "stella_html" / "assets" / "stella.css"

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stella HVS Benchmark Review</title>
<link rel="stylesheet" href="assets/stella.css">
<link rel="stylesheet" href="assets/benchmark-review.css">
</head>
<body data-alignment-index="/alignment/alignment_index.json"
      data-alignment-base="/alignment/"
      data-adjudication-base="/adjudication/"
      data-verdict-api="/api/verdicts/">
<main class="review-shell">
  <header class="review-masthead">
    <span class="eyebrow">Stella HVS Benchmark</span>
    <h1>Expert Review</h1>
    <p id="session-line">Loading…</p>
  </header>
  <div class="review-columns">
    <nav id="paper-list" class="paper-list" aria-label="Benchmark papers"></nav>
    <section id="paper-view" class="paper-view">
      <p class="hint">Select a paper to begin adjudication.</p>
    </section>
  </div>
</main>
<script src="assets/benchmark-review.js"></script>
</body>
</html>
"""


def build_review_site(benchmark_root_dir: Path) -> Path:
    target = review_dir(benchmark_root_dir)
    assets = target / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (target / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    if _STELLA_CSS.exists():
        shutil.copyfile(_STELLA_CSS, assets / "stella.css")
    for name in ("benchmark-review.js", "benchmark-review.css"):
        source = _SRC_ASSETS / name
        if source.exists():
            shutil.copyfile(source, assets / name)
    return target / "index.html"
