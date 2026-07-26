"""Reusable value-free fixtures for canonical extraction tests."""

from __future__ import annotations


def core_quantity(**overrides) -> dict:
    base = {
        "value": "805",
        "error": None,
        "lower_error": None,
        "upper_error": None,
        "unit": "km/s",
        "limit_kind": "none",
        "range_lower": None,
        "range_upper": None,
        "direct_evidence": [
            {
                "part": "value",
                "source": {
                    "kind": "ecsv_cell",
                    "path": "catalog_tables/t1.ecsv",
                    "line": 8,
                    "column": "col_002",
                    "quantity_raw_value": "805",
                },
            }
        ],
        "context_evidence": [],
    }
    base.update(overrides)
    return base


def paper_result(
    *,
    status: str = "complete",
    roster_status: str = "candidates_found",
    candidates: list[dict] | None = None,
    fields: dict | None = None,
) -> dict:
    roster_candidates = [
        {
            "record_id": "candidate-001",
            "display_name": "HVS-1",
            "identifiers": [
                {
                    "value": "HVS-1",
                    "source_refs": [],
                    "recognition": {"kind": "other"},
                },
                {
                    "value": "Gaia DR3 123456789",
                    "source_refs": [],
                    "recognition": {
                        "kind": "gaia",
                        "release": "DR3",
                        "source_id": "123456789",
                    },
                },
            ],
            "qualification": {"reason": "r", "source_refs": []},
        }
    ]
    entries = []
    for candidate in candidates or []:
        entries.append(
            {
                "record_id": candidate["record_id"],
                "display_name": "HVS-1",
                "status": candidate["status"],
                "fields": (
                    fields
                    if candidate["status"] == "fields_complete"
                    else None
                ),
                "bibliography": {
                    "origin_type": "introduced_by_this_paper",
                    "paper_reassesses_unbound_status": False,
                    "resolution": None,
                },
                "failure": candidate.get("failure"),
                "attempts": [],
                "provenance": {},
            }
        )
    return {
        "status": status,
        "roster_status": roster_status,
        "roster": {
            "candidates": roster_candidates,
            "reviewed_exclusions": [],
        },
        "candidates": entries,
    }


def complete_fields(**core_overrides) -> dict:
    observed = {
        "ra": None,
        "dec": None,
        "distance": None,
        "parallax": None,
        "proper_motion_ra": None,
        "proper_motion_dec": None,
        "radial_velocity": core_quantity(),
    }
    observed.update(core_overrides)
    return {
        "candidate_origin": {
            "origin_type": "introduced_by_this_paper",
            "bibkey": None,
            "evidence": [],
        },
        "core": {
            "observed_phase_space": observed,
            "derived_kinematics": {
                "galactocentric_x": None,
                "galactocentric_y": None,
                "galactocentric_z": None,
                "galactocentric_radius": None,
                "galactocentric_vx": None,
                "galactocentric_vy": None,
                "galactocentric_vz": None,
                "tangential_velocity": None,
                "galactocentric_tangential_velocity": None,
                "galactic_rest_frame_velocity": None,
            },
            "bound_assessment": {
                "bound_probability": None,
                "unbound_probability": None,
            },
        },
        "provenance_conflicts": [],
    }
