# Title Triage

Default classifier is `rules`, which is fast and does not call an LLM.

## Direct Matches

Direct matches are accepted immediately and labeled `rule-direct`.

Typical title terms:

```text
hypervelocity star
high-velocity star
runaway star
unbound star
escaping/ejected star
stellar escaper
walkaway star
```

## Weak Matches

Weak matches are accepted by default and labeled `rule-weak`.

They cover mechanism or proxy topics such as:

```text
stellar ejection
ejection velocities
dynamically-ejected stars
binary supernova scenario
potential or cluster escapers
bow shocks
Galactic-center ejection language
stellar collisions or disruptions
unusual stellar kinematics
```

## Hybrid Mode

To ask the LLM to review weak matches before keeping them:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --classifier rules \
  --llm-review-weak
```

In this mode:

- `rule-direct` papers are kept immediately.
- `rule-weak` papers are sent to the LLM.
- LLM-confirmed weak papers are labeled `rule-weak-llm-confirmed`.
- LLM-rejected weak papers are filtered out.

To use full LLM title classification instead:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --classifier llm
```
