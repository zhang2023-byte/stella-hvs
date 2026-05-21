# Stella Vision

This document records Stella's long-term product direction. It is background
context for prioritization and design discussions, not an execution contract for
agents. Current agent behavior is governed by `AGENTS.md`,
`docs/agent-workflows.md`, and `workflows/stella_workflows.yaml`.

Stella is not only a literature collection tool. Its long-term goal is to build
a traceable, reproducible, and continuously updated object-level data and
knowledge system for high-velocity-star research.

The design should consistently follow these principles:

- Treat stellar objects as the basic unit, not only paper entries.
- Preserve sources and processing history for every key result.
- Produce machine-readable structures before building reading views or websites.
- Let workflows expand from literature organization toward data integration,
  physical validation, and database maintenance.

## Core Capabilities

1. Literature acquisition

   Accurately locate high-velocity-star literature and identify its methods,
   datasets, and key objects. The current implementation uses DeepXiv and arXiv
   for discovery, with ADS metadata repair for paper-level bibcodes. Long term,
   ADS should become a primary literature source where practical. Outputs should
   remain machine-readable and provenance-preserving.

2. Data enrichment

   Use stellar IDs, coordinates, and related information from papers to enrich
   objects from Astroquery, CDS, observatory sites, or other traceable sources.
   The goal is an object-level catalog that can integrate 6D phase space,
   stellar parameters, spectra, and derived quantities.

3. Physical validation

   Run reproducible validation workflows for collected stellar objects. For HVS
   research, priorities include velocity transformations, orbit integration, and
   origin tracing. Prefer high-level Skill + CLI workflows over broad wrappers
   around the whole Python package.

4. Database maintenance

   Enable AI-assisted incremental updates to the object database and synchronize
   those updates to the display layer. The website is only a view; the core
   remains structured data, source records, and validation results.

## Future Extensions

- Extract data-processing methods from papers during literature acquisition and
  use them to improve later workflows.
- Organize HVS knowledge for Q&A and onboarding.
- Support hypothesis generation, experiment validation, workflow improvement,
  and paper writing after the database and validation layers mature.
