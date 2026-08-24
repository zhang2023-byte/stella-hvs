"""Static enforcement of the benchmark anti-contamination rules.

These tests back the three data-flow rules documented in benchmark/AGENTS.md.
They are deliberately blunt: any
mention of the gold directory in pipeline code fails unless the file is on
the explicit human-workflow whitelist, and no gold annotation content may
exist anywhere inside this workspace (the gold store lives in the external
private repository pointed to by STELLA_GOLD_DIR). Touching gold from new
code therefore requires consciously editing this test, which is the point.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "benchmark"
THIS_FILE = Path(__file__).resolve()

# Files that legitimately touch the gold store as part of the human
# annotation workflow, gold integrity tooling, or post-gold diagnostics.
# Scoring code (Phase 4) reads gold and must be added here explicitly when
# it lands.
GOLD_ACCESS_WHITELIST = {
    "scripts/serve_gold_annotation.py",
    "scripts/upgrade_gold_annotation.py",
    "scripts/update_gold_manifest.py",
    "scripts/build_gold_selection.py",
    "scripts/list_gold_annotation_queue.py",
    "scripts/audit_extraction_run.py",
    "scripts/score_benchmark_run.py",
    "src/stella/benchmark/gold_form.py",
    "src/stella/benchmark/gold.py",
    "src/stella/benchmark/gold_selection.py",
    "src/stella/benchmark/scoring.py",
}

GOLD_TOKEN = "benchmark/gold"
AI_OUTPUT_TOKENS = (
    "benchmark/campaigns/",
    "/runs/",
    "literature_hvs_candidates.json",
)

# Gold annotation artifacts follow these name shapes; none may exist inside
# the workspace. The blank/example templates under benchmark/templates/ use
# the distinct gold_annotation_* prefix on purpose.
GOLD_ARTIFACT_PATTERNS = (
    "annotation_*.yaml",
    "annotation_*.json",
    "draft_*.json",
)


def iter_pipeline_python_files() -> list[Path]:
    files: list[Path] = []
    for base in (ROOT / "src", ROOT / "scripts", ROOT / "benchmark", ROOT / "tests"):
        files.extend(
            path
            for path in sorted(base.rglob("*.py"))
            if "__pycache__" not in path.parts and path != THIS_FILE
        )
    return files


class BenchmarkSkeletonTest(unittest.TestCase):
    def test_persisted_benchmark_contract_exists(self) -> None:
        # Gold annotations live in the external private repository
        # (STELLA_GOLD_DIR) and are deliberately absent from this list. The
        # Private gold and per-item scoring details stay outside this workspace;
        # benchmark/ therefore holds no private presentation artifacts.
        self.assertTrue((BENCHMARK_DIR / "templates").is_dir())
        v1 = BENCHMARK_DIR / "campaigns" / "hvs-extraction-v1"
        v2 = BENCHMARK_DIR / "campaigns" / "hvs-extraction-v2"
        v3 = BENCHMARK_DIR / "campaigns" / "hvs-extraction-v3"
        v4 = BENCHMARK_DIR / "campaigns" / "hvs-extraction-v4"
        v5 = BENCHMARK_DIR / "campaigns" / "hvs-extraction-v5"
        v6 = BENCHMARK_DIR / "campaigns" / "hvs-extraction-v6"
        for path in (
            v1 / "manifest",
            v1 / "scoring",
            v2 / "manifest",
            v3 / "manifest",
            v4 / "manifest",
            v5 / "manifest",
            v6 / "manifest",
        ):
            with self.subTest(directory=path.relative_to(BENCHMARK_DIR)):
                self.assertTrue(path.is_dir(), path)
        self.assertTrue((v1 / "archive_inventory.json").is_file())
        for campaign in (v1, v2, v3, v4):
            for name in (
                "sampling_manifest.json",
                "campaign_manifest.json",
                "gold_manifest.json",
            ):
                path = campaign / "manifest" / name
                with self.subTest(contract=path.relative_to(BENCHMARK_DIR)):
                    self.assertTrue(path.is_file(), path)
        for campaign in (v3, v4, v5, v6):
            gold_manifest_path = campaign / "manifest" / "gold_manifest.json"
            gold_manifest = json.loads(gold_manifest_path.read_text(encoding="utf-8"))
            with self.subTest(campaign=campaign.name):
                self.assertEqual(
                    gold_manifest["schema"],
                    {"name": "benchmark.gold_manifest", "version": 1},
                )
                self.assertEqual(
                    set(gold_manifest),
                    {
                        "schema",
                        "generated_at",
                        "paper_count",
                        "annotation_yaml_count",
                        "annotation_json_count",
                        "files",
                    },
                    "public gold manifests must be metadata/hash indexes only",
                )
                files = gold_manifest["files"]
                self.assertEqual(
                    len(files),
                    gold_manifest["annotation_yaml_count"]
                    + gold_manifest["annotation_json_count"],
                )
                self.assertEqual(
                    len({record["arxiv_id"] for record in files}),
                    gold_manifest["paper_count"],
                )
                self.assertTrue(
                    all(
                        set(record) == {"arxiv_id", "file", "sha256", "bytes"}
                        and len(record["sha256"]) == 64
                        for record in files
                    ),
                    "public gold manifest records must contain metadata only",
                )

    def test_runtime_directories_need_not_be_committed(self) -> None:
        """Runs/scoring/releases are created by their owning writers."""

        for campaign_id in (
            "hvs-extraction-v1",
            "hvs-extraction-v2",
            "hvs-extraction-v3",
            "hvs-extraction-v4",
            "hvs-extraction-v5",
        ):
            root = BENCHMARK_DIR / "campaigns" / campaign_id
            for name in ("runs", "scoring", "releases"):
                path = root / name
                with self.subTest(path=path.relative_to(BENCHMARK_DIR)):
                    if campaign_id == "hvs-extraction-v5" and name == "runs":
                        self.assertTrue((path / ".gitkeep").exists())
                    else:
                        self.assertFalse((path / ".gitkeep").exists())


class GoldAbsenceTest(unittest.TestCase):
    """The workspace must hold no gold content in any form."""

    def test_gold_directory_is_absent(self) -> None:
        self.assertFalse(
            (BENCHMARK_DIR / "gold").exists(),
            "benchmark/gold must not exist; gold lives in the external "
            "private repository (STELLA_GOLD_DIR)",
        )

    def test_no_gold_annotation_artifacts_under_benchmark(self) -> None:
        hits = [
            path.relative_to(ROOT).as_posix()
            for pattern in GOLD_ARTIFACT_PATTERNS
            for path in BENCHMARK_DIR.rglob(pattern)
        ]
        self.assertEqual(
            hits, [], f"gold annotation artifacts found in workspace: {hits}"
        )

    def test_no_report_html_in_workspace(self) -> None:
        # Report/comparison pages embed gold values; they are generated into
        # the private gold repository, never committed here.
        hits = [
            path.relative_to(ROOT).as_posix()
            for path in BENCHMARK_DIR.rglob("*.html")
        ]
        self.assertEqual(hits, [], f"report HTML found in workspace: {hits}")

    def test_public_gold_assignments_are_value_free(self) -> None:
        for path in BENCHMARK_DIR.glob(
            "campaigns/*/manifest/gold_assignments/*.json"
        ):
            with self.subTest(path=path.relative_to(ROOT)):
                profile = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    set(profile),
                    {"schema", "assignment_id", "campaign", "created_at", "papers"},
                )
                self.assertTrue(
                    all(
                        set(paper)
                        == {"arxiv_id", "primary_annotator", "additional_annotators"}
                        for paper in profile["papers"]
                    )
                )
                rendered = path.read_text(encoding="utf-8")
                for forbidden in ("candidates", "notes", "evidence", "values"):
                    self.assertNotIn(forbidden, rendered)


class GoldIsolationTest(unittest.TestCase):
    def test_only_whitelisted_files_mention_gold_directory(self) -> None:
        for path in iter_pipeline_python_files():
            relative = path.relative_to(ROOT).as_posix()
            if relative in GOLD_ACCESS_WHITELIST:
                continue
            with self.subTest(file=relative):
                content = path.read_text(encoding="utf-8")
                self.assertNotIn(
                    GOLD_TOKEN,
                    content,
                    f"{relative} references {GOLD_TOKEN}; only the human "
                    "annotation workflow may touch gold (see AGENTS.md).",
                )

    def test_whitelist_entries_exist_once_created(self) -> None:
        # Whitelisted paths may not exist yet while a phase is in flight,
        # but stale entries must not linger after renames.
        for relative in sorted(GOLD_ACCESS_WHITELIST):
            path = ROOT / relative
            if not path.exists():
                continue
            with self.subTest(file=relative):
                self.assertTrue(path.is_file())

    def test_batch_driver_does_not_read_gold(self) -> None:
        for relative in (
            "scripts/run_catalog_review_batch.py",
            "src/stella/lit/llm_batch.py",
        ):
            with self.subTest(file=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("gold", content.lower())

    def test_extraction_pipeline_does_not_mention_gold_env(self) -> None:
        # The benchmark extraction pipeline must not even know where the
        # gold store lives.
        for relative in (
            "src/stella/hvs_extraction/run.py",
            "src/stella/lit/extraction/prepare.py",
            "src/stella/lit/extraction/run.py",
            "src/stella/hvs_extraction/roster_stage.py",
            "src/stella/hvs_extraction/field_stage.py",
            "src/stella/hvs_extraction/network_debug.py",
            "scripts/run_hvs_candidate_extraction.py",
            "scripts/run_coding_agent_baseline.py",
            "scripts/run_hvs_extraction_supplement.py",
            "scripts/run_hvs_network_debug.py",
        ):
            with self.subTest(file=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("STELLA_GOLD_DIR", content)
                self.assertNotIn("gold", content.lower())

        baseline = (
            ROOT / "src/stella/benchmark/coding_agent_baseline.py"
        ).read_text(encoding="utf-8")
        self.assertIn('env.pop("STELLA_GOLD_DIR", None)', baseline)

    def test_gold_form_does_not_reference_ai_outputs(self) -> None:
        for relative in (
            "scripts/serve_gold_annotation.py",
            "src/stella/benchmark/gold_form.py",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8")
            for token in AI_OUTPUT_TOKENS:
                with self.subTest(file=relative, token=token):
                    self.assertNotIn(token, content)

    def test_private_gold_cli_paths_are_guarded_at_runtime(self) -> None:
        for relative in (
            "scripts/serve_gold_annotation.py",
            "scripts/serve_hvs_contribution_gold_annotation.py",
            "scripts/update_gold_manifest.py",
            "scripts/build_gold_selection.py",
            "scripts/list_gold_annotation_queue.py",
            "scripts/upgrade_gold_annotation.py",
            "scripts/upgrade_hvs_contribution_gold_annotation.py",
            "scripts/migrate_private_gold_schema.py",
            "scripts/score_benchmark_run.py",
        ):
            with self.subTest(file=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("require_external_path", content)


class AgentsRulesTest(unittest.TestCase):
    def test_benchmark_agents_md_documents_gold_isolation_rules(self) -> None:
        root_rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        content = (ROOT / "benchmark" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("benchmark/AGENTS.md", root_rules)
        self.assertIn("## Gold and AI isolation", content)
        self.assertIn("STELLA_GOLD_DIR", content)
        self.assertIn("never enter this workspace as files, copies, or", content)
        self.assertIn("AI extraction may not read gold", content)
        self.assertIn("sole AI-assisted gold", content)
        self.assertIn("Final scientific evidence remains PDF locators", content)
        self.assertIn("Neither context may read production extraction", content)
