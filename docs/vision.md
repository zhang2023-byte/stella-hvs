# Stella Vision

This document records Stella's motivation and long-term product direction. It is
background context for prioritization and design discussions, not an execution
contract for agents. Current agent behavior is governed by `AGENTS.md` and
`workflows/stella_workflows.yaml`.

## Motivation

A natural first question for anyone entering this field is how many high-velocity
stars (HVS) have been found, and what their velocities and spatial distribution
look like. The question is hard to answer. Different authors use different
observations, selection cuts, and Galactic potential assumptions, and even the
definition of "high-velocity" is ambiguous. Results are scattered across
differently structured tables, often without machine-readable data, hosted on a
patchwork of external infrastructure.

This blocks both observation and theory. Purely observational papers rarely close
the loop: authors hope their catalogs become a reference for later work, but the
difficulties above mean almost no one truly reuses them, and some data is at risk
of being lost permanently. Theorists cannot reliably reuse prior results and
often re-run HVS candidate selection from scratch, steadily increasing the
entropy of the field's data.

Boubert et al. (2018) manually compiled ~500 HVS candidates from the literature
and re-evaluated them with Gaia, finding that nearly all previously reported
late-type candidates were not genuinely hypervelocity
([arXiv:1804.10179](https://arxiv.org/abs/1804.10179),
[ADS:2018MNRAS.479.2789B](https://ui.adsabs.harvard.edu/abs/2018MNRAS.479.2789B/abstract)).
HVS is a relatively small field - roughly 500 papers - yet a substantial
fraction cite that work (about a third of the papers published after it), which
signals a real community need for aggregating and updating older data.

Boubert open-sourced that effort as the
[Open Fast Stars Catalog](https://github.com/astrocatalogs/faststars), a
subdomain of the Open Astronomy Catalog. The vision was ambitious, but it
depended heavily on sustained individual manual curation, and that model proved
unsustainable: faststars has been unmaintained for years and the Open Astronomy
Catalog has stalled, with its site no longer reachable. The most successful comparable example in astronomy is the supernova
community's Transient Name Server, which integrates directly with observatories
to ingest real-time detections - but that approach is unrealistic for a small,
underfunded subfield like HVS.

The root cause of faststars' failure was that the benefit could not cover the
cost. What changed is productivity: agents now perform repetitive, tedious
knowledge work at a cost approaching zero, which is a natural fit for maintaining
a literature-to-catalog data infrastructure. Stella is our proposal - an agent
that automatically fetches and analyzes literature, extracts and integrates HVS
candidates across papers, runs physical validation, and maintains the resulting
database.

## Principles

- Treat stellar objects as the basic unit, not only paper entries.
- Preserve sources and processing history for every key result.
- Produce machine-readable structures before building reading views or websites.
- Let workflows expand from literature organization toward data integration,
  physical validation, and database maintenance.

## Roadmap

Items marked with `*` are exploratory; core capabilities are built first.

1. Literature acquisition

   Accurately locate HVS literature and identify its methods, datasets, and key
   objects, organized into machine-readable records with provenance. The current
   implementation uses DeepXiv and arXiv for discovery, with ADS metadata repair
   for paper-level bibcodes. Long term, ADS should become a primary literature
   source where practical.

2. Data enrichment

   Use stellar IDs, coordinates, and related information from papers to enrich
   objects from Astroquery, CDS, observatory sites, and other traceable sources.
   The goal is an object-level catalog that can integrate multi-level data such
   as 6D phase space, stellar parameters, and spectra, with every value traceable
   to its source.

3. Physical validation

   Run reproducible validation workflows for collected objects. For HVS this
   means velocity transformations and orbit integration for origin tracing,
   ideally cross-validating the same object across multiple data sources and
   models. The processing must be saved so results are reproducible. Prefer
   high-level Skill + CLI workflows over wrapping the whole Python package; expose
   higher-level function objects rather than a thin CLI over all of, for example,
   galpy.

4. Database maintenance

   Enable AI-assisted incremental updates to the object database and synchronize
   them to a display layer. The website is only a view; the core remains
   structured data, source records, and validation results. The current
   implementation generates a local HTML demo under `catalog/web/`. A hosted
   front/back-end stack (for example GitHub + Vercel + Supabase) is a possible
   long-term direction, not a current dependency.

5. *Workflow iteration

   During literature acquisition, also capture data-processing methods, and have
   the agent distill them to improve later workflows.

6. *Knowledge Q&A

   Organize HVS knowledge - both core concepts and hands-on data-processing
   practice - to onboard and guide new researchers.

7. *Research capability

   After the database and validation layers mature, support hypothesis
   generation, experiment validation, workflow improvement, and paper writing.
