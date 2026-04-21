from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.catalog_assessment import (  # noqa: E402
    CatalogAssessment,
    LLMCatalogAssessor,
    annotate_record,
)
from high_velocity_lit.markdown import render_month_note  # noqa: E402

SCRIPT = ROOT / "scripts" / "annotate_catalog_data.py"
SPEC = importlib.util.spec_from_file_location("annotate_catalog_data", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
annotate_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(annotate_cli)


def sample_record() -> dict[str, object]:
    return {
        "schema_version": "stella.literature.month.v1",
        "month": "2026-03",
        "date_from": "2026-03-01",
        "date_to": "2026-03-31",
        "run": {"run_id": "test", "started_at": "2026-04-19T00:00:00"},
        "config": {
            "source": "deepxiv",
            "queries": ["hypervelocity stars"],
            "categories": ["astro-ph.GA"],
            "max_results": 20,
            "search_mode": "hybrid",
            "classifier": "rules",
            "llm_review": False,
            "use_brief": True,
        },
        "stats": {
            "raw_unique": 1,
            "relevant_count": 1,
            "category_filtered": 0,
            "score_filtered": 0,
            "classifier_filtered": 0,
            "direct_rule_included": 1,
            "weak_rule_candidates": 0,
            "brief_eligible_count": 1,
            "brief_skipped_weak_count": 0,
        },
        "search_log": [],
        "papers": [
            {
                "arxiv_id": "2603.00001",
                "title": "A catalog of hypervelocity star candidates",
                "authors": ["A. Author"],
                "author_names": "A. Author",
                "categories": ["astro-ph.GA"],
                "published_at": "2026-03-01",
                "links": {
                    "abs": "https://arxiv.org/abs/2603.00001",
                    "pdf": "https://arxiv.org/pdf/2603.00001",
                },
                "abstract": {
                    "source": "deepxiv",
                    "text": "We present a catalog of high-velocity star candidates with Gaia astrometry.",
                },
                "match": {"queries": ["hypervelocity stars"], "categories": ["astro-ph.GA"], "best_score": 2.0},
                "triage": {"level": "direct", "label": "rule-direct", "include": True, "confidence": 0.95},
                "deepxiv": {"score": 2.0, "best_score": 2.0},
                "brief": {
                    "fetched": True,
                    "source": "deepxiv",
                    "tldr": "The work reports object-level candidate tables and astrometry.",
                    "keywords": ["catalog", "Gaia"],
                },
                "provenance": {"search_source": "deepxiv", "brief_source": "deepxiv", "run_id": "test"},
            }
        ],
    }


class FakeAssessor:
    def assess_batch(self, papers: list[dict[str, object]]) -> dict[str, CatalogAssessment]:
        return {
            "2603.00001": CatalogAssessment(
                has_observational_catalog=True,
                confidence=0.91,
                catalog_role="new_catalog",
                object_scope="multiple_objects",
                evidence="Abstract and brief mention candidate tables and Gaia astrometry.",
                data_products=["candidate_table", "astrometry"],
            )
        }


class CatalogAssessmentTest(unittest.TestCase):
    def test_range_selection_maps_dates_to_month_json_paths(self) -> None:
        notes_dir = Path("/tmp/notes")
        start = annotate_cli.parse_period("2025-02-14", kind="from", today=date(2026, 4, 19))
        end = annotate_cli.parse_period("2025-04", kind="to", today=date(2026, 4, 19))

        self.assertEqual(
            annotate_cli.json_paths_from_range(notes_dir, start, end),
            [
                notes_dir / "2025" / "2025-02" / "2025-02.json",
                notes_dir / "2025" / "2025-03" / "2025-03.json",
                notes_dir / "2025" / "2025-04" / "2025-04.json",
            ],
        )

    def test_omitted_to_defaults_to_today(self) -> None:
        self.assertEqual(annotate_cli.infer_period_end("2025-03", today=date(2026, 4, 19)), date(2026, 4, 19))

    def test_on_selection_supports_one_month_or_comma_list(self) -> None:
        self.assertEqual(
            annotate_cli.parse_on_value("2025-01"),
            ["2025-01"],
        )
        self.assertEqual(
            annotate_cli.parse_on_value("2025-03,2025-06, 2026-01"),
            ["2025-03", "2025-06", "2026-01"],
        )
        self.assertEqual(
            annotate_cli.json_paths_from_months(Path("/tmp/notes"), ["2025-01", "2025-03"]),
            [
                Path("/tmp/notes") / "2025" / "2025-01" / "2025-01.json",
                Path("/tmp/notes") / "2025" / "2025-03" / "2025-03.json",
            ],
        )

    def test_on_selection_rejects_brackets_and_list_prefix(self) -> None:
        for value in ("[2025-01,2025-03]", "list:[2025-01,2025-03]", "[2025-01"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    annotate_cli.parse_on_value(value)

    def test_annotate_record_adds_catalog_assessment_and_markdown(self) -> None:
        record = sample_record()
        summary = annotate_record(
            record,
            FakeAssessor(),
            batch_size=5,
            method="llm",
            model="test-model",
            assessed_at=datetime(2026, 4, 19, 12, 0, 0),
        )

        self.assertEqual(summary["assessed"], 1)
        self.assertEqual(summary["catalog_count"], 1)
        paper = record["papers"][0]  # type: ignore[index]
        assessment = paper["catalog_assessment"]  # type: ignore[index]
        self.assertTrue(assessment["has_observational_catalog"])
        self.assertEqual(assessment["catalog_role"], "new_catalog")

        markdown = render_month_note(record)
        self.assertIn("Observational catalog assessment: assessed 1 paper", markdown)
        self.assertIn("Observational catalog assessment: Likely; role=new_catalog", markdown)
        self.assertIn("Possible data products: candidate_table, astrometry", markdown)

    def test_llm_payload_includes_abstract_and_brief(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        [
                                            {
                                                "arxiv_id": "2603.00001",
                                                "has_observational_catalog": True,
                                                "confidence": 0.9,
                                                "catalog_role": "new_catalog",
                                                "object_scope": "multiple_objects",
                                                "evidence": "brief mentions candidate table",
                                                "data_products": ["candidate_table"],
                                            }
                                        ]
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(request: object, timeout: int) -> FakeResponse:
            captured["payload"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            return FakeResponse()

        record = sample_record()
        assessor = LLMCatalogAssessor(api_key="test", base_url="https://example.test", model="test-model")
        with patch("urllib.request.urlopen", fake_urlopen):
            decisions = assessor.assess_batch(record["papers"])  # type: ignore[arg-type,index]

        self.assertTrue(decisions["2603.00001"].has_observational_catalog)
        messages = captured["payload"]["messages"]  # type: ignore[index]
        user_message = messages[1]["content"]  # type: ignore[index]
        self.assertIn("We present a catalog of high-velocity star candidates", user_message)
        self.assertIn("object-level candidate tables and astrometry", user_message)

    def test_cli_rebuilds_collection_index_after_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp) / "notes"
            month_dir = notes_dir / "2026" / "2026-03"
            month_dir.mkdir(parents=True)
            json_path = month_dir / "2026-03.json"
            json_path.write_text(json.dumps(sample_record(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (notes_dir / "index.json").write_text(
                json.dumps(
                    {
                        "schema_version": "stella.literature.index.v3",
                        "summary": {"literature_count": 0, "data_related_count": 0},
                        "years": [],
                        "papers": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "annotate_catalog_data.py",
                        "--on",
                        "2026-03",
                        "--notes-dir",
                        str(notes_dir),
                    ],
                ),
                patch.object(annotate_cli, "LLMCatalogAssessor", return_value=FakeAssessor()),
                patch.object(annotate_cli, "load_llm_api_key", return_value="test-key"),
            ):
                exit_code = annotate_cli.main()

            self.assertEqual(exit_code, 0)
            index = json.loads((notes_dir / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["summary"]["literature_count"], 1)
            self.assertEqual(index["summary"]["data_related_count"], 1)
            self.assertEqual(index["papers"][0]["arxiv_id"], "2603.00001")
            index_markdown = (notes_dir / "index.md").read_text(encoding="utf-8")
            self.assertIn("A catalog of hypervelocity star candidates", index_markdown)


if __name__ == "__main__":
    unittest.main()
