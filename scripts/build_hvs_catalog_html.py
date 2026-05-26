#!/usr/bin/env python3
"""Build the Stella HVS catalog HTML demo outputs."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stella_html.catalog_site import (  # noqa: E402
    build_static_html,
    has_external_html_dependencies,
    render_live_index_html,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build catalog/html/live and catalog/html/static for the object-level HVS catalog.")
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=WORKSPACE / "catalog",
        help="Object catalog directory. Default: catalog/",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=None,
        help="HTML output root. Default: <catalog-dir>/html.",
    )
    return parser


def ensure_live_assets(assets_dir: Path) -> None:
    """Populate target live assets from bundled source assets."""
    required = ("stella.css", "catalog-viewer.js", "stella-hero.svg")
    source_assets_dir = SRC / "stella_html" / "assets"
    missing_source = [name for name in required if not (source_assets_dir / name).exists()]
    if missing_source:
        missing = ", ".join(str(assets_dir / name) for name in required if not (assets_dir / name).exists())
        raise FileNotFoundError(f"missing live assets: {missing}")
    assets_dir.mkdir(parents=True, exist_ok=True)
    for name in required:
        shutil.copy2(source_assets_dir / name, assets_dir / name)


def patch_catalog_viewer_asset(js_path: Path) -> None:
    """Keep generated live assets aligned with the current catalog layout."""
    text = js_path.read_text(encoding="utf-8")
    text = text.replace(
        'root + "/" + encodeURIComponent(item.object_id) + ".json"',
        'root + "/candidates/" + encodeURIComponent(item.object_id) + ".json"',
    )
    text = text.replace("catalog/*.json", "catalog/candidates/*.json")
    js_path.write_text(text, encoding="utf-8")


def main() -> int:
    args = build_parser().parse_args()
    catalog_dir = args.catalog_dir.expanduser()
    html_dir = args.html_dir.expanduser() if args.html_dir is not None else catalog_dir / "html"
    live_dir = html_dir / "live"
    assets_dir = live_dir / "assets"
    static_dir = html_dir / "static"

    ensure_live_assets(assets_dir)

    css_path = assets_dir / "stella.css"
    js_path = assets_dir / "catalog-viewer.js"
    hero_path = assets_dir / "stella-hero.svg"
    patch_catalog_viewer_asset(js_path)
    missing_assets = [path for path in (css_path, js_path, hero_path) if not path.exists()]
    if missing_assets:
        missing = ", ".join(str(path) for path in missing_assets)
        raise FileNotFoundError(f"missing live assets: {missing}")

    live_dir.mkdir(parents=True, exist_ok=True)
    static_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "index.html").write_text(render_live_index_html(catalog_root="../.."), encoding="utf-8")

    static_html = build_static_html(catalog_dir, css_path, js_path, hero_path)
    if has_external_html_dependencies(static_html):
        raise RuntimeError("static HTML contains an external script, stylesheet, or remote image dependency")
    static_path = static_dir / "index.html"
    static_path.write_text(static_html, encoding="utf-8")

    print("Built Stella HVS catalog HTML outputs:")
    print(live_dir / "index.html")
    print(static_path)
    print("Live preview: start an HTTP server at the repository root and open /catalog/html/live/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
