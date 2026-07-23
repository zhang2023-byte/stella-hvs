"""Minimal TeX cleaning for the model-facing manuscript view (D006).

Cleaning removes only content known not to be part of the paper — TeX comments
— while preserving physical line positions exactly: one input line stays one
output line, so ``N|`` prefixes in the model view always map to the original
physical line numbers. No macro expansion, summarization, or prose rewriting.

Comment handling respects verbatim-style environments (``verbatim``,
``lstlisting``, ``minted``, ``Verbatim``) and inline ``\\verb`` spans, where
``%`` is literal text rather than a comment starter.
"""

from __future__ import annotations

VERBATIM_ENVIRONMENTS = ("verbatim", "verbatim*", "lstlisting", "minted", "Verbatim")

_BEGIN = "\\begin{"
_END = "\\end{"
_VERB = "\\verb"


def _verbatim_begin_env(line: str, start: int) -> str | None:
    for env in VERBATIM_ENVIRONMENTS:
        marker = f"{_BEGIN}{env}}}"
        if line.startswith(marker, start):
            return env
    return None


def _strip_line(line: str, in_verbatim: str | None) -> tuple[str, str | None]:
    """Strip an unescaped comment from one line, tracking verbatim state."""

    if in_verbatim is not None:
        end_marker = f"{_END}{in_verbatim}}}"
        if end_marker in line:
            in_verbatim = None
        return line, in_verbatim

    index = 0
    length = len(line)
    while index < length:
        if line.startswith(_VERB, index):
            cursor = index + len(_VERB)
            if cursor < length and line[cursor] == "*":
                cursor += 1
            if cursor < length:
                delimiter = line[cursor]
                closing = line.find(delimiter, cursor + 1)
                index = length if closing == -1 else closing + 1
                continue
            index = length
            continue
        env = _verbatim_begin_env(line, index)
        if env is not None:
            return line, env
        char = line[index]
        if char == "%":
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                return line[:index], None
        index += 1
    return line, None


def strip_tex_comments(text: str) -> str:
    """Remove TeX comments while preserving physical line positions."""

    stripped: list[str] = []
    in_verbatim: str | None = None
    for line in text.split("\n"):
        cleaned, in_verbatim = _strip_line(line, in_verbatim)
        stripped.append(cleaned)
    return "\n".join(stripped)


def render_file_block(path: str, cleaned_text: str) -> str:
    """Render one named TeX file block with ``N|`` physical line prefixes."""

    lines = cleaned_text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    body = "\n".join(f"{number}|{line}" for number, line in enumerate(lines, 1))
    return f"===== BEGIN FILE: {path} =====\n{body}\n===== END FILE: {path} ====="


def render_manuscript_view(blocks: list[tuple[str, str]]) -> str:
    """Render the complete model-facing manuscript from (path, cleaned) pairs."""

    return "\n\n".join(render_file_block(path, text) for path, text in blocks) + "\n"
