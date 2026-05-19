# RA/Dec Coordinate Frame Reference

Use this reference only when the paper does not explicitly state the frame or
epoch for an RA/Dec value. Paper text, captions, and table headers take
precedence over this lookup table.

## Inference Rules

- Infer per coordinate component, not per `observed_phase_space` object.
- If RA and Dec come from the same table column pair or same catalog statement,
  the nested `reference_frame` and `epoch` objects can cite the same evidence.
- If the paper gives a frame/epoch directly, set `inference_basis` to
  `paper_statement`.
- If the table header or column header gives it, set `inference_basis` to
  `table_header`.
- If the paper only names a known survey/data release listed below, set
  `inference_basis` to `survey_reference` and copy the matching
  `reference_entry_id`.
- If the survey or data release is not listed here, do not guess. Set
  `reference_frame.value` and `epoch.value` to `unknown`, use
  `inference_basis` such as `not_in_reference` or `not_reported`, and keep the
  paper-visible source catalog/data release text in the context object.

## Known Survey Data Releases

| reference_entry_id | Catalog/data release | reference_frame.value | epoch.value | epoch_kind | Notes |
| --- | --- | --- | --- | --- | --- |
| `gaia-dr3` | Gaia DR3 | `ICRS` | `J2016.0` | `reference_epoch` | Gaia DR3 positions and proper motions are referred to ICRS at reference epoch J2016.0. |
| `gaia-edr3` | Gaia EDR3 | `ICRS` | `J2016.0` | `reference_epoch` | Gaia EDR3 shares the DR3 astrometric reference epoch. |
| `gaia-dr2` | Gaia DR2 | `ICRS` | `J2015.5` | `reference_epoch` | Gaia DR2 astrometry uses ICRS coordinates valid for epoch J2015.5. |

## Notes On J2000

Do not treat `J2000.0` as automatically equivalent to a Gaia reference epoch.
When a source says `RA (J2000)` or `Dec (J2000)`, record the literal evidence
and set `epoch_kind` to `equinox` if the paper clearly means an equinox, or
`ambiguous` if it is only a table-label convention. If the source also states
ICRS, record that in `reference_frame`; otherwise leave the frame `unknown`.

## Sources

- Gaia DR3/EDR3: https://gaia.aip.de/metadata/gaiadr3/
- Gaia EDR3 metadata: https://gaia.aip.de/metadata/gaiaedr3/
- Gaia DR2 and J2000/equinox explanation: https://www.cosmos.esa.int/web/gaia/faqs
