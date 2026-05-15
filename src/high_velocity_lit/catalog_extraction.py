"""Extraction of reviewed internal LaTeX catalog tables."""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .catalog_review import (
    REVIEW_FILENAME,
    internal_tables_from_review,
    iter_catalog_review_paths,
    relative_path,
)
from .schema_specs import CATALOG_EXTRACTION_SCHEMA_VERSION
from .schema_models import CatalogExtractionRecord

EXTRACTION_FILENAME = "catalog_extraction.json"
CATALOG_SOURCES_DIR = "catalog_sources"
CATALOG_TABLES_DIR = "catalog_tables"

CONVERTER_TIMEOUT_SECONDS = 120
DEFAULT_AUTO_MAX_JOBS = 12
LATEX_TABLE_ENVIRONMENTS = ("tabular", "tabular*", "longtable", "deluxetable", "deluxetable*")
RULE_COMMAND_RE = re.compile(r"\\(?:hline|toprule|midrule|bottomrule|botrule|tableline)\b")
SPACING_COMMAND_RE = re.compile(r"\\(?:[,;:! ]|quad\b|qquad\b|smallskip\b|medskip\b|bigskip\b)")
UNRESOLVED_MACRO_RE = re.compile(r"\\[A-Za-z]+")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return cleaned or "catalog-table"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def strip_latex_comment(line: str) -> str:
    index = 0
    while index < len(line):
        if line[index] == "%":
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                return line[:index]
        index += 1
    return line


def remove_latex_comments(text: str) -> str:
    return "\n".join(strip_latex_comment(line) for line in text.splitlines())


def find_matching_delimiter(text: str, open_index: int, close_char: str) -> int:
    open_char = text[open_index]
    depth = 0
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
    return -1


def skip_latex_arguments(text: str, index: int) -> int:
    cursor = index
    while cursor < len(text):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or text[cursor] not in "{[":
            return cursor
        close_char = "}" if text[cursor] == "{" else "]"
        close_index = find_matching_delimiter(text, cursor, close_char)
        if close_index == -1:
            return cursor
        cursor = close_index + 1
    return cursor


def latex_command_argument_preserve(text: str, command: str) -> str:
    match = re.search(rf"\\{re.escape(command)}\s*(?:\[[^\]]*\])?\s*\{{", text, flags=re.DOTALL)
    if match is None:
        return ""
    open_index = match.end() - 1
    close_index = find_matching_delimiter(text, open_index, "}")
    if close_index == -1:
        return ""
    return text[open_index + 1 : close_index]


def find_latex_environment_content(text: str, environment: str) -> str:
    begin_re = re.compile(rf"\\begin\{{{re.escape(environment)}\}}")
    begin = begin_re.search(text)
    if begin is None:
        return ""
    end_re = re.compile(rf"\\end\{{{re.escape(environment)}\}}")
    end = end_re.search(text, begin.end())
    if end is None:
        return ""
    content_start = skip_latex_arguments(text, begin.end())
    if content_start > end.start():
        content_start = begin.end()
    return text[content_start : end.start()]


def find_table_content(excerpt: str) -> tuple[str, str]:
    for environment in LATEX_TABLE_ENVIRONMENTS:
        content = find_latex_environment_content(excerpt, environment)
        if content:
            return environment, content
    return "", ""


def split_latex_rows(text: str) -> list[str]:
    rows: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith("\\\\", index):
            rows.append("".join(current))
            current = []
            index += 2
            if index < len(text) and text[index] == "[":
                close_index = text.find("]", index + 1)
                if close_index != -1:
                    index = close_index + 1
            continue
        current.append(text[index])
        index += 1
    tail = "".join(current)
    if tail.strip():
        rows.append(tail)
    return rows


def is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def split_latex_cells(row: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(row):
        char = row[index]
        if char == "{" and not is_escaped(row, index):
            depth += 1
        elif char == "}" and not is_escaped(row, index) and depth > 0:
            depth -= 1
        if char == "&" and depth == 0 and not is_escaped(row, index):
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current))
    return cells


def unwrap_simple_commands(text: str) -> str:
    previous = None
    value = text
    simple_commands = ("colhead", "mathrm", "textrm", "text", "textbf", "textit", "emph")
    while previous != value:
        previous = value
        for command in simple_commands:
            value = re.sub(rf"\\{command}\s*\{{([^{{}}]*)\}}", r"\1", value)
    return value


def replace_multicolumn(text: str) -> str:
    pattern = re.compile(r"\\multicolumn\s*\{[^{}]*\}\s*\{[^{}]*\}\s*\{([^{}]*)\}")
    previous = None
    value = text
    while previous != value:
        previous = value
        value = pattern.sub(r"\1", value)
    return value


def clean_latex_cell(cell: str) -> str:
    value = cell.strip()
    value = RULE_COMMAND_RE.sub(" ", value)
    value = re.sub(r"\\(?:label|caption|tablecaption)\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", " ", value)
    value = replace_multicolumn(value)
    value = unwrap_simple_commands(value)
    value = value.replace(r"\pm", "+/-")
    value = value.replace(r"\ldots", "...")
    value = value.replace(r"\dots", "...")
    value = value.replace(r"\nodata", "")
    value = value.replace(r"\_", "_")
    value = value.replace(r"\%", "%")
    value = value.replace("$", "")
    value = SPACING_COMMAND_RE.sub(" ", value)
    value = value.replace(r"\ ", " ")
    value = value.replace("{", "").replace("}", "")
    return " ".join(value.split())


def clean_html_cell_text(value: str) -> str:
    text = " ".join(value.replace("\xa0", " ").split())
    text = text.replace("±", "+/-").replace("−", "-")
    return clean_latex_cell(text)


def parse_rows_from_segment(segment: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_row in split_latex_rows(segment):
        raw = raw_row.strip()
        if not raw:
            continue
        if re.fullmatch(r"\\(?:endfirsthead|endhead|endfoot|endlastfoot)\b.*", raw, flags=re.DOTALL):
            continue
        cells = [clean_latex_cell(cell) for cell in split_latex_cells(raw)]
        if not any(cells):
            continue
        if len(cells) == 1 and re.match(r"^\\(?:caption|label|tablecaption)\b", raw):
            continue
        rows.append(cells)
    return rows


def split_header_and_data(content: str) -> tuple[list[list[str]], list[list[str]]]:
    cleaned = remove_latex_comments(content)
    normalized = RULE_COMMAND_RE.sub("\n__STELLA_TABLE_RULE__\n", cleaned)
    groups = [
        rows
        for rows in (parse_rows_from_segment(segment) for segment in normalized.split("__STELLA_TABLE_RULE__"))
        if rows
    ]
    if len(groups) >= 2:
        header_rows = groups[0]
        data_rows = [row for group in groups[1:] for row in group]
        return header_rows, data_rows
    rows = groups[0] if groups else parse_rows_from_segment(cleaned)
    if len(rows) >= 2:
        return [rows[0]], rows[1:]
    return [], rows


def deluxetable_body(content: str) -> str:
    start_match = re.search(r"\\startdata\b", content)
    end_match = re.search(r"\\enddata\b", content)
    if start_match is not None and end_match is not None and start_match.end() <= end_match.start():
        return content[start_match.end() : end_match.start()]
    return content


def pad_row(row: list[str], width: int) -> list[str]:
    if len(row) >= width:
        return row[:width]
    return row + [""] * (width - len(row))


def unit_like(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("[", "]", "km/s", "mag", "mas", "yr", "dex", "nm", "k "))


def build_column_records(header_rows: list[list[str]], column_count: int) -> list[dict[str, Any]]:
    padded_headers = [pad_row(row, column_count) for row in header_rows]
    columns: list[dict[str, Any]] = []
    for index in range(column_count):
        values = [row[index] for row in padded_headers if row[index]]
        unit_text = next((value for value in values if unit_like(value)), "")
        columns.append(
            {
                "name": f"col_{index + 1:03d}",
                "original_header": " | ".join(values),
                "unit_text": unit_text,
                "data_type": "",
                "null_values": ["", "..."],
            }
        )
    return columns


def unresolved_macro_warnings(rows: list[list[str]]) -> list[str]:
    macros = sorted({match.group(0) for row in rows for cell in row for match in UNRESOLVED_MACRO_RE.finditer(cell)})
    return [f"unresolved LaTeX macro preserved: {macro}" for macro in macros]


def parse_latex_table_excerpt(excerpt: str) -> dict[str, Any]:
    environment, content = find_table_content(excerpt)
    warnings: list[str] = []
    if not content:
        return {
            "status": "failed",
            "environment": environment,
            "error": "no supported LaTeX table environment found",
            "warnings": warnings,
            "row_count": 0,
            "column_count": 0,
            "columns": [],
            "header_rows": [],
            "data_rows": [],
        }

    if environment.startswith("deluxetable"):
        tablehead = latex_command_argument_preserve(excerpt, "tablehead")
        header_rows = parse_rows_from_segment(remove_latex_comments(tablehead)) if tablehead else []
        fallback_header, data_rows = split_header_and_data(deluxetable_body(content))
        if not header_rows:
            header_rows = fallback_header
    else:
        header_rows, data_rows = split_header_and_data(content)

    all_rows = header_rows + data_rows
    if not data_rows:
        return {
            "status": "failed",
            "environment": environment,
            "error": "no data rows parsed from LaTeX table",
            "warnings": warnings,
            "row_count": 0,
            "column_count": max((len(row) for row in all_rows), default=0),
            "columns": [],
            "header_rows": header_rows,
            "data_rows": [],
        }

    column_count = max(len(row) for row in all_rows)
    header_rows = [pad_row(row, column_count) for row in header_rows]
    data_rows = [pad_row(row, column_count) for row in data_rows]
    columns = build_column_records(header_rows, column_count)
    warnings.extend(unresolved_macro_warnings(header_rows + data_rows))
    return {
        "status": "success",
        "environment": environment,
        "error": "",
        "warnings": warnings,
        "row_count": len(data_rows),
        "column_count": column_count,
        "columns": columns,
        "header_rows": header_rows,
        "data_rows": data_rows,
    }


def infer_data_type(values: list[str]) -> str:
    nonempty = [value for value in values if value and value != "..."]
    if not nonempty:
        return ""
    numeric_count = 0
    for value in nonempty:
        normalized = re.sub(r"\+/-.*$", "", value.strip())
        normalized = normalized.replace(",", "")
        try:
            float(normalized)
            numeric_count += 1
        except ValueError:
            pass
    if numeric_count == len(nonempty):
        return "number"
    if numeric_count >= max(1, len(nonempty) // 2):
        return "mixed"
    return "string"


def enrich_column_data_types(columns: list[dict[str, Any]], data_rows: list[list[str]]) -> list[dict[str, Any]]:
    for index, column in enumerate(columns):
        column["data_type"] = infer_data_type([row[index] for row in data_rows if index < len(row)])
    return columns


def table_ecsv_text(parsed: dict[str, Any]) -> str:
    from astropy.io import ascii
    from astropy.table import Table

    columns = parsed.get("columns") or []
    names = [str(column.get("name") or f"col_{index + 1:03d}") for index, column in enumerate(columns)]
    data_rows = parsed.get("data_rows") or []
    table = Table(rows=data_rows, names=names, dtype=["str"] * len(names))
    for name, column in zip(names, columns, strict=True):
        description_parts = [
            str(column.get("original_header") or column.get("original_name") or "").strip(),
            str(column.get("description") or "").strip(),
        ]
        description = " | ".join(part for part in description_parts if part)
        if description:
            table[name].description = description
        unit_text = str(column.get("unit_text") or "").strip()
        if unit_text:
            table[name].meta["unit_text"] = unit_text
    buffer = io.StringIO()
    ascii.write(table, buffer, format="ecsv", overwrite=True)
    return buffer.getvalue()


def default_preamble(excerpt: str) -> str:
    documentclass = "aastex631" if "deluxetable" in excerpt or r"\tabletypesize" in excerpt else "article"
    return "\n".join(
        [
            rf"\documentclass{{{documentclass}}}",
            r"\usepackage{amsmath,amssymb,booktabs,array,longtable,multirow,rotating}",
        ]
    )


def latex_macro_stubs() -> str:
    return r"""
\providecommand{\tablefoot}[1]{#1}
\providecommand{\tablecomments}[1]{#1}
\providecommand{\tablenotetext}[2]{#2}
\providecommand{\tablerefs}[1]{#1}
\providecommand{\startdata}{}
\providecommand{\enddata}{}
\providecommand{\colhead}[1]{#1}
\providecommand{\teff}{T_{\rm eff}}
\providecommand{\logg}{\log g}
\providecommand{\kms}{\rm km\,s^{-1}}
\providecommand{\ion}[2]{#1 #2}
""".strip()


def wrapped_latex_document(excerpt: str, source_path: Path | None) -> str:
    del source_path
    preamble = default_preamble(excerpt)
    return "\n".join([preamble, latex_macro_stubs(), r"\begin{document}", excerpt, r"\end{document}", ""])


def run_converter(command: list[str], *, cwd: Path, timeout: int = CONVERTER_TIMEOUT_SECONDS) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "error": "",
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def html_cell_text(cell: Any) -> str:
    soup = BeautifulSoup(str(cell), "html.parser")
    for math in soup.find_all("math"):
        replacement = str(math.get("alttext") or math.get_text(" ", strip=True) or "")
        math.replace_with(replacement)
    text = soup.get_text(" ", strip=True)
    return clean_html_cell_text(text)


def cell_span(cell: Any, attribute: str) -> int:
    try:
        return max(1, int(cell.get(attribute) or 1))
    except (TypeError, ValueError):
        return 1


def html_rows_from_section(section: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    pending: dict[int, tuple[int, str]] = {}
    for tr in section.find_all("tr", recursive=False):
        row: list[str] = []
        column_index = 0
        cells = tr.find_all(["th", "td"], recursive=False)
        for cell in cells:
            while column_index in pending:
                remaining, value = pending.pop(column_index)
                row.append(value)
                if remaining > 1:
                    pending[column_index] = (remaining - 1, value)
                column_index += 1
            text = html_cell_text(cell)
            colspan = cell_span(cell, "colspan")
            rowspan = cell_span(cell, "rowspan")
            for offset in range(colspan):
                value = text if offset == 0 else ""
                row.append(value)
                if rowspan > 1:
                    pending[column_index + offset] = (rowspan - 1, value)
            column_index += colspan
        while column_index in pending:
            remaining, value = pending.pop(column_index)
            row.append(value)
            if remaining > 1:
                pending[column_index] = (remaining - 1, value)
            column_index += 1
        if any(row):
            rows.append(row)
    return rows


def html_table_matrix(table: Any) -> tuple[list[list[str]], list[list[str]]]:
    header_rows: list[list[str]] = []
    data_rows: list[list[str]] = []
    for thead in table.find_all("thead", recursive=False):
        header_rows.extend(html_rows_from_section(thead))
    body_sections = table.find_all("tbody", recursive=False)
    if body_sections:
        for tbody in body_sections:
            data_rows.extend(html_rows_from_section(tbody))
    else:
        data_rows = html_rows_from_section(table)
        if not header_rows and len(data_rows) >= 2:
            header_rows = [data_rows.pop(0)]
    while data_rows and leading_body_row_is_header(data_rows[0]):
        header_rows.append(data_rows.pop(0))
    return header_rows, data_rows


def leading_body_row_is_header(row: list[str]) -> bool:
    values = [value for value in row if value]
    if not values:
        return True
    unit_count = sum(1 for value in values if unit_like(value))
    has_numeric_value = any(re.search(r"\d", value) for value in values)
    if unit_count and unit_count >= max(1, len(values) // 2):
        return True
    return not has_numeric_value


def parsed_from_html(html: str, *, method: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return {
            "status": "failed",
            "method": method,
            "error": "no HTML table element found",
            "warnings": [],
            "row_count": 0,
            "column_count": 0,
            "columns": [],
            "header_rows": [],
            "data_rows": [],
        }
    header_rows, data_rows = html_table_matrix(table)
    all_rows = header_rows + data_rows
    if not data_rows:
        return {
            "status": "failed",
            "method": method,
            "error": "no data rows parsed from HTML table",
            "warnings": [],
            "row_count": 0,
            "column_count": max((len(row) for row in all_rows), default=0),
            "columns": [],
            "header_rows": header_rows,
            "data_rows": [],
        }
    column_count = max(len(row) for row in all_rows)
    header_rows = [pad_row(row, column_count) for row in header_rows]
    data_rows = [pad_row(row, column_count) for row in data_rows]
    columns = enrich_column_data_types(build_column_records(header_rows, column_count), data_rows)
    return {
        "status": "success",
        "method": method,
        "error": "",
        "warnings": [],
        "row_count": len(data_rows),
        "column_count": column_count,
        "columns": columns,
        "header_rows": header_rows,
        "data_rows": data_rows,
    }


def failed_parsed_record(*, method: str, error: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "method": method,
        "error": error,
        "warnings": [],
        "row_count": 0,
        "column_count": 0,
        "columns": [],
        "header_rows": [],
        "data_rows": [],
    }


def converter_artifact_paths(source_output_path: Path, method: str) -> dict[str, Path]:
    directory = source_output_path.parent
    return {
        "wrapped_tex": directory / "wrapped.tex",
        "html": directory / f"{method}.html",
        "stdout": directory / f"{method}.stdout.txt",
        "stderr": directory / f"{method}.stderr.txt",
    }


def write_conversion_artifacts(
    *,
    source_output_path: Path,
    method: str,
    wrapped_tex: str,
    html: str,
    stdout: str,
    stderr: str,
    overwrite: bool,
) -> dict[str, str]:
    paths = converter_artifact_paths(source_output_path, method)
    written: dict[str, str] = {}
    for key, path in paths.items():
        if path.exists() and not overwrite:
            written[key] = str(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        content = {
            "wrapped_tex": wrapped_tex,
            "html": html,
            "stdout": stdout,
            "stderr": stderr,
        }[key]
        path.write_text(content, encoding="utf-8")
        written[key] = str(path)
    return written


def conversion_attempt_record(
    *,
    method: str,
    status: str,
    command: list[str],
    error: str,
    artifacts: dict[str, str],
    workspace: Path,
) -> dict[str, Any]:
    return {
        "method": method,
        "status": status,
        "command": command,
        "error": error,
        "artifacts": {key: relative_path(Path(path), workspace=workspace) for key, path in artifacts.items()},
    }


def convert_with_latexml(
    *,
    excerpt: str,
    source_path: Path | None,
    source_output_path: Path,
    workspace: Path,
    dry_run: bool,
    overwrite: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    latexmlc = shutil.which("latexmlc")
    if latexmlc is None:
        return (
            {
                "method": "latexml",
                "status": "skipped",
                "command": ["latexmlc"],
                "error": "latexmlc not found on PATH",
                "artifacts": {},
            },
            {"status": "failed", "error": "latexmlc not found"},
        )
    wrapped = wrapped_latex_document(excerpt, source_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        input_path = tmpdir / "wrapped.tex"
        output_path = tmpdir / "latexml.html"
        input_path.write_text(wrapped, encoding="utf-8")
        command = [
            latexmlc,
            "--format=html5",
            f"--destination={output_path}",
            f"--timeout={CONVERTER_TIMEOUT_SECONDS}",
        ]
        if source_path is not None:
            command.append(f"--path={source_path.parent}")
        command.append(str(input_path))
        result = run_converter(command, cwd=tmpdir)
        html = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        parsed = parsed_from_html(html, method="latexml") if html else failed_parsed_record(method="latexml", error="latexml produced no HTML")
        artifacts: dict[str, str] = {}
        if not dry_run:
            artifacts = write_conversion_artifacts(
                source_output_path=source_output_path,
                method="latexml",
                wrapped_tex=wrapped,
                html=html,
                stdout=result["stdout"],
                stderr=result["stderr"],
                overwrite=overwrite,
            )
        status = "success" if parsed.get("status") == "success" else "failed"
        error = str(parsed.get("error") or result.get("error") or "")
        attempt = conversion_attempt_record(
            method="latexml",
            status=status,
            command=command,
            error=error,
            artifacts=artifacts,
            workspace=workspace,
        )
        return attempt, parsed


def convert_with_pandoc(
    *,
    excerpt: str,
    source_path: Path | None,
    source_output_path: Path,
    workspace: Path,
    dry_run: bool,
    overwrite: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        return (
            {
                "method": "pandoc",
                "status": "skipped",
                "command": ["pandoc"],
                "error": "pandoc not found on PATH",
                "artifacts": {},
            },
            {"status": "failed", "error": "pandoc not found"},
        )
    wrapped = wrapped_latex_document(excerpt, source_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        input_path = tmpdir / "wrapped.tex"
        output_path = tmpdir / "pandoc.html"
        input_path.write_text(wrapped, encoding="utf-8")
        command = [pandoc, "--from=latex", "--to=html", f"--output={output_path}", str(input_path)]
        result = run_converter(command, cwd=tmpdir)
        html = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        parsed = parsed_from_html(html, method="pandoc") if html else failed_parsed_record(method="pandoc", error="pandoc produced no HTML")
        artifacts: dict[str, str] = {}
        if not dry_run:
            artifacts = write_conversion_artifacts(
                source_output_path=source_output_path,
                method="pandoc",
                wrapped_tex=wrapped,
                html=html,
                stdout=result["stdout"],
                stderr=result["stderr"],
                overwrite=overwrite,
            )
        status = "success" if parsed.get("status") == "success" else "failed"
        error = str(parsed.get("error") or result.get("error") or "")
        attempt = conversion_attempt_record(
            method="pandoc",
            status=status,
            command=command,
            error=error,
            artifacts=artifacts,
            workspace=workspace,
        )
        return attempt, parsed


def convert_with_internal_parser(excerpt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed = parse_latex_table_excerpt(excerpt)
    parsed["method"] = "internal"
    if parsed.get("status") == "success":
        parsed["columns"] = enrich_column_data_types(parsed["columns"], parsed["data_rows"])
    attempt = {
        "method": "internal",
        "status": "success" if parsed.get("status") == "success" else "failed",
        "command": [],
        "error": str(parsed.get("error") or ""),
        "artifacts": {},
    }
    return attempt, parsed


def convert_latex_table(
    *,
    excerpt: str,
    source_path: Path | None,
    source_output_path: Path,
    workspace: Path,
    dry_run: bool,
    overwrite: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for converter in (convert_with_latexml, convert_with_pandoc):
        attempt, parsed = converter(
            excerpt=excerpt,
            source_path=source_path,
            source_output_path=source_output_path,
            workspace=workspace,
            dry_run=dry_run,
            overwrite=overwrite,
        )
        attempts.append(attempt)
        if parsed.get("status") == "success":
            return parsed, attempts
    attempt, parsed = convert_with_internal_parser(excerpt)
    attempts.append(attempt)
    return parsed, attempts


def resolve_workspace_path(path_text: str, *, workspace: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return workspace / path


def excerpt_from_source_ref(source_ref: dict[str, Any], *, workspace: Path) -> tuple[Path | None, str, str]:
    path_text = str(source_ref.get("path") or "").strip()
    if not path_text:
        return None, "", "source_ref.path is missing"
    path = resolve_workspace_path(path_text, workspace=workspace)
    if not path.exists():
        return path, "", f"source file does not exist: {path}"
    start_line = int(source_ref.get("start_line") or 0)
    end_line = int(source_ref.get("end_line") or 0)
    if start_line < 1 or end_line < start_line:
        return path, "", "source_ref.start_line/end_line are invalid"
    lines = read_text(path).splitlines()
    if start_line > len(lines):
        return path, "", "source_ref.start_line is past end of file"
    excerpt = "\n".join(lines[start_line - 1 : min(end_line, len(lines))]) + "\n"
    return path, excerpt, ""


def write_table_ecsv(path: Path, parsed: dict[str, Any], *, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(table_ecsv_text(parsed), encoding="utf-8")
    return True


def refresh_ecsv_counts(table_record: dict[str, Any], path: Path) -> None:
    if not path.exists():
        return
    try:
        from astropy.table import Table

        table = Table.read(path, format="ascii.ecsv")
    except Exception as exc:  # pragma: no cover - defensive manifest repair
        warnings = table_record.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append({"code": "ecsv_count_refresh_failed", "message": str(exc)})
        return
    table_record["row_count"] = len(table)
    table_record["column_count"] = len(table.colnames)


def write_excerpt(path: Path, excerpt: str, *, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(excerpt, encoding="utf-8")
    return True


def extract_candidate(
    candidate: dict[str, Any],
    *,
    paper_directory: Path,
    workspace: Path,
    dry_run: bool,
    overwrite: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    internal_table_id = str(candidate.get("id") or "catalog-table")
    safe_id = safe_identifier(internal_table_id)
    source_refs = candidate.get("source_refs")
    source_ref = source_refs[0] if isinstance(source_refs, list) and source_refs else {}
    if not isinstance(source_ref, dict):
        source_ref = {}

    source_path, excerpt, source_error = excerpt_from_source_ref(source_ref, workspace=workspace)
    source_output_path = paper_directory / CATALOG_SOURCES_DIR / safe_id / "excerpt.tex"
    table_output_path = paper_directory / CATALOG_TABLES_DIR / f"{safe_id}.ecsv"

    source_record = {
        "id": internal_table_id,
        "internal_table_id": internal_table_id,
        "kind": str(candidate.get("kind") or ""),
        "status": "failed" if source_error else ("would_write" if dry_run else "written"),
        "source_ref": source_ref,
        "source_path": relative_path(source_path, workspace=workspace) if source_path is not None else "",
        "excerpt_path": relative_path(source_output_path, workspace=workspace),
        "sha256": sha256_text(excerpt) if excerpt else "",
        "line_count": len(excerpt.splitlines()) if excerpt else 0,
        "error": source_error,
    }

    table_record = {
        "id": internal_table_id,
        "internal_table_id": internal_table_id,
        "status": "failed" if source_error else "pending",
        "ecsv_path": relative_path(table_output_path, workspace=workspace),
        "caption": str(source_ref.get("caption") or ""),
        "label": str(source_ref.get("label") or ""),
        "row_count": 0,
        "column_count": 0,
        "environment": "",
        "header_rows": [],
        "columns": [],
        "warnings": [],
        "error": source_error,
        "extraction_method": "",
        "conversion_attempts": [],
        "source_sha256": sha256_text(excerpt) if excerpt else "",
    }
    if source_error:
        return source_record, table_record

    excerpt_for_parse = excerpt
    if source_output_path.exists() and not overwrite:
        excerpt_for_parse = read_text(source_output_path)
        source_record["status"] = "skipped_existing"
    elif dry_run:
        source_record["status"] = "would_write"
    else:
        write_excerpt(source_output_path, excerpt, overwrite=overwrite)
        source_record["status"] = "written"
    source_record["sha256"] = sha256_text(excerpt_for_parse)
    source_record["line_count"] = len(excerpt_for_parse.splitlines())
    table_record["source_sha256"] = sha256_text(excerpt_for_parse)

    parsed, attempts = convert_latex_table(
        excerpt=excerpt_for_parse,
        source_path=source_path,
        source_output_path=source_output_path,
        workspace=workspace,
        dry_run=dry_run,
        overwrite=overwrite,
    )
    table_record.update(
        {
            "status": parsed["status"],
            "extraction_method": str(parsed.get("method") or ""),
            "row_count": parsed["row_count"],
            "column_count": parsed["column_count"],
            "environment": str(parsed.get("environment") or ""),
            "header_rows": parsed["header_rows"],
            "columns": parsed["columns"],
            "warnings": parsed["warnings"],
            "error": parsed["error"],
            "conversion_attempts": attempts,
        }
    )
    if parsed["status"] == "success":
        if dry_run:
            table_record["status"] = "would_write"
        else:
            wrote_ecsv = write_table_ecsv(table_output_path, parsed, overwrite=overwrite)
            if not wrote_ecsv:
                table_record["status"] = "skipped_existing"
            refresh_ecsv_counts(table_record, table_output_path)
    return source_record, table_record


def selected_internal_tables(review: dict[str, Any], *, internal_table_id: str | None) -> list[dict[str, Any]]:
    internal_tables = internal_tables_from_review(review)
    if internal_table_id is None:
        return internal_tables
    selected = [item for item in internal_tables if str(item.get("id") or "") == internal_table_id]
    if not selected:
        raise ValueError(f"internal table id not found in review: {internal_table_id}")
    return selected


def selected_candidates(review: dict[str, Any], *, candidate_id: str | None) -> list[dict[str, Any]]:
    return selected_internal_tables(review, internal_table_id=candidate_id)


def run_status(summary: dict[str, int]) -> str:
    success_count = int(summary.get("success_count") or 0) + int(summary.get("file_success_count") or 0)
    failed_count = int(summary.get("failed_count") or 0) + int(summary.get("file_failed_count") or 0)
    if success_count > 0 and failed_count == 0:
        return "success"
    if success_count > 0:
        return "partial"
    if summary.get("work_count", summary.get("internal_table_count", 0)) == 0:
        return "skipped"
    return "failed"


def extract_catalog_tables(
    *,
    literature_dir: Path,
    arxiv_id: str,
    workspace: Path | None = None,
    internal_table_id: str | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    workspace = workspace or literature_dir.parent
    paper_directory = literature_dir / arxiv_id
    review_path = paper_directory / REVIEW_FILENAME
    if not review_path.exists():
        raise FileNotFoundError(f"catalog review does not exist: {review_path}")
    review = read_json(review_path)
    internal_tables = selected_internal_tables(review, internal_table_id=internal_table_id)

    files: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    for internal_table in internal_tables:
        if str(internal_table.get("kind") or "") != "latex_table":
            internal_table_id_value = str(internal_table.get("id") or "catalog-table")
            files.append(
                {
                    "id": internal_table_id_value,
                    "internal_table_id": internal_table_id_value,
                    "kind": str(internal_table.get("kind") or ""),
                    "status": "deferred",
                    "source_ref": {},
                    "source_path": "",
                    "excerpt_path": "",
                    "sha256": "",
                    "line_count": 0,
                    "error": "only latex_table internal_tables are extracted",
                }
            )
            tables.append(
                {
                    "id": internal_table_id_value,
                    "internal_table_id": internal_table_id_value,
                    "status": "deferred",
                    "ecsv_path": "",
                    "caption": "",
                    "label": "",
                    "row_count": 0,
                    "column_count": 0,
                    "environment": "",
                    "header_rows": [],
                    "error": "only latex_table internal_tables are extracted",
                    "columns": [],
                    "warnings": [],
                    "extraction_method": "",
                    "conversion_attempts": [],
                    "source_sha256": "",
                }
            )
            continue
        source_record, table_record = extract_candidate(
            internal_table,
            paper_directory=paper_directory,
            workspace=workspace,
            dry_run=dry_run,
            overwrite=overwrite,
        )
        files.append(source_record)
        tables.append(table_record)

    success_statuses = {"success", "would_write", "skipped_existing"}
    file_success_statuses = success_statuses | {"written"}
    summary = {
        "internal_table_count": len(internal_tables),
        "work_count": len(internal_tables),
        "table_count": len(tables),
        "success_count": sum(1 for table in tables if table.get("status") in success_statuses),
        "failed_count": sum(1 for table in tables if table.get("status") == "failed"),
        "deferred_count": sum(1 for table in tables if table.get("status") == "deferred"),
        "file_count": len(files),
        "file_success_count": sum(1 for record in files if record.get("status") in file_success_statuses),
        "file_failed_count": sum(1 for record in files if record.get("status") == "failed"),
    }
    now = datetime.now().isoformat(timespec="seconds")
    run_record = {
        "run_id": f"catalog-extraction-{now.replace(':', '').replace('-', '')}",
        "started_at": now,
        "tool": "scripts/extract_catalog_tables.py",
        "options": {
            "arxiv_id": arxiv_id,
            "internal_table_id": internal_table_id,
            "dry_run": dry_run,
            "overwrite": overwrite,
        },
        "summary": summary,
        "status": run_status(summary),
    }
    manifest_path = paper_directory / EXTRACTION_FILENAME
    paper = review.get("paper") if isinstance(review.get("paper"), dict) else {}
    review_meta = review.get("review") if isinstance(review.get("review"), dict) else {}
    manifest = {
        "schema_version": CATALOG_EXTRACTION_SCHEMA_VERSION,
        "generated_at": now,
        "paper": {
            "arxiv_id": str(paper.get("arxiv_id") or arxiv_id),
            "title": str(paper.get("title") or ""),
            "month": str(paper.get("month") or ""),
        },
        "review": {
            "path": relative_path(review_path, workspace=workspace),
            "schema_version": str(review.get("schema_version") or ""),
            "review_status": str(review_meta.get("status") or ""),
        },
        "run": run_record,
        "files": files,
        "tables": tables,
    }
    CatalogExtractionRecord.model_validate(manifest)
    result = {
        "dry_run": dry_run,
        "arxiv_id": arxiv_id,
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "summary": summary,
    }
    if not dry_run:
        write_json(manifest_path, manifest)
    return result


def reviewed_papers_with_internal_tables(literature_dir: Path) -> list[str]:
    ids: list[str] = []
    for path in iter_catalog_review_paths(literature_dir):
        try:
            review = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        review_meta = review.get("review") if isinstance(review.get("review"), dict) else {}
        internal_tables = internal_tables_from_review(review)
        paper = review.get("paper") if isinstance(review.get("paper"), dict) else {}
        if review_meta.get("status") == "reviewed" and internal_tables:
            ids.append(str(paper.get("arxiv_id") or path.parent.name))
    return sorted(dict.fromkeys(ids))


def auto_catalog_jobs(paper_count: int) -> int:
    if paper_count <= 1:
        return 1
    if paper_count <= 8:
        jobs = 2
    elif paper_count <= 32:
        jobs = 4
    elif paper_count <= 96:
        jobs = 8
    else:
        jobs = 12
    return max(1, min(jobs, DEFAULT_AUTO_MAX_JOBS, paper_count))


def resolve_catalog_jobs(jobs: int | str, *, paper_count: int) -> int:
    if isinstance(jobs, str) and jobs.strip().lower() == "auto":
        return auto_catalog_jobs(paper_count)
    return max(1, int(jobs))


def extract_all_reviewed_catalog_tables(
    *,
    literature_dir: Path,
    workspace: Path | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
    jobs: int | str = 1,
) -> dict[str, Any]:
    workspace = workspace or literature_dir.parent
    arxiv_ids = reviewed_papers_with_internal_tables(literature_dir)
    resolved_jobs = resolve_catalog_jobs(jobs, paper_count=len(arxiv_ids))

    def extract_one(arxiv_id: str) -> dict[str, Any]:
        return extract_catalog_tables(
            literature_dir=literature_dir,
            arxiv_id=arxiv_id,
            workspace=workspace,
            dry_run=dry_run,
            overwrite=overwrite,
        )

    if resolved_jobs <= 1 or len(arxiv_ids) <= 1:
        results = [extract_one(arxiv_id) for arxiv_id in arxiv_ids]
    else:
        with ThreadPoolExecutor(max_workers=resolved_jobs) as executor:
            results = list(executor.map(extract_one, arxiv_ids))
    return {
        "dry_run": dry_run,
        "literature_dir": str(literature_dir),
        "paper_count": len(results),
        "jobs": resolved_jobs,
        "jobs_requested": jobs,
        "results": results,
        "summary": {
            "internal_table_count": sum(result["summary"]["internal_table_count"] for result in results),
            "success_count": sum(result["summary"]["success_count"] for result in results),
            "failed_count": sum(result["summary"]["failed_count"] for result in results),
            "deferred_count": sum(result["summary"]["deferred_count"] for result in results),
            "file_count": sum(result["summary"]["file_count"] for result in results),
            "file_success_count": sum(result["summary"]["file_success_count"] for result in results),
            "file_failed_count": sum(result["summary"]["file_failed_count"] for result in results),
        },
    }
