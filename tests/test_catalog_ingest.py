from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.catalog_ingest import bootstrap_catalog_ingestion  # noqa: E402


class CatalogIngestTest(unittest.TestCase):
    def test_bootstrap_catalog_ingestion_creates_scaffold_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_dir = root / "literature" / "2603.00001"
            tables_dir = paper_dir / "source" / "catalog_tables"
            tables_dir.mkdir(parents=True)

            schema_table = tables_dir / "paper_table_01.csv"
            schema_table.write_text(
                "Label,Unit,Description\n"
                "designation,---,Gaia DR3 source id\n"
                "RAdeg,[deg],Right ascension\n",
                encoding="utf-8",
            )
            main_catalog = tables_dir / "paper_table_02.csv"
            main_catalog.write_text(
                "Gaia source id,RAdeg,pmRA\n"
                ",[deg],[mas/yr]\n"
                "123,10.1,-3.5\n"
                "456,20.2,1.1\n",
                encoding="utf-8",
            )

            record = {
                "schema_version": "stella.literature.catalog.v2",
                "generated_at": "2026-04-21T12:34:56",
                "arxiv_id": "2603.00001",
                "title": "A stellar catalog paper",
                "catalog": {
                    "location": "mixed",
                    "tables": [
                        {
                            "source_tex": "paper.tex",
                            "caption": "Catalog format",
                            "header": [],
                            "row_count": 2,
                            "csv_path": str(schema_table),
                        },
                        {
                            "source_tex": "paper.tex",
                            "caption": "Main catalog of candidate stars",
                            "header": [],
                            "row_count": 2,
                            "csv_path": str(main_catalog),
                        },
                    ],
                    "data_files": [],
                },
                "verification": {"overall_verdict": "confirmed_with_source_fallback"},
                "agent_adjudication": {
                    "schema_version": "stella.literature.catalog.agent_adjudication.v1",
                    "reviewed_at": "2026-04-21T13:00:00",
                    "reviewed_by": "agent",
                    "skill_path": "skills/literature-catalog-verifier/SKILL.md",
                    "skill_version": "0.2.0",
                    "has_catalog_data": True,
                    "catalog_scope": "sample_level",
                    "internal_delivery": "partial",
                    "external_delivery": "full",
                    "location_class": "mixed",
                    "primary_host": "cds",
                    "confidence": "high",
                    "overall_verdict": "agent_confirmed",
                    "reasoning_notes": "Main table should be ingested.",
                },
            }
            (paper_dir / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

            result = bootstrap_catalog_ingestion(
                paper_dir=paper_dir,
                workspace_root=root,
                overwrite=False,
            )

            ingest_dir = paper_dir / "catalog_ingest"
            manifest = json.loads((ingest_dir / "manifest.json").read_text(encoding="utf-8"))
            field_definitions = json.loads((ingest_dir / "field_definitions.json").read_text(encoding="utf-8"))
            column_mapping = json.loads((ingest_dir / "column_mapping.json").read_text(encoding="utf-8"))

        self.assertEqual(result["catalog_candidate_count"], 2)
        self.assertEqual(manifest["schema_version"], "stella.catalog.ingest.manifest.v1")
        self.assertEqual(manifest["verification_summary"]["decision_source"], "agent")
        self.assertEqual(manifest["verification_summary"]["primary_host"], "cds")
        self.assertEqual(manifest["catalog_candidates"][0]["catalog_role_hint"], "schema_definition")
        self.assertEqual(manifest["catalog_candidates"][0]["schema_field_count"], 2)
        self.assertEqual(manifest["catalog_candidates"][1]["catalog_role_hint"], "candidate_catalog")
        self.assertTrue(manifest["status"]["field_definitions_started"])
        self.assertTrue(manifest["status"]["column_mapping_started"])
        self.assertEqual(manifest["catalog_candidates"][1]["units_row"], ["", "[deg]", "[mas/yr]"])
        self.assertEqual(
            manifest["catalog_candidates"][1]["preview_rows"],
            [["123", "10.1", "-3.5"], ["456", "20.2", "1.1"]],
        )
        self.assertEqual(field_definitions["catalogs"][0]["status"], "drafted")
        self.assertEqual(field_definitions["catalogs"][0]["fields"][0]["source_column"], "designation")
        self.assertEqual(field_definitions["catalogs"][0]["fields"][0]["standardized_name"], "gaia_dr3_source_id")
        self.assertEqual(field_definitions["catalogs"][0]["fields"][1]["source_column"], "RAdeg")
        self.assertEqual(field_definitions["catalogs"][0]["fields"][1]["semantic_type"], "coordinate")
        self.assertEqual(field_definitions["catalogs"][1]["fields"][0]["source_column"], "Gaia source id")
        self.assertEqual(field_definitions["catalogs"][1]["fields"][1]["units_hint"], "[deg]")
        schema_ra_mapping = next(
            item
            for item in column_mapping["mappings"]
            if item["catalog_id"].endswith("paper_table_01") and item["source_column"] == "RAdeg"
        )
        self.assertEqual(schema_ra_mapping["standardized_name"], "ra_deg_icrs")
        self.assertEqual(schema_ra_mapping["semantic_group"], "coordinate")
        self.assertEqual(schema_ra_mapping["unit"], "deg")
        self.assertEqual(schema_ra_mapping["status"], "drafted")
        pmra_mapping = next(item for item in column_mapping["mappings"] if item["source_column"] == "pmRA")
        self.assertEqual(pmra_mapping["unit"], "[mas/yr]")

    def test_bootstrap_catalog_ingestion_preserves_existing_files_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_dir = root / "literature" / "2603.00001"
            tables_dir = paper_dir / "source" / "catalog_tables"
            ingest_dir = paper_dir / "catalog_ingest"
            tables_dir.mkdir(parents=True)
            ingest_dir.mkdir(parents=True)

            table_path = tables_dir / "paper_table_01.csv"
            table_path.write_text(
                "col_1,col_2\n"
                "123,10.1\n",
                encoding="utf-8",
            )
            existing_manifest = {"schema_version": "custom", "note": "keep me"}
            (ingest_dir / "manifest.json").write_text(json.dumps(existing_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            record = {
                "schema_version": "stella.literature.catalog.v2",
                "generated_at": "2026-04-21T12:34:56",
                "arxiv_id": "2603.00001",
                "title": "A stellar catalog paper",
                "catalog": {
                    "location": "internal_only",
                    "tables": [
                        {
                            "source_tex": "paper.tex",
                            "caption": "Main catalog",
                            "header": ["source_id", "ra_deg"],
                            "row_count": 1,
                            "csv_path": str(table_path),
                        }
                    ],
                    "data_files": [],
                },
                "verification": {"overall_verdict": "confirmed"},
            }
            (paper_dir / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

            result = bootstrap_catalog_ingestion(
                paper_dir=paper_dir,
                workspace_root=root,
                overwrite=False,
            )

            manifest = json.loads((ingest_dir / "manifest.json").read_text(encoding="utf-8"))

        self.assertIn(str(ingest_dir / "manifest.json"), result["skipped_paths"])
        self.assertEqual(manifest, existing_manifest)


if __name__ == "__main__":
    unittest.main()
