# Stella Vision and Roadmap

This file records the project's long-term goals and implementation direction.

Stella is not only a literature collection tool. Its goal is to gradually build a traceable, reproducible, and continuously updated object-level data and knowledge system for high-velocity-star research.

The design should consistently follow these principles:

- Treat stellar objects as the basic unit, not only paper entries.
- Preserve sources and processing history for every key result.
- Produce machine-readable structures before building reading views or websites.
- Let the workflow expand from literature organization toward data integration, physical validation, and database maintenance.

## Core Capabilities

1. Literature acquisition

   Accurately locate high-velocity-star literature and identify its methods, datasets, and key objects. ADS should be the primary source, with arXiv and DeepXiv as supporting sources. Outputs should be organized as machine-readable Markdown, CSV, or structured JSON whenever possible, with provenance preserved.

2. Data enrichment

   Use stellar IDs, coordinates, and related information from papers to enrich objects from Astroquery, CDS, observatory sites, or other traceable sources. The goal is not merely to copy paper tables, but to build a star-object-level catalog. This catalog can gradually integrate data at different levels, including 6D phase space, stellar parameters, spectra, and derived quantities.

3. Physical validation

   Run reproducible physical validation workflows for collected stellar objects. For high-velocity stars, priorities include velocity transformations, orbit integration, and origin tracing. This layer should prefer high-level `Skill + CLI` workflows over simply wrapping the entire Python package as a CLI. The same object should support cross-validation across multiple data sources and models, with the validation process fully preserved.

4. Database maintenance

   Enable AI-assisted incremental updates to the object database and synchronize those updates to the website. The website is only the display layer; the core remains the structured database, source records, and validation results. During the demo stage, a stack such as `GitHub + Vercel + Supabase` can be considered.

## Future Extensions

5. Workflow iteration

   During literature acquisition, extract not only stellar data but also data-processing methods. AI should be able to summarize workflows from methods and gradually improve existing workflows.

6. Knowledge Q&A

   Organize high-velocity-star knowledge from the literature, including basic concepts and practical procedures. The goal is to help new researchers enter the field faster.

7. Scientific research support

   After the database, methods, and validation workflows mature, further support hypothesis generation, experiment validation, workflow improvement, and paper writing.

## Implementation Order

Stabilize the first four core capabilities before gradually adding items five through seven.
