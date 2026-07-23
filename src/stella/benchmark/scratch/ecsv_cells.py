"""ECSV data-row cell parsing for locator validation and hydration (D028, D030).

Rows are whitespace-delimited with double-quoted cells; ``""`` inside a quoted
cell is an escaped quote. Empty cells are always written quoted, so runs of
whitespace are pure separators. The parser copies cell text exactly; it never
rewrites, normalizes, or infers delimiters beyond the ECSV basic format.
"""

from __future__ import annotations


class EcsvRowParseError(ValueError):
    pass


def parse_ecsv_row(line: str) -> list[str]:
    """Split one ECSV data row into exact cell strings."""

    cells: list[str] = []
    index = 0
    length = len(line)
    while index < length:
        while index < length and line[index] in " \t":
            index += 1
        if index >= length:
            break
        if line[index] == '"':
            index += 1
            buffer: list[str] = []
            while True:
                if index >= length:
                    raise EcsvRowParseError("unterminated quoted cell")
                if line[index] == '"':
                    if index + 1 < length and line[index + 1] == '"':
                        buffer.append('"')
                        index += 2
                        continue
                    index += 1
                    break
                buffer.append(line[index])
                index += 1
            cells.append("".join(buffer))
            if index < length and line[index] not in " \t":
                raise EcsvRowParseError("quoted cell must be followed by whitespace")
        else:
            start = index
            while index < length and line[index] not in " \t":
                index += 1
            cells.append(line[start:index])
    return cells


def cell_at(line: str, column_index: int) -> str:
    """Return the exact cell at one zero-based column index."""

    cells = parse_ecsv_row(line)
    if column_index >= len(cells):
        raise EcsvRowParseError(
            f"row has {len(cells)} cells, no cell at column index {column_index}"
        )
    return cells[column_index]
