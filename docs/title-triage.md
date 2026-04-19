# Title Triage

Default classifier is `rules`, which is fast and does not call an LLM.

## Direct Matches

Direct matches are accepted immediately and labeled `rule-direct`.

Typical title terms:

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

## Weak Matches

Weak matches are accepted by default and labeled `rule-weak`.
They are kept in the monthly note with the metadata returned by DeepXiv search,
but DeepXiv `brief` is not fetched for them by default.

They cover mechanism or proxy topics such as:

```text
stellar ejection
ejection velocities
dynamically-ejected stars
binary supernova scenario
potential or cluster escapers
globular cluster escaped stars
stellar escape from globular clusters
bow shocks
Galactic-center ejection language
Sgr A* ejection language
Hills mechanism
tidal separation or disruption of binary stars by massive black holes
restricted three-body encounters
intermediate-mass black holes in star clusters
massive black-hole binaries interacting with clusters or binaries
Andromeda/M31 to Milky Way stellar migration
Large Magellanic Cloud, Galactic bar, or Sagittarius Dwarf perturbations with high-velocity-star context
stellar collisions or disruptions
unusual stellar kinematics
```

The rules intentionally reject generic astronomy/tool titles unless the title also has a high-velocity-star signal. Examples that should stay out:

```text
galpy: A Python Library for Galactic Dynamics
emcee: The MCMC Hammer
Galaxy formation and evolution
Gaia Early Data Release 3 summary papers
generic parallax/proper-motion method papers
generic intermediate-mass black hole papers without a star-cluster/ejection context
generic LMC/Galactic-bar trajectory papers without a high-velocity-star context
```

## Hybrid Mode

To ask the LLM to review weak matches before keeping them:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --to 2026-03 \
  --classifier rules \
  --llm-review True
```

In this mode:

- `rule-direct` papers are kept immediately.
- `rule-weak` papers are sent to the LLM.
- LLM-confirmed weak papers are labeled `rule-weak-llm-confirmed`.
- LLM-rejected weak papers are filtered out.
- DeepXiv `brief` is still fetched only for `rule-direct` papers; weak matches
  use search metadata only.

To use full LLM title classification instead:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --to 2026-03 \
  --classifier llm
```
