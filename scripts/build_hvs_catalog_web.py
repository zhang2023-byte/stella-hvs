#!/usr/bin/env python3
"""Build the Stella HVS catalog HTML demo outputs."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import stella.web


WORKSPACE = Path(__file__).resolve().parents[1]

from stella.web.catalog_site import (  # noqa: E402
    build_static_site,
    load_catalog_snapshot,
    render_live_index_html,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build catalog/web/live and catalog/web/static for the object-level HVS catalog.")
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=WORKSPACE / "catalog",
        help="Object catalog directory. Default: catalog/",
    )
    parser.add_argument(
        "--web-dir",
        type=Path,
        default=None,
        help="HTML output root. Default: <catalog-dir>/html.",
    )
    return parser


def ensure_live_assets(assets_dir: Path) -> None:
    """Populate target live assets from bundled source assets."""
    required = ("stella.css", "catalog-viewer.js", "stella-hero.svg", "stella-hvs-hero.png")
    source_assets_dir = Path(stella.web.__file__).resolve().parent / "assets"
    missing_source = [name for name in required if not (source_assets_dir / name).exists()]
    if missing_source:
        missing = ", ".join(str(source_assets_dir / name) for name in missing_source)
        raise FileNotFoundError(f"missing source live assets: {missing}")
    assets_dir.mkdir(parents=True, exist_ok=True)
    for name in required:
        shutil.copy2(source_assets_dir / name, assets_dir / name)


def main() -> int:
    args = build_parser().parse_args()
    catalog_dir = args.catalog_dir.expanduser()
    web_dir = args.web_dir.expanduser() if args.web_dir is not None else catalog_dir / "html"
    live_dir = web_dir / "live"
    assets_dir = live_dir / "assets"
    static_dir = web_dir / "static"

    ensure_live_assets(assets_dir)

    css_path = assets_dir / "stella.css"
    js_path = assets_dir / "catalog-viewer.js"
    hero_path = assets_dir / "stella-hvs-hero.png"
    missing_assets = [path for path in (css_path, js_path, hero_path) if not path.exists()]
    if missing_assets:
        missing = ", ".join(str(path) for path in missing_assets)
        raise FileNotFoundError(f"missing live assets: {missing}")

    live_dir.mkdir(parents=True, exist_ok=True)
    static_dir.mkdir(parents=True, exist_ok=True)
    snapshot = load_catalog_snapshot(catalog_dir, literature_dir=WORKSPACE / "literature")
    (assets_dir / "paper-metadata.json").write_text(
        json.dumps(snapshot.get("paper_metadata") or {}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (live_dir / "index.html").write_text(render_live_index_html(catalog_root="../.."), encoding="utf-8")

    build_static_site(
        static_dir,
        catalog_dir,
        css_path,
        js_path,
        hero_path,
        literature_dir=WORKSPACE / "literature",
    )

    print("Built Stella HVS catalog HTML outputs:")
    print(live_dir / "index.html")
    print(static_dir / "index.html")
    print("Live preview: conda run -n stella-env python scripts/serve_catalog_web.py --mode live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
