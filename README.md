# Stella

Stella is an autonomous agent for high-velocity-star (HVS) research. It turns
scattered literature into a traceable, reproducible, object-level data catalog,
and keeps that catalog updated mostly through natural-language conversation with
an AI agent.

## Why Stella

A natural first question in this field is simple: how many high-velocity stars
have we found, and what are their velocities and spatial distribution? It is
surprisingly hard to answer. Different authors use different observations,
selection cuts, Galactic potential assumptions, and even different definitions
of "high-velocity". Results live in differently structured tables, often without
machine-readable data, hosted on a patchwork of infrastructure. Purely
observational papers rarely get reused, some data is at risk of being lost for
good, and theorists usually re-derive HVS candidate selection from scratch -
steadily increasing the entropy of the field's data.

Boubert et al. (2018) manually compiled ~500 HVS candidates from the literature
and re-evaluated them with Gaia, showing that almost all previously reported
late-type candidates were not genuinely hypervelocity
([arXiv:1804.10179](https://arxiv.org/abs/1804.10179),
[ADS](https://ui.adsabs.harvard.edu/abs/2018MNRAS.479.2789B/abstract)). A
sizable fraction of subsequent HVS work cites that effort, which signals a real
community need for aggregating and updating older data. But projects that depend
on sustained manual curation - the
[Open Fast Stars Catalog](https://github.com/astrocatalogs/faststars) and the
Open Astronomy Catalog - proved unsustainable and have stalled. A TNS-style
pipeline wired directly into observatories is not realistic for a small,
underfunded subfield.

What changed is the cost structure. Agents now perform repetitive, tedious
knowledge work at a cost approaching zero, which makes maintaining a
literature-to-catalog data infrastructure newly feasible. Stella is our attempt:
an agent that automatically fetches and analyzes literature, extracts and merges
HVS candidates across papers, runs physical validation, and maintains the
resulting database.

See [docs/vision.md](docs/vision.md) for the full motivation and roadmap.

## Quick Start

Stella is meant to be driven by talking to an agent, not by memorizing commands.

1. Set up the environment:

```bash
conda env create -f environment.yml
conda activate stella-env
cp env.example .env
```

LaTeX table extraction works best with LaTeXML (`brew install latexml`). Tokens
for DeepXiv, ADS, or LLM features go in `.env`. Details are in
[docs/setup.md](docs/setup.md).

2. Point an agent runtime at this repository. Stella ships its operating rules in
[AGENTS.md](AGENTS.md), so any agent that auto-loads `AGENTS.md` works. Good
options include [OpenClaw](https://github.com/openclaw/openclaw) and
[Hermes Agent](https://github.com/NousResearch/hermes-agent); follow their setup
docs to bind an agent workspace to this folder.

3. Ask in natural language. The agent reads [AGENTS.md](AGENTS.md), routes your
request through [workflows/stella_workflows.yaml](workflows/stella_workflows.yaml),
and asks only for details that change the result, trigger network/API calls, or
risk touching the wrong generated data. For example:

```text
Fetch high-velocity-star literature from 2026-03.
Review structured data assets for 2402.10714.
Extract paper-level HVS candidates for 2402.10714.
Rebuild the object-level HVS catalog.
Calculate HVS dynamics for the object catalog.
Build the HVS catalog HTML demo.
```

The full set of requests, with what each one does, is in
[docs/workflows.md](docs/workflows.md).

## How It Works

Stella is a pipeline of focused workflows. JSON is always the source of truth;
Markdown, indexes, HTML, and the object catalog are generated views or products.

```text
fetch literature  ->  review data assets  ->  extract internal tables
      ->  extract HVS candidates  ->  merge into object catalog
      ->  calculate dynamics  ->  build HTML site
```

Each stage writes machine-readable JSON first; reading views are regenerated
from that JSON. If a generated view looks wrong, the fix is in the source JSON or
the renderer, never in the generated file. See
[docs/workflows.md](docs/workflows.md) for stage-by-stage detail and
[docs/outputs.md](docs/outputs.md) for the data contract.

## Documentation

- Workflows and example requests: [docs/workflows.md](docs/workflows.md)
- Machine-readable workflow contract: [workflows/stella_workflows.yaml](workflows/stella_workflows.yaml)
- Environment setup: [docs/setup.md](docs/setup.md)
- CLI reference: [docs/usage.md](docs/usage.md)
- Output data contract: [docs/outputs.md](docs/outputs.md)
- Title triage rules: [docs/title-triage.md](docs/title-triage.md)
- Motivation and roadmap: [docs/vision.md](docs/vision.md)
- Web/HTML design spec: [docs/DESIGN.md](docs/DESIGN.md)
- Agent operating rules: [AGENTS.md](AGENTS.md)
