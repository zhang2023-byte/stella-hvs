"""Object-level contribution timeline catalog tests."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_hvs_contribution_scoring import (
    ai_contribution,
    ai_document,
    ai_identifier,
    ai_value,
)
from stella.lit.hvs_contribution_catalog import (
    build_contribution_catalog,
    object_record,
    write_contribution_catalog,
)


def write_paper(literature_dir: Path, arxiv_id: str, document: dict) -> None:
    document = copy.deepcopy(document)
    document["paper"]["arxiv_id"] = arxiv_id
    paper_dir = literature_dir / arxiv_id
    paper_dir.mkdir(parents=True)
    (paper_dir / "literature_hvs_contributions.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )


class HvsContributionCatalogTest(unittest.TestCase):
    def test_timeline_preserves_bound_followup_in_chronological_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp)
            early = ai_document(
                contributions=[
                    ai_contribution(
                        record_id="obj-001",
                        identifiers=[ai_identifier("HVS-FIC")],
                        contribution_type="follow_up",
                        paper_boundness={"status": "unbound", "evidence": [{"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}]},
                    )
                ]
            )
            late = ai_document(
                contributions=[
                    ai_contribution(
                        record_id="obj-001",
                        identifiers=[ai_identifier("HVS-FIC")],
                        contribution_type="follow_up",
                        paper_boundness={"status": "bound", "evidence": [{"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}]},
                    )
                ]
            )
            write_paper(literature_dir, "2601.00001", early)
            write_paper(literature_dir, "2601.00002", late)
            catalog = build_contribution_catalog(literature_dir)
            self.assertEqual(catalog["object_count"], 1)
            record = object_record(catalog, catalog["_objects"][0]["object_id"])
            timeline = record["timeline"]
            self.assertEqual(len(timeline), 2)
            # Bound reassessment stays visible in the timeline.
            self.assertEqual(timeline[0]["paper_boundness"]["status"], "unbound")
            self.assertEqual(timeline[1]["paper_boundness"]["status"], "bound")
            # Chronological order by arXiv id.
            self.assertEqual(timeline[0]["arxiv_id"], "2601.00001")
            self.assertEqual(timeline[1]["arxiv_id"], "2601.00002")
            # No authoritative global boundness field exists on the record;
            # the only mention is the disclaimer itself.
            serialized = json.dumps(record)
            for forbidden_key in ('"global_boundness"', '"current_status"', '"stella_truth"', '"latest_reported_status"'):
                self.assertNotIn(forbidden_key, serialized)
            self.assertIn("no authoritative global boundness state", record["display_note"])

    def test_values_are_not_flattened_or_deduplicated_across_papers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp)
            values_one = [
                ai_value("8.2", paper_preferred=True),
                ai_value("8.6", paper_preferred=None),
            ]
            values_two = [ai_value("8.2", paper_preferred=None, kind="prior_work")]
            one = ai_document(
                contributions=[
                    ai_contribution(
                        identifiers=[ai_identifier("FIC-1")],
                        quantities=[
                            {"quantity": "observed_phase_space.distance", "values": values_one}
                        ],
                    )
                ]
            )
            two = ai_document(
                contributions=[
                    ai_contribution(
                        identifiers=[ai_identifier("FIC-1")],
                        quantities=[
                            {"quantity": "observed_phase_space.distance", "values": values_two}
                        ],
                    )
                ]
            )
            write_paper(literature_dir, "2601.00001", one)
            write_paper(literature_dir, "2601.00002", two)
            catalog = build_contribution_catalog(literature_dir)
            record = object_record(catalog, catalog["_objects"][0]["object_id"])
            distances = []
            for entry in record["timeline"]:
                for group in entry["quantities"]:
                    if group["quantity"] == "observed_phase_space.distance":
                        distances.extend(value["value"] for value in group["values"])
            # Both papers' values survive: 8.2, 8.6, and the second paper's
            # scientifically distinct prior-work 8.2.
            self.assertEqual(sorted(distances), ["8.2", "8.2", "8.6"])

    def test_gaia_id_groups_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp)
            document = ai_document(
                contributions=[
                    ai_contribution(
                        identifiers=[ai_identifier("FIC-A")],
                    ),
                    ai_contribution(
                        record_id="obj-002",
                        identifiers=[ai_identifier("Gaia DR3 1234567890123456789")],
                    ),
                ]
            )
            write_paper(literature_dir, "2601.00001", document)
            other = ai_document(
                contributions=[
                    ai_contribution(
                        identifiers=[
                            ai_identifier("G-9"),
                            ai_identifier("Gaia DR3 1234567890123456789"),
                        ],
                    )
                ]
            )
            write_paper(literature_dir, "2601.00002", other)
            catalog = build_contribution_catalog(literature_dir)
            self.assertEqual(catalog["object_count"], 2)
            grouped = [
                item
                for item in catalog["_objects"]
                if len(item["timeline"]) == 2
            ]
            self.assertEqual(len(grouped), 1)

    def test_display_name_is_shortest_identifier_independent_of_input_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp)
            contribution = ai_contribution(
                identifiers=[ai_identifier("A MUCH LONGER NAME"), ai_identifier("FIC-1")]
            )
            write_paper(
                literature_dir,
                "2601.00001",
                ai_document(contributions=[contribution]),
            )
            catalog = build_contribution_catalog(literature_dir)
            self.assertEqual(catalog["_objects"][0]["display_name"], "FIC-1")

            contribution["identifiers"].reverse()
            write_paper(
                literature_dir,
                "2601.00002",
                ai_document(contributions=[contribution]),
            )
            catalog = build_contribution_catalog(literature_dir)
            self.assertEqual(catalog["_objects"][0]["display_name"], "FIC-1")

    def test_same_alias_does_not_override_conflicting_gaia_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp)
            for arxiv_id, source_id in (
                ("2601.00001", "1111111111111111111"),
                ("2601.00002", "2222222222222222222"),
            ):
                write_paper(
                    literature_dir,
                    arxiv_id,
                    ai_document(
                        contributions=[
                            ai_contribution(
                                identifiers=[
                                    ai_identifier("SHARED-NAME"),
                                    ai_identifier(f"Gaia DR3 {source_id}"),
                                ],
                            )
                        ]
                    ),
                )
            catalog = build_contribution_catalog(literature_dir)
            self.assertEqual(catalog["object_count"], 2)

    def test_unique_coordinates_bridge_different_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp)

            def coordinate_contribution(name: str) -> dict:
                ra = ai_value("120") | {
                    "unit": "deg",
                    "coordinate_format": "decimal_degrees",
                }
                dec = ai_value("30") | {
                    "unit": "deg",
                    "coordinate_format": "decimal_degrees",
                }
                return ai_contribution(
                    identifiers=[ai_identifier(name)],
                    quantities=[
                        {"quantity": "observed_phase_space.ra", "values": [ra]},
                        {"quantity": "observed_phase_space.dec", "values": [dec]},
                    ],
                )

            write_paper(
                literature_dir,
                "2601.00001",
                ai_document(contributions=[coordinate_contribution("NAME-A")]),
            )
            write_paper(
                literature_dir,
                "2601.00002",
                ai_document(contributions=[coordinate_contribution("NAME-B")]),
            )
            catalog = build_contribution_catalog(literature_dir)
            self.assertEqual(catalog["object_count"], 1)
            self.assertEqual(catalog["_objects"][0]["identifiers"], ["NAME-A", "NAME-B"])

    def test_write_catalog_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp)
            output_dir = Path(tmp) / "catalog" / "contributions"
            output_dir.mkdir(parents=True)
            stale = output_dir / "hvc-stale.json"
            stale.write_text("{}", encoding="utf-8")
            write_paper(literature_dir, "2601.00001", ai_document())
            result = write_contribution_catalog(literature_dir, output_dir=output_dir)
            self.assertEqual(result["object_count"], 1)
            index = json.loads((output_dir / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(
                index["schema"],
                {"name": "hvs_contribution_catalog.index", "version": 1},
            )
            object_files = list(output_dir.glob("hvc-*.json"))
            self.assertEqual(len(object_files), 1)
            record = json.loads(object_files[0].read_text(encoding="utf-8"))
            self.assertEqual(
                record["schema"],
                {"name": "hvs_contribution_catalog.object", "version": 1},
            )
            self.assertEqual(len(record["timeline"]), 1)
            self.assertFalse(stale.exists())
            self.assertEqual(result["removed_stale"], [str(stale)])


if __name__ == "__main__":
    unittest.main()
