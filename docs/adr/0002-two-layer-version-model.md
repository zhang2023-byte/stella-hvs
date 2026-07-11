# ADR 0002: Two-layer version model

Status: accepted for Stella 0.2.0.

Stella uses two version layers. The project release (`0.2.0`) communicates a
human-facing software milestone. Each independently persisted artifact carries
only a local integer schema reference:

```json
{"schema":{"name":"literature_hvs_candidates","version":2}}
```

Artifact integers are comparable only within the same canonical name. The
central registry in `src/stella/schema_registry.py` owns current/readable
versions, lifecycle, legacy aliases, and model dispatch. Nested structures do
not declare versions; their parent artifact owns them. Producer changes are
recorded as provenance hashes rather than parallel semantic-version sequences.

Benchmark reproducibility is an orthogonal identity boundary. The immutable
`hvs-extraction-v1` campaign is read-only history; `hvs-extraction-v2` is the
active campaign. Normal readers accept only structured schema references.
Archived v1 files retain their bytes and are available only through explicit
legacy inspection paths.

Consequences: new writers have one envelope, documentation is generated from
one registry, and domain schema numbers change only when that artifact's
payload semantics change. Private gold migration remains a private-repository
maintenance operation and may not execute in the public workspace.
