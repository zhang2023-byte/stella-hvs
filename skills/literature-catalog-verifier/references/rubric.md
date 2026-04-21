# Catalog Verification Rubric

Use this rubric when an automated keyword-based result looks wrong.

## Boundary Rule

Keep this split explicit:

- extraction, download, caching, file parsing, and index sync should stay in scripts or deterministic tooling
- interpretation of ambiguous evidence should be done by the agent following this rubric

If you find yourself encoding more and more special cases into host-name lists or keyword rules, pause and ask whether the case is actually semantic rather than mechanical.

## Strong Positive Signals

- "The full table is available in machine-readable form ..."
- "Published in its entirety online ..."
- "Available at CDS / China-VO / Zenodo ..." when clearly tied to the paper's own catalog
- An appendix table explicitly described as the full catalog
- Source-extracted tables that clearly contain the catalog rows, not only column definitions

## Internal Delivery

Treat as internal evidence when:

- the paper embeds the actual catalog rows in appendix or source tables
- the source contains data-like tables extracted into `source/catalog_tables/*.csv`
- the paper says the machine-readable table is included with the journal article or online article itself

Use `internal_delivery=partial` when the appendix appears to show only a subset or illustrative excerpt.
Use `internal_delivery=format_only` when the paper only gives a column-description or schema table.

## External Delivery

Treat as external evidence only when the repository mention is explicitly tied to the paper's own catalog or full table.

Examples that should count:

- "The full machine-readable table is available at CDS."
- "Table 6 is published in its entirety on China-VO."
- "The catalog is hosted at Zenodo ..."

Examples that should not count by themselves:

- the paper used VizieR or SIMBAD during analysis
- a bibliography entry points to a VizieR catalog
- acknowledgements thank CDS or archive staff
- a generic repository URL appears without any tie to the paper's own table or catalog

Use `external_delivery=reference_only` when a repository is mentioned but the evidence does not prove it hosts the paper's own catalog.

## Mixed Cases

Use `location_class=mixed` only when both are true:

1. the paper provides meaningful internal delivery
2. the paper also explicitly provides external delivery of the same catalog or a fuller machine-readable version

Do not call a paper `mixed` merely because:

- it has appendix tables and also cites VizieR/CDS in methods
- it has extracted URLs from source files that are unrelated to the paper's own output

## Appendix Nuance

Appendix evidence needs a second pass:

- Appendix sample rows or a "catalog format" table do not automatically mean the full catalog is internal.
- A long table in the appendix may still be only a printed subset if the paper separately says the full version is online.

## Preferred Reasoning Style

- Prefer explicit hosting statements over inferred host names.
- Prefer paper-specific phrasing over generic archive mentions.
- Be conservative with external-host calls.
- When uncertain, return `unclear` and explain what is missing.
- When disagreeing with the automated pipeline, state both the heuristic failure mode and the evidence that supports the override.
