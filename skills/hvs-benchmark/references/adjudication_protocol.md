# Expert Adjudication Protocol

Audience: the domain expert reviewing benchmark papers in the local review site
(`scripts/serve_benchmark_review.py`). Every click is saved immediately to
`benchmark/adjudication/<arxiv_id>.adjudication.json` with your expert id and a
timestamp; you can stop and resume at any time.

## What you are judging

For each benchmark paper, independent extraction variants were aligned into
candidate clusters. You adjudicate three kinds of items:

1. **Paper status** — does the paper contain Galactic-unbound / HVS candidates
   at all (`candidates_found` vs `no_candidates`)?
2. **Candidate presence** — is each cluster a real candidate that the paper
   treats as possibly unbound from the Galaxy? Inclusion follows the same
   scientific rules as production extraction
   (`skills/hvs-candidates-extraction/SKILL.md`): the paper text must establish
   unbound/HVS-candidate status; tables alone never justify inclusion.
3. **Field values** — for disagreeing fields (and a random sample of agreeing
   ones), which value is what the paper actually reports?

## Verdicts

- `accept` — the displayed value (or the base variant's candidate) is correct.
  For candidate presence, pick the variant whose record should seed the gold
  candidate (`base_variant`).
- `accept_variant` — a different variant's value is the correct one.
- `fix` — no variant is correct; supply the corrected record in the JSON
  editor. The editor pre-fills the closest variant payload; your record must
  satisfy the v7 schema including `source_refs` and `method_refs`.
- `reject` — the cluster is not a candidate in this paper (e.g. the paper
  concludes it is bound, or it is an ordinary runaway).
- `reject_field` — the paper does not report this field; gold leaves it empty.
- `add_missing` — every variant missed a candidate. Use the "uncovered table
  rows" panel as a recall aid and supply a full candidate payload.

## Evidence standards

- Judge against the displayed evidence excerpts (LaTeX lines, ECSV cells)
  first; open the archived PDF only when excerpts are insufficient.
- A value is correct when it matches what the paper visibly reports, in the
  paper's own units. Do not re-derive or convert values.
- If the paper is genuinely ambiguous, prefer the variant reading that stays
  closest to the paper's wording, and record the ambiguity in the rationale.

## Completeness obligations

Gold cannot be finalized until every disagreement field, every cluster's
presence, the paper status, and every assigned consensus spot-check item has a
verdict. Spot-check items are fields where all variants agree; they exist to
estimate the residual error rate of consensus values, so judge them
independently — do not assume agreement implies correctness.

## Rationale

A short rationale is required for `fix`, `reject`, `reject_field`, and
`add_missing`; it becomes part of the published correction provenance.
