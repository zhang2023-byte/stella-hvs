"""Optional ECSV selection with the minimal TeX mapping.

Converted ECSV tables improve exact cell addressing but are never a
prerequisite: missing, incomplete, failed, or mechanically invalid ECSV assets
never block extraction from a valid TeX manuscript. ``catalog_extraction.json``
is read only to resolve and verify the deterministic provenance mapping; it is
program-private and never enters model-visible context. The model-visible
mapping carries only ``ecsv_path``, ``source_tex_path``, the inclusive source
TeX line range, and the table label or id when present.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from stella.lit.extraction.tex_graph import TexManuscriptGraph

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_UNAVAILABLE = "unavailable"

REASON_CATALOG_MISSING = "catalog_extraction_missing"
REASON_CATALOG_UNREADABLE = "catalog_extraction_unreadable"
REASON_TABLE_NOT_SUCCESS = "table_not_success"
REASON_MAPPING_MISSING = "mapping_missing"
REASON_ECSV_MISSING = "ecsv_missing"
REASON_ECSV_INVALID = "ecsv_invalid_structure"
REASON_TEX_OUTSIDE_GRAPH = "mapped_tex_outside_manuscript_graph"
REASON_RANGE_INVALID = "mapped_range_invalid"


class EcsvStructureError(ValueError):
    pass


@dataclass(frozen=True)
class EcsvStructure:
    columns: tuple[str, ...]
    column_row_line: int
    data_row_lines: tuple[int, ...]
    line_count: int
    sha256: str
    column_headers: dict[str, str] = field(default_factory=dict)


def _parse_column_headers_lenient(header_comment_lines: list[str]) -> dict[str, str]:
    """Tolerant fallback for non-YAML-safe header lines.

    Our converter writes some descriptions unquoted inside flow mappings
    (commas and brackets break ``yaml.safe_load``), so this parser reads
    ``- name:`` / ``description:`` lines directly and treats a flow-style
    ``{... description: X}`` as ending at the closing brace.
    """

    headers: dict[str, str] = {}
    current: str | None = None

    def unquote(value: str) -> str:
        value = value.strip().rstrip("}").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            return value[1:-1]
        return value

    for raw in header_comment_lines:
        line = raw.lstrip("#").strip()
        if line.startswith("- name:"):
            current = line.split(":", 1)[1].strip()
            headers.setdefault(current, current)
        elif line.startswith("- {"):
            name_match = re.search(r"name:\s*([^,}\s]+)", line)
            if not name_match:
                continue
            current = name_match.group(1).strip().strip("'\"")
            description_match = re.search(r"description:\s*(.+)$", line)
            if description_match:
                headers[current] = unquote(description_match.group(1))
            else:
                headers.setdefault(current, current)
        elif line.startswith("description:") and current is not None:
            headers[current] = unquote(line.split(":", 1)[1])
    return headers


def _parse_column_headers(header_comment_lines: list[str]) -> dict[str, str]:
    """Best-effort column metadata from the ECSV YAML header block.

    The header between the ``# %ECSV`` marker and the column-name row is YAML
    with a ``datatype`` list. Column descriptions carry the original author
    header text used for program-owned hydration. A malformed header
    degrades to the lenient line parser rather than failing table selection.
    """

    body = "\n".join(
        line[1:].lstrip() if line.startswith("#") else line
        for line in header_comment_lines
    )
    try:
        payload = yaml.safe_load(body)
    except yaml.YAMLError:
        return _parse_column_headers_lenient(header_comment_lines)
    if not isinstance(payload, dict):
        return _parse_column_headers_lenient(header_comment_lines)
    headers: dict[str, str] = {}
    for column in payload.get("datatype") or []:
        if not isinstance(column, dict):
            continue
        name = column.get("name")
        if not name:
            continue
        description = column.get("description")
        headers[str(name)] = str(description) if description else str(name)
    return headers


@dataclass(frozen=True)
class SelectedEcsv:
    """One usable ECSV with its minimal model-visible mapping."""

    ecsv_path: str  # model-visible block name, relative to the paper directory
    source_tex_path: str  # model-visible TeX block name
    source_tex_start_line: int
    source_tex_end_line: int
    label: str  # empty when the source table has no label/id
    structure: EcsvStructure


@dataclass
class EcsvSelection:
    status: str
    selected: list[SelectedEcsv] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def resolve_paper_ecsv_path(paper_dir: Path, relative_path: str) -> Path:
    """Resolve an ECSV path strictly inside one paper directory."""

    logical = PurePosixPath(relative_path)
    if logical.is_absolute() or ".." in logical.parts or not logical.parts:
        raise EcsvStructureError("ECSV path is not a safe paper-relative path")
    try:
        paper_root = paper_dir.resolve(strict=True)
        target = (paper_root / Path(*logical.parts)).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise EcsvStructureError(f"ECSV path cannot be resolved strictly: {exc}") from exc
    if not target.is_relative_to(paper_root) or not target.is_file():
        raise EcsvStructureError("ECSV target is outside the paper directory")
    return target


def parse_ecsv_structure(path: Path) -> EcsvStructure:
    """Validate ECSV mechanically: decodable, machine columns, data rows."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EcsvStructureError(f"unreadable: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EcsvStructureError(f"undecodable: {exc}") from exc
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or not lines[0].startswith("# %ECSV"):
        raise EcsvStructureError("missing '# %ECSV' header marker")
    column_row_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip() and not line.startswith("#"):
            column_row_index = index
            break
    if column_row_index is None:
        raise EcsvStructureError("no column-name row")
    columns = tuple(lines[column_row_index].split())
    if not columns:
        raise EcsvStructureError("empty column-name row")
    data_row_lines = tuple(
        index + 1
        for index, line in enumerate(lines[column_row_index + 1 :], column_row_index + 1)
        if line.strip() and not line.startswith("#")
    )
    if not data_row_lines:
        raise EcsvStructureError("no data rows")
    return EcsvStructure(
        columns=columns,
        column_row_line=column_row_index + 1,
        data_row_lines=data_row_lines,
        line_count=len(lines),
        sha256=hashlib.sha256(raw).hexdigest(),
        column_headers=_parse_column_headers(lines[1:column_row_index]),
    )


def select_ecsv_tables(
    workspace: Path,
    paper_dir: Path,
    graph: TexManuscriptGraph,
) -> EcsvSelection:
    """Select mechanically usable ECSV tables under the frozen include/exclude rules."""

    paper_rel = paper_dir.relative_to(workspace).as_posix()
    source_prefix = f"{paper_rel}/arxiv_source/"
    catalog_path = paper_dir / "catalog_extraction.json"
    if not catalog_path.is_file():
        return EcsvSelection(
            status=STATUS_UNAVAILABLE,
            diagnostics=[f"no catalog_extraction.json for {paper_rel}"],
        )
    try:
        catalog: dict[str, Any] = json.loads(catalog_path.read_text(encoding="utf-8"))
        tables = catalog["tables"]
        files = catalog["files"]
        if not isinstance(tables, list) or not isinstance(files, list):
            raise ValueError("tables/files must be lists")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return EcsvSelection(
            status=STATUS_UNAVAILABLE,
            diagnostics=[f"catalog_extraction.json unreadable: {exc}"],
        )

    file_refs = {
        item.get("id"): item.get("source_ref") or {}
        for item in files
        if isinstance(item, dict) and item.get("status") == "written"
    }
    selection = EcsvSelection(status=STATUS_UNAVAILABLE)
    for table in tables:
        if not isinstance(table, dict):
            continue
        target = str(table.get("id") or table.get("ecsv_path") or "<unknown>")
        if table.get("status") != "success":
            selection.excluded.append(
                {"target": target, "reason": REASON_TABLE_NOT_SUCCESS}
            )
            continue
        source_ref = file_refs.get(table.get("id")) or {}
        tex_path_full = source_ref.get("path")
        start_line = source_ref.get("start_line")
        end_line = source_ref.get("end_line")
        if not tex_path_full or not isinstance(start_line, int) or not isinstance(end_line, int):
            selection.excluded.append({"target": target, "reason": REASON_MAPPING_MISSING})
            continue
        if not str(tex_path_full).startswith(source_prefix):
            selection.excluded.append(
                {"target": target, "reason": REASON_TEX_OUTSIDE_GRAPH}
            )
            continue
        tex_block = str(tex_path_full)[len(source_prefix):]
        graph_file = graph.files.get(tex_block)
        if graph_file is None:
            selection.excluded.append(
                {"target": target, "reason": REASON_TEX_OUTSIDE_GRAPH}
            )
            continue
        if not (1 <= start_line <= end_line <= graph_file.line_count):
            selection.excluded.append(
                {"target": target, "reason": REASON_RANGE_INVALID}
            )
            continue
        ecsv_full = str(table.get("ecsv_path") or "")
        logical = PurePosixPath(ecsv_full)
        paper_parts = PurePosixPath(paper_rel).parts
        if (
            logical.is_absolute()
            or ".." in logical.parts
            or logical.parts[: len(paper_parts)] != paper_parts
            or len(logical.parts) <= len(paper_parts)
        ):
            selection.excluded.append({"target": target, "reason": REASON_ECSV_MISSING})
            continue
        relative_ecsv = PurePosixPath(*logical.parts[len(paper_parts) :]).as_posix()
        try:
            ecsv_path = resolve_paper_ecsv_path(paper_dir, relative_ecsv)
        except EcsvStructureError:
            selection.excluded.append({"target": target, "reason": REASON_ECSV_MISSING})
            continue
        try:
            structure = parse_ecsv_structure(ecsv_path)
        except EcsvStructureError as exc:
            selection.excluded.append(
                {"target": target, "reason": f"{REASON_ECSV_INVALID}: {exc}"}
            )
            continue
        selection.selected.append(
            SelectedEcsv(
                ecsv_path=relative_ecsv,
                source_tex_path=tex_block,
                source_tex_start_line=start_line,
                source_tex_end_line=end_line,
                label=str(source_ref.get("label") or table.get("label") or ""),
                structure=structure,
            )
        )

    if selection.selected:
        selection.status = STATUS_PARTIAL if selection.excluded else STATUS_COMPLETE
    return selection
