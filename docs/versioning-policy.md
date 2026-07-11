# Stella Versioning Policy

This policy defines how Stella versions evolve. Current values come only from
`src/stella/schema_registry.py`; `docs/versions.md` is generated from that
registry and must not be edited by hand.

## 1. Version axes

Stella has three independent identifiers:

1. **Stella release** — a human-facing SemVer release such as `0.2.0`.
2. **Artifact schema** — a positive integer local to one canonical artifact
   name, such as `literature_hvs_candidates` version 2.
3. **Benchmark campaign ID** — an immutable evaluation contract such as
   `hvs-extraction-v2`.

Producer, prompt, skill, validator, model, runtime, and context-packer changes
do not receive parallel human-maintained versions. They are identified by Git
commit, runtime/model identity, component SHA256, and `method_fingerprint` in
provenance.

## 2. Stella release rules

Stella uses Semantic Versioning. While the project remains below 1.0, it uses a
stricter policy than SemVer requires:

- **PATCH** (`0.2.0 → 0.2.1`): bug fixes, performance work, tests,
  documentation, rendering changes, or internal refactoring that does not
  change a persisted contract or required user behavior. Patch releases must
  not contain breaking changes.
- **MINOR** (`0.2.x → 0.3.0`): new user-visible capabilities, workflows,
  persisted artifact types, artifact schema versions, or breaking changes to
  CLI/workflow/reader behavior during the pre-1.0 period.
- **MAJOR** (`1.x → 2.0.0`): after 1.0, any incompatible public API, CLI,
  workflow, or persistence-contract change.

`1.0.0` should be released only after the CLI, workflow contract, schema
migration policy, and campaign lifecycle are stable enough to support an
explicit compatibility promise. Python metadata omits the `v` prefix; Git
release tags use `v<version>`, such as `v0.3.0` or `v0.3.0rc1`.

## 3. Artifact schema rules

Artifact versions are comparable only when their canonical `name` is the same.
Changing one artifact never mechanically increments another.

Increment an artifact integer when a persisted domain payload changes in a way
that can affect reading, validation, or interpretation, including:

- adding a field that current writers may emit;
- removing or renaming a field;
- changing a field's type, requiredness, unit, range, default, or meaning;
- changing enum meaning or domain validation semantics;
- changing container shape or identity semantics.

Do not increment an artifact for documentation, rendering, error-message,
implementation, model, prompt, runtime, or provenance-hash changes that leave
the persisted domain contract unchanged.

For every `N → N+1` transition:

1. Add the new model and registry version; keep `N` readable while retained
   data requires it.
2. Make all normal writers emit only `N+1`.
3. Dispatch readers through the registry, never scattered version literals.
4. Provide an explicit, idempotent, atomic migration with a value-free audit.
5. Validate before and after migration and compare business payloads after
   excluding schema/provenance management fields.
6. Add unknown-version, dry-run, repeat-run, and partial-failure tests.
7. Regenerate `docs/versions.md` from the registry.

Legacy string envelopes are accepted only by the explicit read-only legacy
adapter or migration fixtures, not as a permanent production format.

## 4. Benchmark campaign rules

A campaign is immutable after freeze. Create a new campaign ID when changing
anything that defines the evaluation cohort or meaning of headline results:

- paper sample or dev/test split;
- gold scientific judgments or annotation protocol;
- candidate inclusion boundary or scored quantity vocabulary;
- matching, scoring, aggregation, contamination, release, or evidence rules;
- any campaign manifest content.

Do not create a campaign for a new model, prompt, skill, harness, provider,
retry policy, extraction implementation, or participating method. Those are run
provenance and `method_fingerprint` differences inside the active campaign.

The practical test is: if old and new scores cannot share one comparison table
without qualification about what was measured, create a new campaign. Frozen
campaigns receive no new formal runs. Campaign tags are immutable and must
never be moved or overwritten.

## 5. Scorer corrections

Do not silently overwrite a published scorecard.

- A correction that cannot change headline results is a Stella patch release
  plus updated scorer provenance.
- A defect that changes results invalidates or supersedes affected scorecards.
  If it changes scoring meaning or comparability, create a new campaign. If it
  only fixes implementation of an unchanged frozen rule, retain both records
  and record the superseding scorer provenance.

When uncertain, prefer a new campaign over retroactively changing a frozen
result's meaning.

## 6. Release checklist

Every release that changes version state must:

- update `src/stella/schema_registry.py` and `pyproject.toml` consistently;
- include required models, migrations, compatibility tests, and CLI tests;
- regenerate schema references, generated views, and `docs/versions.md`;
- update workflows, README, usage, and output documentation when needed;
- run `conda run -n stella-env python -m unittest discover tests`;
- scan active code and data for scattered version literals and legacy envelopes;
- record breaking changes and migration instructions in release notes;
- create release/campaign tags only after the commit exists and tests pass.

When none of the release, artifact, or campaign conditions are met, record the
implementation change only in provenance and Git history; do not invent a new
version number.
