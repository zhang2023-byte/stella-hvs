# Schema v0.3 Notes

**Status (2026-07-06): v0.3 landed.** Second (and final) pre-formal-runs
schema revision, decided by the expert immediately after the gold8 `ai_only`
triage. Same scope discipline as v0.2: **clear design defects only, no
prompt fine-tuning**. Motivation: the expert plans a full re-extraction of
method A (skill agent) plus a third dev round of methods B/C on an
extraction surface that is field-for-field aligned with the gold guideline,
so the three methods compare on the same schema without scorer projections.

v0.2 (`stella.literature_hvs_candidates.v0.2`, defined earlier the same
day) was superseded **before any extraction instantiated it** — no document
anywhere carries the v0.2 version string, so there is no v0.2 reader and no
v0.2 compatibility surface. Readers dispatch between v0.1 (legacy corpus)
and v0.3 (current).

## Landed in v0.3 (2026-07-06)

- **`bound_assessment` reduced to the two probability slots**
  (`bound_probability`, `unbound_probability`). Expert decision from the
  gold8 triage: record whichever probability the paper reports; an escape
  probability **is** an unbound probability (escape ≡ unbound), so P_esc
  records under `unbound_probability`. The dropped fields —
  `escape_velocity`, `escape_velocity_ratio`, `escape_margin`,
  `bound_status_metric` — were rarely comparable across papers and diluted
  the scored vocabulary; no gold annotation ever used them. The scored
  vocabulary shrinks from 23 to 19 fields (GUIDELINE §5,
  docs/benchmark-l2-spec.md amendment v0.2.1). AI values on the dropped
  fields in archived v0.1 runs simply leave the scored surface, exactly
  like `total_velocity`.
- **Plain-spelling `unit` contract**: the semantic validator rejects LaTeX
  markup (braces, `$`, backslashes, commands) in quantity `unit` fields —
  `mas yr^{-1}` must be written `mas yr^-1`; the typeset form stays in
  `raw_value`/source refs. Complementary scorer-side change: `normalize_unit`
  (synonym table v2) strips the same residue so archived v0.1 runs score
  correctly without re-extraction. Found via gold8 unit_mismatch rows that
  were pure markup differences.
- **Gold-side unit discipline reaffirmed**: the 1807.00427 gold annotation
  had converted printed pc distances to kpc "for consistency" — reverted to
  the printed pc values, and GUIDELINE §6 now names pc↔kpc scale shifts
  explicitly in the never-convert examples.
- **Method A run provenance contract**: agent-harness reruns are archived
  like B/C runs under `benchmark/runs/<run_id>/` with a `run_config.json`
  that must record the **harness** (name/version of the coding-agent
  runtime) and **model**. `scripts/init_agent_run.py` scaffolds the config;
  the scorer copies `harness` into `run_source` and the report displays it.
  Per-paper `extraction.tooling` mirrors the same facts
  (`agent_runtime = "<harness>/<version>"`, `model_id`).
- **Version mechanics**: `LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION` is
  v0.3; the legacy reader family gains `LegacyBoundAssessment` (restores
  the four dropped fields for v0.1 documents) alongside
  `LegacyDerivedKinematics.total_velocity`. Extraction pipelines bumped:
  B `stella-benchmark-extraction` 0.6.0 (prompt template v0.6.0 via the
  regenerated schema reference), C `stella-agentic-extraction` 0.3.0.

## Deferred items

The v0.2 parking lot (docs/schema-v0.2-notes.md §"Still deferred") carries
over unchanged; nothing on that list was promoted into v0.3.
