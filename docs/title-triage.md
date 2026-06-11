# Title Triage

The default workflow first applies rule-based title triage, then optionally asks an LLM to review papers whose titles have no clear evidence.

## Rule-Related

Papers that match explicit high-velocity-star title rules are assigned to `rule-related` and enter the final monthly note directly.

Common title terms:

```text
hypervelocity star
high-velocity star
high-velocity RR Lyrae stars
extreme-velocity stars
fastest stars in the Galaxy
runaway star
hyper-runaway star
unbound star
escaping/ejected star
stellar escaper
walkaway star
hypervelocity/high-velocity star surveys, searches, candidates, catalogues
```

## No Clear Title Evidence

Any title that does not match an explicit high-velocity-star rule is assigned to `no-clear-title-evidence`.

The workflow intentionally no longer keeps a separate `rejected` title bucket. Even if a title looks more like a generic tool, method, or astronomy paper, it goes into this bucket unless it directly matches the relevance rules.

These papers do not enter the final monthly note directly, but they are saved in the monthly title triage file:

```text
notes/YYYY/YYYY-MM/YYYY-MM.title-triage.json
```

Common examples include:

```text
Stellar Escape from Globular Clusters
Where do they come from? Identification of globular cluster escaped stars
galpy: A Python Library for Galactic Dynamics
emcee: The MCMC Hammer
Galaxy formation and evolution
Gaia Early Data Release 3 summary papers
Joint inference from parallax and proper motions
```

## LLM Review for No-Clear-Title-Evidence Papers

```bash
conda run -n stella-env python scripts/fetch_literature.py \
  --from 2026-03 \
  --llm-review True
```

In this mode:

- `rule-related` papers enter the final monthly note directly.
- `no-clear-title-evidence` papers are sent to the LLM for review.
- Papers confirmed relevant by the LLM enter the final monthly note.
- Papers rejected by the LLM, or papers without a returned review result, do not enter the final monthly note.
