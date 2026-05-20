#!/usr/bin/env python3
"""Build the Stella HVS catalog HTML demo outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.hvs_catalog_site import (  # noqa: E402
    build_static_html,
    has_external_html_dependencies,
    render_live_index_html,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build html/live and html/static for the object-level HVS catalog.")
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=WORKSPACE / "catalog",
        help="Object catalog directory. Default: catalog/",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=WORKSPACE / "html",
        help="HTML output root. Default: html/",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    catalog_dir = args.catalog_dir.expanduser()
    html_dir = args.html_dir.expanduser()
    live_dir = html_dir / "live"
    assets_dir = live_dir / "assets"
    static_dir = html_dir / "static"

    css_path = assets_dir / "stella.css"
    js_path = assets_dir / "catalog-viewer.js"
    hero_path = assets_dir / "stella-hero.svg"
    missing_assets = [path for path in (css_path, js_path, hero_path) if not path.exists()]
    if missing_assets:
        missing = ", ".join(str(path) for path in missing_assets)
        raise FileNotFoundError(f"missing live assets: {missing}")

    live_dir.mkdir(parents=True, exist_ok=True)
    static_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "index.html").write_text(render_live_index_html(), encoding="utf-8")

    static_html = build_static_html(catalog_dir, css_path, js_path, hero_path)
    if has_external_html_dependencies(static_html):
        raise RuntimeError("static HTML contains an external script, stylesheet, or remote image dependency")
    static_path = static_dir / "index.html"
    static_path.write_text(static_html, encoding="utf-8")

    print("Built Stella HVS catalog HTML outputs:")
    print(live_dir / "index.html")
    print(static_path)
    print("Live preview: start an HTTP server at the repository root and open /html/live/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
