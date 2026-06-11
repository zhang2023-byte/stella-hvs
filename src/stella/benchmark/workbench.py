"""Evidence review workbench for verification-role benchmark papers.

Renders one static HTML page per paper: every AI assertion (candidate
identities, scored quantities, method parameters) on the left, anchored to
the paper PDF on the right. Anchoring is text-based: each assertion's
raw/normalized value is searched in the PDF text layer (PyMuPDF), the best
page is chosen (preferring pages that also mention the candidate), the hit
is highlighted, and a cropped snippet image is rendered inline so the
expert sees the printed evidence without leaving the page. A link opens the
full PDF at the anchored page for context.

Anti-contamination: blind-role papers are refused unconditionally — blind
annotators must never see AI output (AGENTS.md, Benchmark
Anti-Contamination Rules). The PDF is the normative evidence source; the
workbench therefore anchors into the PDF, not into TeX/ECSV pipeline
artifacts (those remain available to adjudicators in the extracted JSON).

Review verdicts (confirm / reject / uncertain plus a note) are kept in the
browser's localStorage and exported as YAML for merging into the expert's
annotation file.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path

import fitz

MIN_ANCHOR_LENGTH = 3
SNIPPET_ZOOM = 2.0
SNIPPET_PAD_VERTICAL = 42.0

CORE_CONTAINERS = ("observed_phase_space", "derived_kinematics", "bound_assessment")


class WorkbenchContaminationError(RuntimeError):
    """Raised when a blind-role paper is requested."""


@dataclass(frozen=True)
class Assertion:
    assertion_id: str
    group: str
    label: str
    display_value: str
    raw_value: str = ""
    anchors: tuple[str, ...] = ()
    context_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnchorHit:
    page_index: int
    rect: tuple[float, float, float, float]
    term: str


@dataclass
class LocatedAssertion:
    assertion: Assertion
    hit: AnchorHit | None = None
    snippet_relpath: str = ""
    extra_pages: tuple[int, ...] = field(default_factory=tuple)


def manifest_entry(manifest: dict, arxiv_id: str) -> dict | None:
    for entry in manifest.get("papers", []):
        if entry.get("arxiv_id") == arxiv_id:
            return entry
    return None


def ensure_reviewable(
    manifest: dict, arxiv_id: str, allow_unsampled: bool = False
) -> str:
    """Return the manifest role, refusing blind papers unconditionally."""

    entry = manifest_entry(manifest, arxiv_id)
    if entry is None:
        if allow_unsampled:
            return "unsampled"
        raise ValueError(
            f"{arxiv_id} is not in the sampling manifest; use "
            "--allow-unsampled for off-benchmark papers (e.g. pilots)"
        )
    role = entry.get("role", "")
    if role == "blind":
        raise WorkbenchContaminationError(
            f"{arxiv_id} is a blind-role paper; blind annotators must never "
            "see AI output (AGENTS.md, Benchmark Anti-Contamination Rules)"
        )
    return role


def _quantity_display(record: dict) -> str:
    parts = []
    value = record.get("value", "")
    limit_kind = record.get("limit_kind", "")
    if limit_kind == "range":
        parts.append(f"{record.get('range_lower', '')}..{record.get('range_upper', '')}")
    elif value:
        parts.append(value)
    error = record.get("error", "")
    lower = record.get("lower_error", "")
    upper = record.get("upper_error", "")
    if error:
        parts.append(f"± {error}")
    elif lower or upper:
        parts.append(f"+{upper} / -{lower}")
    unit = record.get("unit", "")
    if unit:
        parts.append(unit)
    if limit_kind and limit_kind != "range":
        parts.append(f"[{limit_kind}]")
    elif limit_kind == "range":
        parts.append("[range]")
    return " ".join(parts).strip()


def _value_anchors(record: dict) -> tuple[str, ...]:
    anchors = []
    for key in ("raw_value", "value", "range_lower", "range_upper"):
        text = str(record.get(key, "") or "").strip()
        if len(text) >= MIN_ANCHOR_LENGTH and text.lower() != "unknown":
            anchors.append(text)
    seen: list[str] = []
    for anchor in anchors:
        if anchor not in seen:
            seen.append(anchor)
    return tuple(seen)


def _candidate_names(candidate: dict) -> tuple[str, ...]:
    identifiers = candidate.get("identifiers", {})
    names = [item.get("value", "") for item in identifiers.get("all", [])]
    gaia = identifiers.get("gaia_source_id", "")
    if gaia:
        names.append(gaia)
        digits = gaia.split()[-1]
        if digits.isdigit():
            names.append(digits)
    return tuple(name for name in names if len(name) >= MIN_ANCHOR_LENGTH)


def extract_assertions(payload: dict) -> list[Assertion]:
    """Flatten an extraction document into reviewable assertions."""

    assertions: list[Assertion] = []
    extraction = payload.get("extraction", {})
    assertions.append(
        Assertion(
            assertion_id="document|status",
            group="document",
            label="extraction.status",
            display_value=extraction.get("status", ""),
        )
    )

    for candidate in payload.get("candidates", []):
        identifiers = candidate.get("identifiers", {})
        record_id = identifiers.get("record_id", "?")
        group = f"candidate:{record_id}"
        names = _candidate_names(candidate)
        gaia = identifiers.get("gaia_source_id", "")
        display_names = ", ".join(
            item.get("value", "") for item in identifiers.get("all", [])
        )
        assertions.append(
            Assertion(
                assertion_id=f"{group}|identifiers",
                group=group,
                label="identifiers",
                display_value=(
                    f"{record_id}" + (f" — Gaia: {gaia}" if gaia else "")
                    + (f" — names: {display_names}" if display_names else "")
                ),
                anchors=names,
                context_terms=names,
            )
        )
        inclusion = candidate.get("inclusion_assessment", {})
        assertions.append(
            Assertion(
                assertion_id=f"{group}|inclusion",
                group=group,
                label="inclusion_assessment",
                display_value=(
                    f"{', '.join(inclusion.get('paper_labels', []))} — "
                    f"bound claim: {inclusion.get('galactic_bound_claim', '')} — "
                    f"{inclusion.get('summary', '')}"
                ),
                anchors=names,
                context_terms=names,
            )
        )
        core = candidate.get("core", {})
        for container in CORE_CONTAINERS:
            for field_name, record in (core.get(container) or {}).items():
                if not isinstance(record, dict):
                    continue
                display = _quantity_display(record)
                if not display and not record.get("raw_value"):
                    continue
                assertions.append(
                    Assertion(
                        assertion_id=f"{group}|{container}.{field_name}",
                        group=group,
                        label=f"{container}.{field_name}",
                        display_value=display,
                        raw_value=str(record.get("raw_value", "")),
                        anchors=_value_anchors(record),
                        context_terms=names,
                    )
                )

    for step in payload.get("method_chain", []):
        step_type = step.get("step_type", "")
        for parameter in step.get("parameters", []):
            name = parameter.get("name", "")
            assertions.append(
                Assertion(
                    assertion_id=f"method|{step.get('id', '')}|{name}",
                    group="method",
                    label=f"{step_type}: {name}",
                    display_value=_quantity_display(parameter),
                    raw_value=str(parameter.get("raw_value", "")),
                    anchors=_value_anchors(parameter),
                )
            )

    step_types = sorted(
        {step.get("step_type", "") for step in payload.get("method_chain", [])}
    )
    if step_types:
        assertions.append(
            Assertion(
                assertion_id="method|step_types",
                group="method",
                label="step types present",
                display_value=", ".join(step_types),
            )
        )
    return assertions


def locate_assertion(
    doc: "fitz.Document", assertion: Assertion, page_texts: list[str]
) -> AnchorHit | None:
    """Find the best PDF anchor for one assertion.

    Tries anchors in order (raw value first). Among pages containing the
    term, pages that also mention a context term (candidate name) win.
    """

    for term in assertion.anchors:
        candidate_pages = [
            index for index, text in enumerate(page_texts) if term in text
        ]
        if not candidate_pages:
            continue
        preferred = [
            index
            for index in candidate_pages
            if any(context in page_texts[index] for context in assertion.context_terms)
        ]
        ordered = preferred + [p for p in candidate_pages if p not in preferred]
        for page_index in ordered:
            rects = doc[page_index].search_for(term)
            if rects:
                rect = rects[0]
                return AnchorHit(
                    page_index=page_index,
                    rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                    term=term,
                )
    return None


def render_snippet(
    doc: "fitz.Document", hit: AnchorHit, output_path: Path
) -> None:
    """Render a highlighted page strip around the anchor hit."""

    page = doc[hit.page_index]
    rect = fitz.Rect(*hit.rect)
    highlight = fitz.Rect(
        rect.x0 - 1.5, rect.y0 - 1.5, rect.x1 + 1.5, rect.y1 + 1.5
    )
    page.draw_rect(highlight, color=(0.8, 0.1, 0.1), width=1.2)
    clip = fitz.Rect(
        page.rect.x0,
        max(page.rect.y0, rect.y0 - SNIPPET_PAD_VERTICAL),
        page.rect.x1,
        min(page.rect.y1, rect.y1 + SNIPPET_PAD_VERTICAL),
    )
    matrix = fitz.Matrix(SNIPPET_ZOOM, SNIPPET_ZOOM)
    pixmap = page.get_pixmap(matrix=matrix, clip=clip)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(output_path)


def locate_all(
    doc: "fitz.Document", assertions: list[Assertion], snippets_dir: Path
) -> list[LocatedAssertion]:
    page_texts = [doc[index].get_text() for index in range(doc.page_count)]
    located: list[LocatedAssertion] = []
    for order, assertion in enumerate(assertions):
        hit = locate_assertion(doc, assertion, page_texts)
        item = LocatedAssertion(assertion=assertion, hit=hit)
        if hit is not None:
            snippet_name = f"assertion-{order:03d}.png"
            render_snippet(doc, hit, snippets_dir / snippet_name)
            item.snippet_relpath = f"snippets/{snippet_name}"
        located.append(item)
    return located


_PAGE_STYLE = """
:root { --ink:#000; --ink-mute:#5a5a5f; --canvas:#fff; --cool:#f0f0fa;
        --hairline:#e0e0e8; --reject:#a01010; --confirm:#0a6b2d; }
* { box-sizing: border-box; }
body { margin:0; background:var(--canvas); color:var(--ink);
       font:14px/1.5 -apple-system, "Helvetica Neue", Arial, sans-serif; }
header { padding:14px 20px; border-bottom:1px solid var(--hairline);
         display:flex; gap:16px; align-items:baseline; flex-wrap:wrap; }
header h1 { font-size:16px; margin:0; }
header .meta { color:var(--ink-mute); }
header button { margin-left:auto; }
main { display:grid; grid-template-columns: minmax(420px, 56%) 1fr; }
#assertions { border-right:1px solid var(--hairline); padding:12px 20px 80px;
              max-height: calc(100vh - 53px); overflow-y:auto; }
#pdf-pane { position:sticky; top:53px; height:calc(100vh - 53px); }
#pdf-pane iframe { width:100%; height:100%; border:0; }
h2.group { font-size:13px; text-transform:uppercase; letter-spacing:.06em;
           color:var(--ink-mute); border-bottom:1px solid var(--hairline);
           padding-bottom:4px; margin:22px 0 8px; }
.assertion { border:1px solid var(--hairline); border-radius:4px;
             padding:10px 12px; margin:10px 0; background:var(--canvas); }
.assertion.confirmed { background:#f3faf5; border-color:var(--confirm); }
.assertion.rejected { background:#fbf3f3; border-color:var(--reject); }
.assertion.uncertain { background:var(--cool); }
.assertion .label { font-weight:600; }
.assertion .value { font-family:ui-monospace, "SF Mono", Menlo, monospace; }
.assertion .raw { color:var(--ink-mute); font-size:12px; }
.assertion img { max-width:100%; border:1px solid var(--hairline);
                 margin-top:8px; display:block; }
.assertion .anchor-missing { color:var(--ink-mute); font-style:italic;
                             font-size:12px; }
.controls { margin-top:8px; display:flex; gap:6px; align-items:center; }
.controls button { border:1px solid var(--hairline); background:var(--canvas);
                   border-radius:3px; padding:2px 10px; cursor:pointer; }
.controls button.active[data-verdict="confirmed"] { background:var(--confirm); color:#fff; }
.controls button.active[data-verdict="rejected"] { background:var(--reject); color:#fff; }
.controls button.active[data-verdict="uncertain"] { background:var(--ink-mute); color:#fff; }
.controls input { flex:1; border:1px solid var(--hairline); border-radius:3px;
                  padding:2px 8px; font:inherit; }
a.page-link { font-size:12px; }
#progress { font-variant-numeric: tabular-nums; }
"""

_PAGE_SCRIPT = """
(function () {
  const arxivId = document.body.dataset.arxivId;
  const storageKey = "stella-workbench-" + arxivId;
  const state = JSON.parse(localStorage.getItem(storageKey) || "{}");

  function save() { localStorage.setItem(storageKey, JSON.stringify(state)); }

  function apply(card) {
    const id = card.dataset.assertionId;
    const entry = state[id] || {};
    card.classList.remove("confirmed", "rejected", "uncertain");
    if (entry.verdict) card.classList.add(entry.verdict);
    card.querySelectorAll(".controls button[data-verdict]").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.verdict === entry.verdict);
    });
    const note = card.querySelector(".controls input");
    if (note && note.value !== (entry.note || "")) note.value = entry.note || "";
  }

  function refreshProgress() {
    const cards = document.querySelectorAll(".assertion");
    let done = 0;
    cards.forEach(card => { if ((state[card.dataset.assertionId] || {}).verdict) done++; });
    document.getElementById("progress").textContent =
      done + " / " + cards.length + " reviewed";
  }

  document.querySelectorAll(".assertion").forEach(card => {
    const id = card.dataset.assertionId;
    card.querySelectorAll(".controls button[data-verdict]").forEach(btn => {
      btn.addEventListener("click", () => {
        const entry = state[id] || {};
        entry.verdict = entry.verdict === btn.dataset.verdict ? "" : btn.dataset.verdict;
        state[id] = entry;
        save(); apply(card); refreshProgress();
      });
    });
    const note = card.querySelector(".controls input");
    if (note) note.addEventListener("input", () => {
      const entry = state[id] || {};
      entry.note = note.value;
      state[id] = entry;
      save();
    });
    card.querySelectorAll("a.page-link").forEach(link => {
      link.addEventListener("click", event => {
        const frame = document.getElementById("pdf-frame");
        if (!frame) return;
        event.preventDefault();
        frame.src = link.getAttribute("href");
      });
    });
    apply(card);
  });

  document.getElementById("export").addEventListener("click", () => {
    const lines = ["arxiv_id: \\"" + arxivId + "\\"",
                   "exported_at: \\"" + new Date().toISOString() + "\\"",
                   "verdicts:"];
    document.querySelectorAll(".assertion").forEach(card => {
      const id = card.dataset.assertionId;
      const entry = state[id] || {};
      lines.push("  - assertion_id: " + JSON.stringify(id));
      lines.push("    verdict: " + JSON.stringify(entry.verdict || "unreviewed"));
      lines.push("    note: " + JSON.stringify(entry.note || ""));
    });
    const blob = new Blob([lines.join("\\n") + "\\n"], { type: "text/yaml" });
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(blob);
    anchor.download = "workbench_verdicts_" + arxivId + ".yaml";
    anchor.click();
    URL.revokeObjectURL(anchor.href);
  });

  refreshProgress();
})();
"""


def _assertion_card(item: LocatedAssertion, pdf_href: str) -> str:
    assertion = item.assertion
    parts = [
        f'<div class="assertion" data-assertion-id="{html.escape(assertion.assertion_id, quote=True)}">',
        f'<div class="label">{html.escape(assertion.label)}</div>',
    ]
    if assertion.display_value:
        parts.append(
            f'<div class="value">{html.escape(assertion.display_value)}</div>'
        )
    if assertion.raw_value and assertion.raw_value != assertion.display_value:
        parts.append(
            f'<div class="raw">raw: {html.escape(assertion.raw_value)}</div>'
        )
    if item.hit is not None:
        page_number = item.hit.page_index + 1
        parts.append(
            f'<a class="page-link" href="{pdf_href}#page={page_number}">'
            f"PDF p.{page_number} (match: {html.escape(item.hit.term)})</a>"
        )
        if item.snippet_relpath:
            parts.append(
                f'<img src="{item.snippet_relpath}" loading="lazy" '
                f'alt="PDF snippet, page {page_number}">'
            )
    elif assertion.anchors:
        parts.append(
            '<div class="anchor-missing">not auto-located in the PDF — '
            "use the PDF search yourself; if absent there, that is "
            "evidence-side information</div>"
        )
    parts.append(
        '<div class="controls">'
        '<button data-verdict="confirmed">✓</button>'
        '<button data-verdict="rejected">✗</button>'
        '<button data-verdict="uncertain">?</button>'
        '<input placeholder="note / correction">'
        "</div>"
    )
    parts.append("</div>")
    return "\n".join(parts)


def render_workbench_html(
    arxiv_id: str,
    title: str,
    located: list[LocatedAssertion],
    pdf_href: str,
) -> str:
    groups: dict[str, list[LocatedAssertion]] = {}
    for item in located:
        groups.setdefault(item.assertion.group, []).append(item)

    body_sections = []
    for group, items in groups.items():
        heading = {
            "document": "Document",
            "method": "Method chain",
        }.get(group, group.replace("candidate:", "Candidate: "))
        cards = "\n".join(_assertion_card(item, pdf_href) for item in items)
        body_sections.append(
            f'<h2 class="group">{html.escape(heading)}</h2>\n{cards}'
        )

    located_count = sum(1 for item in located if item.hit is not None)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Workbench — {html.escape(arxiv_id)}</title>
<style>{_PAGE_STYLE}</style>
</head>
<body data-arxiv-id="{html.escape(arxiv_id, quote=True)}">
<header>
  <h1>{html.escape(arxiv_id)}</h1>
  <span class="meta">{html.escape(title)}</span>
  <span class="meta">{located_count}/{len(located)} assertions auto-located</span>
  <span class="meta" id="progress"></span>
  <button id="export">Export verdicts (YAML)</button>
</header>
<main>
  <section id="assertions">
    {"".join(body_sections)}
  </section>
  <section id="pdf-pane">
    <iframe id="pdf-frame" src="{pdf_href}" title="paper PDF"></iframe>
  </section>
</main>
<script>{_PAGE_SCRIPT}</script>
</body>
</html>
"""


def build_paper_workbench(
    arxiv_id: str,
    extraction_path: Path,
    pdf_path: Path,
    output_dir: Path,
    pdf_href: str,
) -> dict:
    """Build one paper's workbench page. Returns a small build report."""

    payload = json.loads(extraction_path.read_text(encoding="utf-8"))
    assertions = extract_assertions(payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as doc:
        located = locate_all(doc, assertions, output_dir / "snippets")
        page = render_workbench_html(
            arxiv_id,
            payload.get("paper", {}).get("title", ""),
            located,
            pdf_href,
        )
    (output_dir / "index.html").write_text(page, encoding="utf-8")
    return {
        "arxiv_id": arxiv_id,
        "assertions": len(located),
        "located": sum(1 for item in located if item.hit is not None),
        "output": str(output_dir / "index.html"),
    }
