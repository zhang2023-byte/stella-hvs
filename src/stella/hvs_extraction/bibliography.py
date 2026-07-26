"""Discover bibliography sources associated with the resolved root manuscript.

Discovery only records where citation-key resolution must look in the later
field stage; it exposes nothing to the model. Embedded ``thebibliography``
content inside an included TeX file stays visible as manuscript text, while
standalone ``.bbl``/``.bib`` files are hidden from the model and used only for
program-owned key resolution.

Association rules (delegated engineering, recorded in the implementation log):
an embedded ``thebibliography`` environment in any included TeX file; a
standalone ``.bbl`` that is ``\\input``/``\\include``-targeted by an included
file or that shares the root file's basename; a standalone ``.bib`` named by
``\\bibliography`` or ``\\addbibresource`` in an included file, resolved
relative to the referring file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from stella.hvs_extraction.cleaning import strip_tex_comments
from stella.hvs_extraction.tex_graph import TexManuscriptGraph

THEBIBLIOGRAPHY_BEGIN_RE = re.compile(r"\\begin\{thebibliography\}")
THEBIBLIOGRAPHY_END_RE = re.compile(r"\\end\{thebibliography\}")
BIBLIOGRAPHY_RE = re.compile(r"\\(?:bibliography|addbibresource)\s*\{([^}]+)\}")

KIND_EMBEDDED = "embedded_thebibliography"
KIND_BBL = "bbl"
KIND_BIB = "bib"


@dataclass(frozen=True)
class BibliographySource:
    kind: str
    path: str  # source-dir-relative path; TeX block name for embedded entries
    start_line: int | None = None
    end_line: int | None = None


def discover_bibliography(
    graph: TexManuscriptGraph,
    source_dir: Path,
) -> list[BibliographySource]:
    """Locate embedded, .bbl, and .bib sources tied to the resolved root."""

    source_dir = source_dir.resolve()
    sources: list[BibliographySource] = []

    for name in graph.included:
        stripped = strip_tex_comments(graph.texts[name])
        lines = stripped.split("\n")
        begin_line: int | None = None
        for number, line in enumerate(lines, 1):
            if begin_line is None and THEBIBLIOGRAPHY_BEGIN_RE.search(line):
                begin_line = number
            elif begin_line is not None and THEBIBLIOGRAPHY_END_RE.search(line):
                sources.append(
                    BibliographySource(
                        kind=KIND_EMBEDDED,
                        path=name,
                        start_line=begin_line,
                        end_line=number,
                    )
                )
                begin_line = None

    seen_bbl: set[str] = set()
    for _referring, target in graph.non_tex_includes:
        if target.lower().endswith(".bbl") and target not in seen_bbl:
            seen_bbl.add(target)
            sources.append(BibliographySource(kind=KIND_BBL, path=target))
    root_bbl = Path(graph.root).with_suffix(".bbl").as_posix()
    if root_bbl not in seen_bbl and (source_dir / root_bbl).is_file():
        seen_bbl.add(root_bbl)
        sources.append(BibliographySource(kind=KIND_BBL, path=root_bbl))

    seen_bib: set[str] = set()
    for name in graph.included:
        stripped = strip_tex_comments(graph.texts[name])
        referring_dir = Path(source_dir / name).parent
        for match in BIBLIOGRAPHY_RE.finditer(stripped):
            for raw in match.group(1).split(","):
                bib_name = raw.strip()
                if not bib_name:
                    continue
                candidate = (referring_dir / bib_name).resolve()
                if candidate.suffix == "":
                    candidate = candidate.with_suffix(".bib")
                if not candidate.is_file():
                    continue
                try:
                    display = candidate.relative_to(source_dir).as_posix()
                except ValueError:
                    continue
                if display not in seen_bib:
                    seen_bib.add(display)
                    sources.append(BibliographySource(kind=KIND_BIB, path=display))

    order = {KIND_EMBEDDED: 0, KIND_BBL: 1, KIND_BIB: 2}
    return sorted(sources, key=lambda item: (order[item.kind], item.path, item.start_line or 0))
