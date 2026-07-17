from __future__ import annotations

import copy
import io
import json
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from stella.benchmark.context_pack import (
    PackedContext,
    numbered_lines,
    pack_paper_context,
)
from stella.benchmark.extraction_run import (
    batch_structure_errors,
    build_system_prompt,
    enforce_pipeline_fields,
    find_cjk_strings,
    repair_feedback,
    route_errors,
    run_paper,
    scaffold_structure_errors,
    split_batches,
    write_harness_error_report,
)
from stella.benchmark.mechanical_normalization import (
    normalize_mechanical_representation,
)
from stella.benchmark.extraction_review import DEFAULT_REVIEWER_MODEL
from stella.lit.llm_batch import LLMTransportError, chat_completion_raw
from stella.lit.extraction_rules import render_rule_profile


ROOT = Path(__file__).resolve().parents[1]


class HarnessErrorReportTest(unittest.TestCase):
    def test_unexpected_paper_failure_is_persisted_as_harness_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            trace = mock.Mock()

            result = write_harness_error_report(
                run_dir=run_dir,
                arxiv_id="1902.05061",
                error=ValueError("broken roster boundary"),
                trace=trace,
            )

            report = json.loads(
                (run_dir / "1902.05061" / "report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result.status, "harness_error")
            self.assertEqual(report["status"], "harness_error")
            self.assertEqual(report["error"], "ValueError: broken roster boundary")
            self.assertEqual(report["stage_log"][0]["stage"], "harness")
            trace.emit.assert_called_once()


class WorkflowMechanicalNormalizationTest(unittest.TestCase):
    """Task 4: normalization is shared, pure, and representation-only."""

    @staticmethod
    def document() -> dict:
        return {
            "candidates": [
                {
                    "identifiers": {"record_id": "9901.00001:cand-001"},
                    "inclusion_assessment": {
                        "galactic_bound_claim": "unbound",
                        "inclusion_basis": "explicit_unbound_text",
                    },
                    "core": {
                        "observed_phase_space": {
                            "ra": {
                                "value": "16:03:04.06",
                                "coordinate_format": "sexagesimal_hms",
                            },
                            "dec": {
                                "value": "- 66:13:26.9",
                                "coordinate_format": "sexagesimal_dms",
                            },
                            "radial_velocity": {
                                "value": "612.3",
                                "unit": "km/s",
                                "limit_kind": "lower_limit",
                            },
                        },
                        "bound_assessment": {
                            "unbound_probability": {"value": "0.9", "unit": ""}
                        },
                    },
                    "candidate_origin": {
                        "citation": {
                            "bibkey": "wrong-key",
                            "citation_context_refs": [
                                {
                                    "kind": "text",
                                    "path": "literature/paper/arxiv_source/paper.tex",
                                    "start_line": 2,
                                    "end_line": 2,
                                }
                            ],
                            "bibliography_refs": [
                                {
                                    "kind": "text",
                                    "path": "literature/paper/arxiv_source/paper.bbl",
                                    "start_line": 4,
                                    "end_line": 4,
                                }
                            ],
                        }
                    },
                },
                {
                    "identifiers": {"record_id": "9901.00001:cand-002"},
                    "inclusion_assessment": {
                        "galactic_bound_claim": "bound",
                        "inclusion_basis": "explicit_candidate_text",
                    },
                    "core": {"observed_phase_space": {}},
                },
            ]
        }

    @staticmethod
    def snapshot(document: dict) -> dict:
        """Candidate count, record ids, scientific values, units, limit
        kinds, and inclusion decisions — the payload normalization must
        never touch (coordinate punctuation is representation, so the
        snapshot stores parsed colon spellings only for non-coordinate
        fields)."""

        records = []
        for candidate in document["candidates"]:
            observed = candidate.get("core", {}).get("observed_phase_space", {})
            quantities = {
                name: {
                    key: quantity.get(key)
                    for key in ("value", "unit", "limit_kind")
                }
                for name, quantity in observed.items()
                if isinstance(quantity, dict) and name not in ("ra", "dec")
            }
            records.append(
                {
                    "record_id": candidate.get("identifiers", {}).get("record_id"),
                    "inclusion": candidate.get("inclusion_assessment", {}),
                    "quantities": quantities,
                }
            )
        return {"count": len(document["candidates"]), "records": records}

    def test_only_coordinate_punctuation_is_normalized(self) -> None:
        document = self.document()
        citation_before = copy.deepcopy(
            document["candidates"][0]["candidate_origin"]["citation"]
        )

        changes = normalize_mechanical_representation(document)

        candidate = document["candidates"][0]
        observed = candidate["core"]["observed_phase_space"]
        self.assertEqual(observed["ra"]["value"], "16h03m04.06s")
        self.assertEqual(observed["dec"]["value"], "-66d13m26.9s")
        self.assertEqual(
            sorted(changes),
            ["candidates[0].dec.value", "candidates[0].ra.value"],
        )
        # Semantic bibliography selection is removed: a wrong bibkey and its
        # locator refs stay exactly as the model submitted them; the failure
        # is validator/reviewer work, not silent code repair.
        self.assertEqual(candidate["candidate_origin"]["citation"], citation_before)

    def test_normalization_is_idempotent(self) -> None:
        document = self.document()
        first = normalize_mechanical_representation(document)
        after_first = copy.deepcopy(document)
        second = normalize_mechanical_representation(document)
        self.assertTrue(first)
        self.assertEqual(second, [])
        self.assertEqual(document, after_first)

    def test_scientific_payload_is_unchanged(self) -> None:
        document = self.document()
        before = self.snapshot(document)
        normalize_mechanical_representation(document)
        self.assertEqual(self.snapshot(document), before)

    def test_methods_b_and_c_share_the_identical_normalizer(self) -> None:
        from stella.benchmark import agentic_run, extraction_run, mechanical_normalization

        self.assertIs(
            extraction_run.normalize_mechanical_representation,
            mechanical_normalization.normalize_mechanical_representation,
        )
        self.assertIs(
            agentic_run.normalize_mechanical_representation,
            mechanical_normalization.normalize_mechanical_representation,
        )
        for apply in (
            extraction_run.normalize_mechanical_representation,
            agentic_run.normalize_mechanical_representation,
        ):
            document = self.document()
            changes = apply(document)
            self.assertEqual(
                sorted(changes),
                ["candidates[0].dec.value", "candidates[0].ra.value"],
            )
            self.assertEqual(
                document["candidates"][0]["core"]["observed_phase_space"]["ra"]["value"],
                "16h03m04.06s",
            )


def make_skill_files(workspace: Path) -> None:
    skill_dir = workspace / "skills" / "hvs-candidates-extraction"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Skill\nExtract.", encoding="utf-8")
    (skill_dir / "references" / "schema.md").write_text("# Schema", encoding="utf-8")
    (skill_dir / "references" / "coordinate_frames.md").write_text(
        "# Frames", encoding="utf-8"
    )
    shutil.copytree(
        ROOT / "skills" / "hvs-candidates-extraction" / "rules",
        skill_dir / "rules",
    )


def make_paper_dir(workspace: Path, arxiv_id: str = "9901.00001") -> Path:
    paper_dir = workspace / "literature" / arxiv_id
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "catalog_tables").mkdir()
    (paper_dir / "audit.json").write_text(
        json.dumps(
            {
                "arxiv_id": arxiv_id,
                "title": "A synthetic paper",
                "month": "2099-01",
                "source_note_json": "",
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "catalog_review.json").write_text(
        json.dumps({"schema_version": "x", "tables": []}), encoding="utf-8"
    )
    ecsv_rel = f"literature/{arxiv_id}/catalog_tables/table-a.ecsv"
    (paper_dir / "catalog_extraction.json").write_text(
        json.dumps(
            {
                "schema_version": "x",
                "tables": [{"status": "success", "ecsv_path": ecsv_rel}],
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "catalog_tables" / "table-a.ecsv").write_text(
        "# %ECSV 1.0\nname,rv\nStarA,612.3\n", encoding="utf-8"
    )
    (paper_dir / "arxiv_source" / "paper.tex").write_text(
        "\\title{Synthetic}\nStarA has rv 612.3 km/s.\n", encoding="utf-8"
    )
    return paper_dir


class ContextPackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        make_paper_dir(self.workspace)
        self.ecsv = ["literature/9901.00001/catalog_tables/table-a.ecsv"]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def pack(self) -> PackedContext:
        return pack_paper_context(self.workspace, "9901.00001", self.ecsv)

    def test_pack_is_deterministic(self) -> None:
        self.assertEqual(self.pack().sha256, self.pack().sha256)

    def test_pack_contains_numbered_tex_and_ecsv(self) -> None:
        text = self.pack().text
        self.assertIn("1|\\title{Synthetic}", text)
        self.assertIn("3|StarA,612.3", text)
        self.assertIn("BEGIN literature/9901.00001/catalog_review.json", text)

    def test_file_order_and_kinds(self) -> None:
        kinds = [item.kind for item in self.pack().files]
        self.assertEqual(
            kinds,
            ["catalog_review", "catalog_extraction", "ecsv_table", "paper_text"],
        )

    def test_missing_declared_ecsv_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            pack_paper_context(
                self.workspace, "9901.00001", ["literature/9901.00001/nope.ecsv"]
            )

    def test_oversize_pack_refuses_truncation(self) -> None:
        with self.assertRaises(ValueError):
            pack_paper_context(
                self.workspace, "9901.00001", self.ecsv, max_chars=10
            )

    def test_numbered_lines_are_physical(self) -> None:
        self.assertEqual(numbered_lines("a\nb\n"), "1|a\n2|b")


class BibFilterTest(unittest.TestCase):
    BIB = (
        "% master library\n"
        "@string{apj = {ApJ}}\n"
        "@ARTICLE{cited2020,\n  author = {A},\n  journal = apj,\n}\n"
        "@ARTICLE{uncited2019,\n  author = {B},\n}\n"
        "@ARTICLE{also_cited,\n  author = {C},\n}\n"
    )

    def test_cited_keys_parsing_handles_variants(self) -> None:
        from stella.benchmark.context_pack import extract_cited_keys

        keys, nocite = extract_cited_keys(
            ["We \\citep[e.g.][]{cited2020, also_cited} stars."]
        )
        self.assertEqual(keys, {"cited2020", "also_cited"})
        self.assertFalse(nocite)
        _, nocite_all = extract_cited_keys(["\\nocite{*}"])
        self.assertTrue(nocite_all)

    def test_filter_keeps_cited_and_string_blocks_with_real_lines(self) -> None:
        from stella.benchmark.context_pack import filter_bib_to_cited

        body, kept, total = filter_bib_to_cited(
            self.BIB, {"cited2020", "also_cited"}
        )
        self.assertEqual(total, 12)
        self.assertIn("1|% master library", body)          # header kept
        self.assertIn("2|@string{apj = {ApJ}}", body)      # @string kept
        self.assertIn("3|@ARTICLE{cited2020,", body)
        self.assertIn("10|@ARTICLE{also_cited,", body)     # physical number
        self.assertNotIn("uncited2019", body)
        self.assertIn("omitted: uncited", body)
        self.assertEqual(kept, 9)

    def test_pack_filters_bib_but_keeps_bbl_whole(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            paper_dir = make_paper_dir(workspace)
            source = paper_dir / "arxiv_source"
            (source / "library.bib").write_text(self.BIB, encoding="utf-8")
            (source / "paper.bbl").write_text(
                "\\bibitem{x} Everything stays.\n", encoding="utf-8"
            )
            (source / "paper.tex").write_text(
                "StarA \\cite{cited2020}.\n", encoding="utf-8"
            )
            context = pack_paper_context(
                workspace,
                "9901.00001",
                ["literature/9901.00001/catalog_tables/table-a.ecsv"],
            )
        by_path = {item.path.split("/")[-1]: item for item in context.files}
        self.assertEqual(by_path["library.bib"].kind, "bibliography_filtered")
        self.assertEqual(by_path["library.bib"].original_lines, 12)
        self.assertEqual(by_path["paper.bbl"].kind, "paper_text")
        self.assertIn("Everything stays.", context.text)
        self.assertNotIn("uncited2019", context.text)


class CjkScanTest(unittest.TestCase):
    def test_finds_cjk_paths_and_skips_raw_value(self) -> None:
        document = {
            "extraction": {"summary": "这是中文摘要"},
            "candidates": [
                {
                    "core": {
                        "raw_value": "测试",  # exempt key
                        "description": "fine english",
                    }
                }
            ],
        }
        findings = find_cjk_strings(document)
        self.assertEqual(findings, ["$.extraction.summary"])


class EnforceFieldsTest(unittest.TestCase):
    def test_model_cannot_control_provenance(self) -> None:
        skeleton = {
            "schema": {"name": "literature_hvs_candidates", "version": 2},
            "generated_at": "2099-01-01T00:00:00",
            "paper": {"arxiv_id": "9901.00001"},
            "inputs": {"ecsv_paths": []},
        }
        forged = {
            "schema_version": "evil",
            "generated_at": "1990",
            "paper": {"arxiv_id": "fake"},
            "inputs": {"ecsv_paths": ["fake"]},
            "extraction": {
                "status": "no_candidates",
                "provenance": {"model_id": "model-claims-to-be-gpt9"},
            },
        }
        document = enforce_pipeline_fields(
            forged,
            skeleton,
            served_model_id="deepseek-v4-pro",
            requested_model="deepseek-v4-pro",
            prompt_version="abc1234",
            request_parameters={"temperature": 0},
            extracted_at="2099-01-02T00:00:00",
            pipeline_name="stella-agentic-extraction",
        )
        self.assertEqual(document["schema"], skeleton["schema"])
        self.assertEqual(document["paper"], skeleton["paper"])
        self.assertEqual(document["inputs"], skeleton["inputs"])
        provenance = document["extraction"]["provenance"]
        self.assertEqual(provenance["model_id"], "deepseek-v4-pro")
        self.assertEqual(provenance["git_commit"], "abc1234")
        self.assertEqual(document["extraction"]["extractor"], "stella-agentic-extraction")

    def test_feedback_truncates_long_error_lists(self) -> None:
        text = repair_feedback([f"e{i}" for i in range(200)], [], "scaffold")
        self.assertIn("200 total, showing 80", text)
        self.assertIn("NEVER renumber", text)


class StagedStructureTest(unittest.TestCase):
    def stub(self, n: int) -> dict:
        return {
            "identifiers": {
                "record_id": f"9901.00001:cand-{n:03d}",
                "paper_candidate_id": f"Star{n}",
                "gaia_source_id": "",
                "all": [{"value": f"Star{n}", "source_refs": []}],
            }
        }

    def test_valid_scaffold_passes(self) -> None:
        document = {
            "extraction": {"status": "candidates_found"},
            "method_chain": [],
            "candidates": [self.stub(1), self.stub(2)],
            "candidate_groups_considered": [],
        }
        self.assertEqual(scaffold_structure_errors(document, "9901.00001"), [])

    def test_scaffold_rejects_full_candidates_and_bad_ids(self) -> None:
        fat = self.stub(1)
        fat["core"] = {}
        document = {
            "extraction": {"status": "candidates_found"},
            "method_chain": [],
            "candidates": [fat, {"identifiers": {"record_id": "wrong"}}],
            "candidate_groups_considered": [],
        }
        errors = scaffold_structure_errors(document, "9901.00001")
        self.assertTrue(any("ONLY" in error for error in errors))
        self.assertTrue(any("cand-001" in error for error in errors))

    def test_scaffold_status_roster_consistency(self) -> None:
        document = {
            "extraction": {"status": "no_candidates"},
            "method_chain": [],
            "candidates": [self.stub(1)],
            "candidate_groups_considered": [],
        }
        errors = scaffold_structure_errors(document, "9901.00001")
        self.assertTrue(any("conflicts" in error for error in errors))

    def test_batch_checks_count_and_ids(self) -> None:
        stubs = [self.stub(1), self.stub(2)]
        good = {
            "candidates": [
                {"identifiers": dict(stub["identifiers"]), "core": {}}
                for stub in stubs
            ]
        }
        self.assertEqual(batch_structure_errors(good, stubs), [])
        short = {"candidates": good["candidates"][:1]}
        self.assertTrue(batch_structure_errors(short, stubs))
        swapped = {"candidates": list(reversed(good["candidates"]))}
        self.assertTrue(batch_structure_errors(swapped, stubs))

    def test_batch_rejects_identifier_rename_of_a_sealed_stub(self) -> None:
        # Post-seal membership mutation covers renames: only record_id was
        # checked historically, so a renamed paper_candidate_id slipped past.
        stubs = [self.stub(1)]
        renamed = {
            "candidates": [
                {
                    "identifiers": {
                        **self.stub(1)["identifiers"],
                        "paper_candidate_id": "RenamedStar",
                    }
                }
            ]
        }
        errors = batch_structure_errors(renamed, stubs)
        self.assertTrue(any("exactly match" in error for error in errors))
        aliased = {
            "candidates": [
                {
                    "identifiers": {
                        **self.stub(1)["identifiers"],
                        "all": [{"value": "OtherAlias", "source_refs": []}],
                    }
                }
            ]
        }
        self.assertTrue(batch_structure_errors(aliased, stubs))

    def test_split_batches(self) -> None:
        roster = [self.stub(i) for i in range(1, 11)]
        batches = split_batches(roster, 4)
        self.assertEqual([len(b) for b in batches], [4, 4, 2])

    def test_route_errors_separates_candidates_from_scaffold(self) -> None:
        scaffold_errors, candidate_errors = route_errors(
            [
                "$.candidates[3].core.x: bad value",
                "$.candidates[11].core.y: bad unit",
                "$.candidates: method step 'step-15' is used as direct producer",
                "$.method_chain[2]: summary required",
            ]
        )
        self.assertEqual(sorted(candidate_errors), [3, 11])
        self.assertEqual(len(scaffold_errors), 2)

    def test_route_errors_handles_dotted_pydantic_paths(self) -> None:
        # pydantic emits dotted paths; they must reach the owning batch,
        # not the scaffold (pilot-03: 451 such errors looped on scaffold).
        scaffold_errors, candidate_errors = route_errors(
            [
                "$.candidates.8.astrophysical_origin: Input should be a "
                "valid dictionary or instance of AstrophysicalOrigin",
                "$.candidates.18.inclusion_assessment.confidence_reason: "
                "Field required",
                "$.candidates.0.core.observed_phase_space.distance"
                ".source_refs.0.TextSourceRef.raw_value: Extra inputs are "
                "not permitted",
                "$.method_chain.3.id: String should match pattern",
            ]
        )
        self.assertEqual(sorted(candidate_errors), [0, 8, 18])
        self.assertEqual(len(scaffold_errors), 1)

    def test_scaffold_method_chain_guards(self) -> None:
        document = {
            "extraction": {"status": "candidates_found"},
            "method_chain": [
                {"id": "step-01", "step_type": "input_catalog"},
                {"id": "step-03b", "step_type": "velocity_calculation"},
                {"id": "step-03", "step_type": "velocity_calculation"},
                {"id": "step-02", "step_type": "velocity_calculation"},
                {
                    "id": "step-04",
                    "step_type": "orbit_integration",
                    "depends_on": ["step-09"],
                },
            ],
            "candidates": [self.stub(1)],
            "candidate_groups_considered": [],
        }
        errors = scaffold_structure_errors(document, "9901.00001")
        self.assertTrue(any("step-03b" in error for error in errors))
        self.assertTrue(any("ascending" in error for error in errors))
        self.assertTrue(
            any("'step-09'" in error and "earlier" in error for error in errors)
        )

    def test_scaffold_rejects_source_missing(self) -> None:
        # The pipeline packed the sources itself, so a model claiming
        # source_missing is factually wrong about its own input
        # (pilot-04/05: two papers dodged extraction this way).
        document = {
            "extraction": {"status": "source_missing"},
            "method_chain": [],
            "candidates": [],
            "candidate_groups_considered": [],
        }
        errors = scaffold_structure_errors(document, "9901.00001")
        self.assertTrue(any("source_missing" in error for error in errors))

    def test_method_chain_order_hint_is_stage_aware(self) -> None:
        document = {
            "extraction": {"status": "candidates_found"},
            "method_chain": [
                {"id": "step-02", "step_type": "input_catalog"},
                {"id": "step-01", "step_type": "sample_selection"},
            ],
            "candidates": [self.stub(1)],
            "candidate_groups_considered": [],
        }
        initial = scaffold_structure_errors(document, "9901.00001")
        self.assertTrue(any("renumber the ENTIRE chain" in e for e in initial))
        during_repair = scaffold_structure_errors(
            document, "9901.00001", repair=True
        )
        self.assertTrue(any("never renumber" in e for e in during_repair))

    def test_batch_rejects_unknown_method_refs(self) -> None:
        stubs = [self.stub(1)]
        record = {
            "identifiers": dict(self.stub(1)["identifiers"]),
            "core": {
                "observed_phase_space": {
                    "radial_velocity": {"method_refs": ["step-03b"]}
                }
            },
        }
        errors = batch_structure_errors(
            {"candidates": [record]}, stubs, {"step-01", "step-02"}
        )
        self.assertTrue(any("step-03b" in error for error in errors))
        ok = batch_structure_errors(
            {"candidates": [record]}, stubs, {"step-03b"}
        )
        self.assertEqual(ok, [])


class FakeValidatorModule:
    """Stub of the frozen validator with a scripted error sequence."""

    def __init__(self, error_batches: list[list[str]]) -> None:
        self.error_batches = error_batches
        self.calls = 0

    def validate_hvs_candidates_report(self, payload, *, workspace, require_complete):
        errors = (
            self.error_batches[self.calls]
            if self.calls < len(self.error_batches)
            else []
        )
        self.calls += 1
        return type("Report", (), {"errors": errors, "warnings": ["w"]})()


def fake_response(document: dict, model: str = "deepseek-v4-pro") -> dict:
    return {
        "model": model,
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "completion_tokens_details": {"reasoning_tokens": 20},
        },
        "choices": [{"message": {"content": json.dumps(document)}}],
    }


def fake_review_response(challenges: list[dict] | None = None) -> dict:
    return fake_response(
        {
            "review": {
                "challenges": list(challenges or []),
                "summary": "review complete",
            }
        },
        model=DEFAULT_REVIEWER_MODEL,
    )


def fake_roster_review_response(
    decision: str = "accept",
    revised_roster: dict | None = None,
    challenges: list[dict] | None = None,
) -> dict:
    roster_review: dict = {
        "decision": decision,
        "challenges": list(challenges or []),
        "summary": "roster review complete",
    }
    if revised_roster is not None:
        roster_review["revised_roster"] = revised_roster
    return fake_response({"roster_review": roster_review}, model=DEFAULT_REVIEWER_MODEL)


def default_reviewer_transport(messages: list[dict], **kwargs) -> dict:
    """Route roster-review and final-review requests to their fake replies."""

    user = messages[-1].get("content", "") if messages else ""
    if "===== ROSTER UNDER REVIEW =====" in user:
        return fake_roster_review_response()
    return fake_review_response()


class RunPaperTest(unittest.TestCase):
    ARXIV = "9901.00001"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        make_paper_dir(self.workspace)
        make_skill_files(self.workspace)
        self.run_dir = self.workspace / "run"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def stub(self, n: int) -> dict:
        return {
            "identifiers": {
                "record_id": f"{self.ARXIV}:cand-{n:03d}",
                "paper_candidate_id": f"Star{n}",
                "gaia_source_id": "",
                "all": [{"value": f"Star{n}", "source_refs": []}],
            }
        }

    def scaffold_doc(self, n: int, summary: str = "fine") -> dict:
        status = "candidates_found" if n else "no_candidates"
        return {
            "extraction": {"status": status, "summary": summary},
            "method_chain": [{"id": "step-01", "step_type": "input_catalog"}],
            "candidates": [self.stub(i) for i in range(1, n + 1)],
            "candidate_groups_considered": [],
        }

    def batch_reply(self, numbers: list[int]) -> dict:
        return {
            "candidates": [
                {"identifiers": self.stub(n)["identifiers"],
                 "filled": True}
                for n in numbers
            ]
        }

    def roster_stub(self, n: int) -> dict:
        identifiers = self.stub(n)["identifiers"]
        identifiers["all"] = [
            {
                "value": f"Star{n}",
                "source_refs": [
                    {
                        "kind": "text",
                        "path": f"literature/{self.ARXIV}/arxiv_source/paper.tex",
                        "start_line": 2,
                        "end_line": 2,
                        "context": f"Star{n} has rv 612.3 km/s.",
                    }
                ],
            }
        ]
        return {
            "identifiers": identifiers,
            "inclusion_anchor": {
                "summary": f"Star{n} is proposed as unbound.",
                "source_refs": [
                    {
                        "kind": "text",
                        "path": f"literature/{self.ARXIV}/arxiv_source/paper.tex",
                        "start_line": 2,
                        "end_line": 2,
                        "context": f"Star{n} has rv 612.3 km/s.",
                    }
                ],
            },
        }

    def roster_doc(self, numbers: list[int]) -> dict:
        status = "candidates_found" if numbers else "no_candidates"
        return {
            "extraction": {"status": status, "summary": "roster"},
            "candidates": [self.roster_stub(n) for n in numbers],
            "candidate_groups_considered": [],
        }

    def frozen_scaffold_doc(self, numbers: list[int]) -> dict:
        status = "candidates_found" if numbers else "no_candidates"
        return {
            "extraction": {"status": status, "summary": "fine"},
            "method_chain": [{"id": "step-01", "step_type": "input_catalog"}],
            "candidates": [
                {"identifiers": self.roster_stub(n)["identifiers"]}
                for n in numbers
            ],
            "candidate_groups_considered": [],
        }

    def frozen_batch_reply(self, numbers: list[int]) -> dict:
        return {
            "candidates": [
                {
                    "identifiers": self.roster_stub(n)["identifiers"],
                    "filled": True,
                }
                for n in numbers
            ]
        }

    def run_one(
        self,
        validator,
        transport,
        request_extra=None,
        reviewer_transport=None,
        max_repair_rounds=2,
        task_surface="full",
        roster_cache_root=None,
    ) -> object:
        self.reviewer_transport = reviewer_transport or mock.Mock(
            side_effect=default_reviewer_transport
        )
        return run_paper(
            workspace=self.workspace,
            arxiv_id=self.ARXIV,
            run_dir=self.run_dir,
            api_key="k",
            base_url="https://example.invalid/v1",
            model="deepseek-v4-pro",
            reviewer_model=DEFAULT_REVIEWER_MODEL,
            prompt_version="abc1234",
            batch_size=2,
            max_repair_rounds=max_repair_rounds,
            request_extra=request_extra,
            reviewer_request_extra={"provider": {"order": ["bigmodel"]}},
            task_surface=task_surface,
            validator_module=validator,
            transport=transport,
            reviewer_transport=self.reviewer_transport,
            roster_cache_root=roster_cache_root,
        )

    def test_surface_neutral_roster_is_shared_across_full_and_core_runs(self) -> None:
        cache_root = self.workspace / "shared-rosters"
        roster = {
            "extraction": {"status": "no_candidates", "summary": "No candidates."},
            "candidates": [],
            "candidate_groups_considered": [],
        }
        full_transport = mock.Mock(
            side_effect=[
                fake_response(roster),
                fake_response(self.scaffold_doc(0)),
            ]
        )
        full = self.run_one(
            FakeValidatorModule([[]]),
            full_transport,
            task_surface="full",
            roster_cache_root=cache_root,
        )
        full_bundle = json.loads(
            (self.run_dir / self.ARXIV / "roster_bundle.json").read_text()
        )

        self.run_dir = self.workspace / "run-core"
        shutil.copy2(
            ROOT
            / "skills"
            / "hvs-candidates-extraction"
            / "references"
            / "schema-core-provenance.md",
            self.workspace
            / "skills"
            / "hvs-candidates-extraction"
            / "references"
            / "schema-core-provenance.md",
        )
        core_transport = mock.Mock(side_effect=[fake_response(self.scaffold_doc(0))])
        core = self.run_one(
            FakeValidatorModule([[]]),
            core_transport,
            task_surface="core_prov",
            roster_cache_root=cache_root,
        )
        core_bundle = json.loads(
            (self.run_dir / self.ARXIV / "roster_bundle.json").read_text()
        )

        self.assertEqual(full.status, "ok")
        self.assertEqual(core.status, "ok")
        self.assertFalse(full.roster_cache_hit)
        self.assertTrue(core.roster_cache_hit)
        self.assertEqual(full_bundle["bundle_id"], core_bundle["bundle_id"])
        self.assertEqual(full_bundle["review"]["status"], "accepted")
        self.assertEqual(full_bundle["review"]["provenance"]["model"], "glm-5.2")
        self.assertEqual(full_transport.call_count, 2)
        self.assertEqual(core_transport.call_count, 1)
        self.assertEqual(full.downstream_usage["total_tokens"], 300)
        self.assertEqual(core.downstream_usage["total_tokens"], 300)

    def test_roster_reviewer_removes_overincluded_member_before_sealing(self) -> None:
        # Plan Steps 1+2: the producer over-includes Star2; the independent
        # roster reviewer sees every inclusion_anchor and removes Star2
        # before the bundle hash is computed.
        cache_root = self.workspace / "shared-rosters"
        roster_review_requests: list[list[dict]] = []

        def reviewer(messages, **kwargs):
            user = messages[-1].get("content", "")
            if "===== ROSTER UNDER REVIEW =====" in user:
                roster_review_requests.append(messages)
                return fake_roster_review_response(
                    "revise",
                    revised_roster=self.roster_doc([1]),
                    challenges=[
                        {"record_id": f"{self.ARXIV}:cand-002", "issue": "cite-in-passing only"}
                    ],
                )
            return fake_review_response()

        transport = mock.Mock(
            side_effect=[
                fake_response(self.roster_doc([1, 2])),  # over-included roster
                fake_response(self.frozen_scaffold_doc([1])),
                fake_response(self.frozen_batch_reply([1])),
            ]
        )
        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            reviewer_transport=reviewer,
            roster_cache_root=cache_root,
        )

        self.assertEqual(result.status, "ok")
        bundle = json.loads(
            (self.run_dir / self.ARXIV / "roster_bundle.json").read_text()
        )
        self.assertEqual(bundle["review"]["status"], "revised")
        self.assertEqual(len(bundle["candidates"]), 1)
        self.assertEqual(
            bundle["candidates"][0]["identifiers"]["paper_candidate_id"], "Star1"
        )
        self.assertEqual(bundle["review"]["provenance"]["model"], DEFAULT_REVIEWER_MODEL)
        # Step 2: the roster reviewer received each candidate's
        # inclusion_anchor, including its paper-text source references.
        self.assertEqual(len(roster_review_requests), 1)
        review_messages = roster_review_requests[0]
        review_request = review_messages[-1]["content"]
        self.assertIn('"inclusion_anchor"', review_request)
        self.assertIn("Star1 has rv 612.3 km/s.", review_request)
        self.assertIn("Star2 has rv 612.3 km/s.", review_request)
        # The only scientific rule source is the hvs_roster profile.
        self.assertIn(
            "===== ROSTER REVIEW RULE PROFILE: hvs_roster =====",
            review_messages[0]["content"],
        )
        # The sealed (revised) roster drives the final document.
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(len(final["candidates"]), 1)
        self.assertNotIn("inclusion_anchor", final["candidates"][0])

    def test_roster_reviewer_accept_path_and_reviewer_contract_in_key(self) -> None:
        cache_root = self.workspace / "shared-rosters"
        transport = mock.Mock(
            side_effect=[
                fake_response(self.roster_doc([1])),
                fake_response(self.frozen_scaffold_doc([1])),
                fake_response(self.frozen_batch_reply([1])),
            ]
        )
        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            roster_cache_root=cache_root,
        )

        self.assertEqual(result.status, "ok")
        bundle = json.loads(
            (self.run_dir / self.ARXIV / "roster_bundle.json").read_text()
        )
        self.assertEqual(bundle["review"]["status"], "accepted")
        components = bundle["key_components"]
        self.assertEqual(components["reviewer_model"], DEFAULT_REVIEWER_MODEL)
        self.assertEqual(len(components["reviewer_prompt_sha256"]), 64)
        self.assertEqual(len(components["reviewer_rule_sha256"]), 64)
        self.assertEqual(components["reviewer_rule_sha256"], components["rule_sha256"])

    def test_run_applies_shared_mechanical_normalization_once(self) -> None:
        # Task 4: coordinate punctuation is canonicalized and logged once;
        # citation selection is left exactly as the model submitted it.
        cache_root = self.workspace / "shared-rosters"
        candidate = {
            "identifiers": self.roster_stub(1)["identifiers"],
            "filled": True,
            "core": {
                "observed_phase_space": {
                    "ra": {"value": "16:03:04.06", "coordinate_format": "sexagesimal_hms"},
                    "dec": {"value": "-66:13:26.9", "coordinate_format": "sexagesimal_dms"},
                }
            },
            "candidate_origin": {
                "citation": {"bibkey": "model-chosen-key", "bibliography_refs": []}
            },
        }
        transport = mock.Mock(
            side_effect=[
                fake_response(self.roster_doc([1])),
                fake_response(self.frozen_scaffold_doc([1])),
                fake_response({"candidates": [candidate]}),
            ]
        )
        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            roster_cache_root=cache_root,
        )

        self.assertEqual(result.status, "ok")
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        observed = final["candidates"][0]["core"]["observed_phase_space"]
        self.assertEqual(observed["ra"]["value"], "16h03m04.06s")
        self.assertEqual(observed["dec"]["value"], "-66d13m26.9s")
        self.assertEqual(
            final["candidates"][0]["candidate_origin"]["citation"]["bibkey"],
            "model-chosen-key",
        )
        report = json.loads((self.run_dir / self.ARXIV / "report.json").read_text())
        normalization_stages = [
            entry
            for entry in report["stage_log"]
            if entry.get("stage") == "deterministic_normalization"
        ]
        self.assertEqual(len(normalization_stages), 1)
        self.assertEqual(
            normalization_stages[0]["changes"],
            ["candidates[0].ra.value", "candidates[0].dec.value"],
        )

    def test_sealed_anchors_reach_batch_fill_and_final_review(self) -> None:
        # Plan Step 6: sealed inclusion anchors stay visible downstream as
        # read-only evidence without becoming mutable candidate fields.
        cache_root = self.workspace / "shared-rosters"
        transport = mock.Mock(
            side_effect=[
                fake_response(self.roster_doc([1])),
                fake_response(self.frozen_scaffold_doc([1])),
                fake_response(self.frozen_batch_reply([1])),
            ]
        )
        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            roster_cache_root=cache_root,
        )

        self.assertEqual(result.status, "ok")
        batch_prompt = transport.call_args_list[2].kwargs["messages"][1]["content"]
        self.assertIn("SEALED ROSTER INCLUSION ANCHORS (read-only evidence)", batch_prompt)
        self.assertIn("Star1 has rv 612.3 km/s.", batch_prompt)
        final_review_prompt = self.reviewer_transport.call_args.kwargs["messages"][1][
            "content"
        ]
        self.assertIn("sealed_roster_inclusion_anchors", final_review_prompt)
        self.assertIn("Do not challenge membership", final_review_prompt)
        self.assertIn("Star1 has rv 612.3 km/s.", final_review_prompt)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(
            final["candidates"][0]["identifiers"]["record_id"],
            f"{self.ARXIV}:cand-001",
        )
        self.assertNotIn("inclusion_anchor", final["candidates"][0])

    def test_post_seal_membership_mutation_is_rejected(self) -> None:
        # Plan Step 7: the final reviewer is field/evidence-only; a scaffold
        # revision that tries to add a roster member is rejected.
        cache_root = self.workspace / "shared-rosters"

        def reviewer(messages, **kwargs):
            user = messages[-1].get("content", "")
            if "===== ROSTER UNDER REVIEW =====" in user:
                return fake_roster_review_response()
            return fake_review_response(
                [
                    {
                        "candidate_index": -1,
                        "field": "candidates",
                        "issue": "Star2 is missing from the roster",
                        "severity": "high",
                    }
                ]
            )

        transport = mock.Mock(
            side_effect=[
                fake_response(self.roster_doc([1])),
                fake_response(self.frozen_scaffold_doc([1])),
                fake_response(self.frozen_batch_reply([1])),
                fake_response(self.frozen_scaffold_doc([1, 2])),  # mutation attempt
                fake_response(self.frozen_scaffold_doc([1])),     # compliant retry
            ]
        )
        result = self.run_one(
            FakeValidatorModule([[], []]),
            transport,
            reviewer_transport=reviewer,
            roster_cache_root=cache_root,
        )

        self.assertEqual(result.status, "ok")
        rejected_feedback = transport.call_args_list[4].kwargs["messages"][-1][
            "content"
        ]
        self.assertIn("exactly preserve the frozen shared roster", rejected_feedback)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(len(final["candidates"]), 1)
        bundle = json.loads(
            (self.run_dir / self.ARXIV / "roster_bundle.json").read_text()
        )
        self.assertEqual(len(bundle["candidates"]), 1)

    def test_failed_roster_review_seals_nothing(self) -> None:
        cache_root = self.workspace / "shared-rosters"
        reviewer = mock.Mock(
            side_effect=[
                fake_response({"not_roster_review": call}, model=DEFAULT_REVIEWER_MODEL)
                for call in range(3)
            ]
        )
        transport = mock.Mock(side_effect=[fake_response(self.roster_doc([1]))])

        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            reviewer_transport=reviewer,
            roster_cache_root=cache_root,
        )

        self.assertEqual(result.status, "roster_failed")
        self.assertIn("roster_review_workflow_structured_output_failed", result.error)
        self.assertEqual(reviewer.call_count, 3)
        self.assertFalse((self.run_dir / self.ARXIV / "roster_bundle.json").exists())
        self.assertEqual(list(cache_root.glob("*/roster_bundle.json")), [])
        # A retry with the same contract reruns producer and reviewer.
        transport = mock.Mock(
            side_effect=[
                fake_response(self.roster_doc([1])),
                fake_response(self.frozen_scaffold_doc([1])),
                fake_response(self.frozen_batch_reply([1])),
            ]
        )
        self.run_dir = self.workspace / "run-retry"
        retry = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            roster_cache_root=cache_root,
        )
        self.assertEqual(retry.status, "ok")
        self.assertFalse(retry.roster_cache_hit)

    def test_no_candidates_paper_needs_one_call(self) -> None:
        transport = mock.Mock(
            side_effect=[fake_response(self.scaffold_doc(0))]
        )
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.scaffold_attempts, 1)
        self.assertEqual(result.batch_count, 0)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(result.review_calls, 1)
        self.assertEqual(self.reviewer_transport.call_count, 1)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(
            final["extraction"]["provenance"]["model_id"], "deepseek-v4-pro"
        )
        self.assertEqual(final["extraction"]["provenance"]["git_commit"], "abc1234")

    def test_staged_flow_merges_batches(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(3)),
                fake_response(self.batch_reply([1, 2])),
                fake_response(self.batch_reply([3])),
            ]
        )
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.batch_count, 2)
        self.assertEqual(result.batch_calls, 2)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(len(final["candidates"]), 3)
        self.assertTrue(all(c.get("filled") for c in final["candidates"]))
        attempts = self.run_dir / self.ARXIV / "attempts"
        self.assertTrue((attempts / "scaffold-call-01.response.json").is_file())
        self.assertTrue((attempts / "batch-001-call-01.response.json").is_file())
        self.assertTrue((attempts / "batch-002-call-01.response.json").is_file())
        self.assertTrue((attempts / "review-call-01.response.json").is_file())
        self.assertTrue((attempts / "review-call-01.request.json").is_file())

    def test_workflow_reviewer_receives_full_context_without_tools(self) -> None:
        transport = mock.Mock(side_effect=[fake_response(self.scaffold_doc(0))])

        result = self.run_one(FakeValidatorModule([[]]), transport)

        self.assertEqual(result.status, "ok")
        reviewer_call = self.reviewer_transport.call_args.kwargs
        self.assertNotIn("tools", reviewer_call["extra_body"])
        self.assertNotIn("tool_choice", reviewer_call["extra_body"])
        review_input = reviewer_call["messages"][1]["content"]
        self.assertIn("===== PAPER INPUT FILES =====", review_input)
        self.assertIn("StarA has rv 612.3 km/s.", review_input)
        self.assertIn("===== EXTRACTION UNDER REVIEW =====", review_input)

    def test_workflow_reviewer_retries_malformed_structured_reply(self) -> None:
        transport = mock.Mock(side_effect=[fake_response(self.scaffold_doc(0))])
        reviewer = mock.Mock(
            side_effect=[
                fake_response({"not_review": True}, model=DEFAULT_REVIEWER_MODEL),
                fake_review_response(),
            ]
        )

        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            reviewer_transport=reviewer,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.review_calls, 2)
        self.assertEqual(reviewer.call_count, 2)
        retry_message = reviewer.call_args_list[1].kwargs["messages"][-1]["content"]
        self.assertIn("not_review", retry_message)

    def test_workflow_reviewer_recovers_from_truncated_reply(self) -> None:
        transport = mock.Mock(side_effect=[fake_response(self.scaffold_doc(0))])
        truncated = fake_response({}, model=DEFAULT_REVIEWER_MODEL)
        truncated["choices"][0] = {
            "message": {"content": '{"review": {"challenges": ['},
            "finish_reason": "length",
        }
        reviewer = mock.Mock(
            side_effect=[truncated, fake_review_response()]
        )

        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            reviewer_transport=reviewer,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.review_calls, 2)

    def test_workflow_reviewer_exhaustion_has_explicit_error(self) -> None:
        transport = mock.Mock(side_effect=[fake_response(self.scaffold_doc(0))])
        reviewer = mock.Mock(
            side_effect=[
                fake_response({"not_review": call}, model=DEFAULT_REVIEWER_MODEL)
                for call in range(3)
            ]
        )

        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            reviewer_transport=reviewer,
        )

        self.assertEqual(result.status, "review_failed")
        self.assertEqual(result.review_calls, 3)
        self.assertIn("review_workflow_structured_output_failed", result.error)

    def test_invalid_document_skips_workflow_reviewer(self) -> None:
        transport = mock.Mock(side_effect=[fake_response(self.scaffold_doc(0))])

        result = self.run_one(
            FakeValidatorModule([["$.method_chain: still invalid"]]),
            transport,
            max_repair_rounds=0,
        )

        self.assertEqual(result.status, "validator_errors")
        self.assertEqual(result.review_calls, 0)
        self.assertEqual(self.reviewer_transport.call_count, 0)
        report = json.loads((self.run_dir / self.ARXIV / "report.json").read_text())
        self.assertEqual(report["validator_warnings"], ["w"])
        self.assertEqual(report["validator_findings"], [])
        self.assertEqual(report["validator_groups"], [])
        self.assertTrue(
            any(entry.get("reason") == "pre_review_validation_failed" for entry in report["stage_log"])
        )

    def test_cjk_failure_skips_reviewer_and_is_not_success(self) -> None:
        transport = mock.Mock(
            side_effect=[fake_response(self.scaffold_doc(0, summary="中文"))]
        )

        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            max_repair_rounds=0,
        )

        self.assertEqual(result.status, "validator_errors")
        self.assertEqual(result.review_calls, 0)
        self.assertEqual(self.reviewer_transport.call_count, 0)

    def test_reviewer_challenge_repairs_direct_pipeline(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(0)),
                fake_response(self.scaffold_doc(1, summary="review repaired")),
                fake_response(self.batch_reply([1])),
            ]
        )
        reviewer = mock.Mock(
            side_effect=[
                fake_review_response(
                    [
                        {
                            "candidate_index": -1,
                            "field": "candidates",
                            "issue": "Star1 is missing from the roster",
                            "severity": "high",
                        }
                    ]
                )
            ]
        )
        result = self.run_one(
            FakeValidatorModule([[], []]),
            transport,
            reviewer_transport=reviewer,
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.review_challenges, 1)
        self.assertEqual(result.review_fix_targets, 1)
        self.assertEqual(result.batch_count, 1)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(len(final["candidates"]), 1)
        self.assertEqual(final["extraction"]["summary"], "review repaired")

    def test_failed_review_revision_has_explicit_error(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(0)),
                fake_response({"not": "a scaffold"}),
                fake_response({"still": "not a scaffold"}),
                fake_response({"again": "not a scaffold"}),
            ]
        )
        reviewer = mock.Mock(
            side_effect=[
                fake_review_response(
                    [
                        {
                            "candidate_index": -1,
                            "field": "candidates",
                            "issue": "Star1 is missing from the roster",
                            "severity": "high",
                        }
                    ]
                )
            ]
        )

        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            reviewer_transport=reviewer,
        )

        self.assertEqual(result.status, "review_failed")
        self.assertIn("review_revision_failed", result.error)

    def test_reviewer_transport_failure_invalidates_direct_delivery(self) -> None:
        transport = mock.Mock(side_effect=[fake_response(self.scaffold_doc(0))])
        reviewer = mock.Mock(side_effect=RuntimeError("review endpoint down"))
        result = self.run_one(
            FakeValidatorModule([[]]),
            transport,
            reviewer_transport=reviewer,
        )
        self.assertEqual(result.status, "transport_error")
        self.assertIn("review endpoint down", result.error)

    def test_targeted_repair_touches_only_owning_batch(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(3)),
                fake_response(self.batch_reply([1, 2])),
                fake_response(self.batch_reply([3])),
                fake_response(self.batch_reply([3])),  # repair of batch 2
            ]
        )
        validator = FakeValidatorModule(
            [["$.candidates[2].core.x: bad value"], []]
        )
        result = self.run_one(validator, transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_rounds, 1)
        self.assertEqual(transport.call_count, 4)
        repair_messages = transport.call_args_list[3].kwargs["messages"]
        self.assertEqual(len(repair_messages), 4)
        self.assertIn("bad value", repair_messages[-1]["content"])
        # Batch repairs see the live method_chain — the scaffold may have
        # been repaired after the batch's original prompt was built.
        self.assertIn("CURRENT method_chain", repair_messages[-1]["content"])
        self.assertIn("step-01", repair_messages[-1]["content"])
        attempts = self.run_dir / self.ARXIV / "attempts"
        self.assertTrue((attempts / "batch-002-call-02.response.json").is_file())
        self.assertFalse((attempts / "batch-001-call-02.response.json").exists())

    def test_rejected_repair_is_retried_with_structure_feedback(self) -> None:
        # pilot-04: a repair reply dropped one record, the count check
        # silently discarded it, and the error plateau froze. The repair
        # must be retried with the structure errors added to the feedback.
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(2)),
                fake_response(self.batch_reply([1, 2])),
                fake_response(self.batch_reply([1])),  # repair drops cand-002
                fake_response(self.batch_reply([1, 2])),  # retried repair ok
            ]
        )
        validator = FakeValidatorModule(
            [["$.candidates[0].core.x: bad value"], []]
        )
        result = self.run_one(validator, transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(transport.call_count, 4)
        retry_feedback = transport.call_args_list[3].kwargs["messages"][-1]
        self.assertIn("exactly 2 candidates", retry_feedback["content"])
        self.assertIn("bad value", retry_feedback["content"])
        report = json.loads(
            (self.run_dir / self.ARXIV / "report.json").read_text()
        )
        self.assertTrue(
            any("repair_rejected" in entry for entry in report["stage_log"])
        )

    def test_scaffold_prompt_forbids_source_missing_misuse(self) -> None:
        from stella.benchmark.extraction_run import build_scaffold_prompt

        prompt = build_scaffold_prompt(
            {"schema_version": "x"},
            PackedContext(text="paper text"),
            render_rule_profile(ROOT, "hvs_roster", "prompt"),
        )
        self.assertIn("do not use status 'source_missing'", prompt)
        self.assertIn("identifiable subset", prompt)

    def test_method_a_skill_and_bc_prompt_share_candidate_policy(self) -> None:
        skill = (
            ROOT / "skills" / "hvs-candidates-extraction" / "SKILL.md"
        ).read_text(encoding="utf-8")
        guideline = (ROOT / "benchmark" / "GUIDELINE.md").read_text(
            encoding="utf-8"
        )

        for fragment in (
            "final treatment",
            "cite-in-passing",
            "fewest extra model",
            "inaccessible remainder",
        ):
            self.assertIn(fragment, skill)
            self.assertIn(fragment, guideline)
        prompt_rules = render_rule_profile(ROOT, "hvs_extractor", "prompt")
        self.assertIn(prompt_rules, build_system_prompt(ROOT))

    def test_truncated_batch_is_split_in_half(self) -> None:
        truncated = fake_response({})
        truncated["choices"][0] = {
            "message": {"content": '{"candidates": [{"identifiers": {'},
            "finish_reason": "length",
        }
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(2)),
                truncated,  # batch-001 (2 stubs) hits the output cap
                fake_response(self.batch_reply([1])),  # batch-001a
                fake_response(self.batch_reply([2])),  # batch-001b
            ]
        )
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(transport.call_count, 4)
        self.assertEqual(result.batch_count, 2)  # final groups after split
        self.assertEqual(result.batch_calls, 3)  # orphaned call + two fills
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(len(final["candidates"]), 2)
        attempts = self.run_dir / self.ARXIV / "attempts"
        self.assertTrue((attempts / "batch-001a-call-01.response.json").is_file())
        self.assertTrue((attempts / "batch-001b-call-01.response.json").is_file())
        report = json.loads(
            (self.run_dir / self.ARXIV / "report.json").read_text()
        )
        self.assertTrue(
            any("split_for_truncation" in entry for entry in report["stage_log"])
        )

    def test_document_level_error_repairs_scaffold(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(2)),
                fake_response(self.batch_reply([1, 2])),
                fake_response(self.scaffold_doc(2, summary="repaired")),
            ]
        )
        validator = FakeValidatorModule(
            [["$.method_chain[0]: summary is required"], []]
        )
        result = self.run_one(validator, transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(transport.call_count, 3)
        feedback = transport.call_args_list[2].kwargs["messages"][-1]["content"]
        self.assertIn("summary is required", feedback)
        self.assertIn("NEVER renumber", feedback)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(final["extraction"]["summary"], "repaired")

    def test_invalid_scaffold_structure_is_retried_with_feedback(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response({"not": "a scaffold"}),
                fake_response(self.scaffold_doc(0)),
            ]
        )
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.scaffold_attempts, 2)
        retry_messages = transport.call_args_list[1].kwargs["messages"]
        self.assertIn("missing the", retry_messages[-1]["content"])

    def test_cjk_in_scaffold_routes_to_scaffold_repair(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(0, summary="\u4e2d\u6587\u6458\u8981")),
                fake_response(self.scaffold_doc(0, summary="english")),
            ]
        )
        result = self.run_one(FakeValidatorModule([[], []]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(result.cjk_paths, [])

    def test_transport_error_is_archived(self) -> None:
        transport = mock.Mock(
            side_effect=LLMTransportError(
                "provider unavailable",
                category="server",
                http_status=503,
                automatic_retryable=True,
                manual_retry_eligible=True,
                provider_request_id="req-test",
                response_body_excerpt="unavailable",
            )
        )
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "transport_error")
        self.assertIn("provider unavailable", result.error)
        report = json.loads(
            (self.run_dir / self.ARXIV / "report.json").read_text()
        )
        self.assertEqual(report["status"], "transport_error")
        self.assertEqual(report["transport_error"]["category"], "server")
        self.assertEqual(report["transport_error"]["stage"], "scaffold")
        self.assertEqual(report["transport_error"]["call_id"], f"{self.ARXIV}:scaffold:1")
        archived = self.run_dir / self.ARXIV / "attempts" / "scaffold-call-01.transport-error.json"
        self.assertTrue(archived.is_file())

    def test_request_extra_reaches_transport_and_provenance(self) -> None:
        extra = {"provider": {"order": ["deepseek"]}}
        transport = mock.Mock(side_effect=[fake_response(self.scaffold_doc(0))])
        result = self.run_one(
            FakeValidatorModule([[]]), transport, request_extra=extra
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(transport.call_args.kwargs["extra_body"], extra)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        recorded = final["extraction"]["provenance"]["parameters"]
        self.assertEqual(recorded["provider"], {"order": ["deepseek"]})

    def test_nested_cache_usage_is_normalized_in_report(self) -> None:
        response = fake_response(self.scaffold_doc(0))
        response["usage"]["prompt_tokens_details"] = {"cached_tokens": 80}
        result = self.run_one(
            FakeValidatorModule([[]]), mock.Mock(side_effect=[response])
        )
        self.assertEqual(result.usage_totals["prompt_cache_hit_tokens"], 80)
        report = json.loads(
            (self.run_dir / self.ARXIV / "report.json").read_text()
        )
        self.assertEqual(
            report["usage_totals"]["prompt_cache_hit_tokens"], 80
        )


class RunnerRoutingTest(unittest.TestCase):
    """build_request_extra in scripts/run_benchmark_extraction.py."""

    @classmethod
    def setUpClass(cls) -> None:
        import importlib.util

        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "run_benchmark_extraction.py"
        )
        spec = importlib.util.spec_from_file_location("bench_runner", script)
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    @staticmethod
    def args(**overrides):
        import argparse

        defaults = {
            "provider": None,
            "no_provider_pin": False,
            "fallback_model": None,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_known_models_pin_first_party_provider(self) -> None:
        extra = self.runner.build_request_extra(self.args(), "deepseek-v4-pro")
        self.assertEqual(extra, {"provider": {"order": ["deepseek"]}})
        extra = self.runner.build_request_extra(self.args(), "mimo-v2.5-pro")
        self.assertEqual(
            extra, {"provider": {"order": ["infini-ai", "xiaomi"]}}
        )
        extra = self.runner.build_request_extra(self.args(), "glm-5.2")
        self.assertEqual(extra, {"provider": {"order": ["bigmodel"]}})

    def test_unknown_model_and_opt_out_have_no_pin(self) -> None:
        self.assertEqual(
            self.runner.build_request_extra(self.args(), "some-other-model"), {}
        )
        self.assertEqual(
            self.runner.build_request_extra(
                self.args(no_provider_pin=True), "deepseek-v4-pro"
            ),
            {},
        )

    def test_explicit_provider_and_fallback_models(self) -> None:
        extra = self.runner.build_request_extra(
            self.args(
                provider=["bigmodel", "deepseek"],
                fallback_model=["mimo-v2.5-pro", "mimo-v2.5-pro"],
            ),
            "deepseek-v4-pro",
        )
        self.assertEqual(extra["provider"], {"order": ["bigmodel", "deepseek"]})
        self.assertEqual(extra["models"], ["mimo-v2.5-pro"])


class ExistingArtifactsGuardTest(unittest.TestCase):
    """papers_with_existing_artifacts: rerun clobber protection.

    Regression for gold8-c-03 2401.02017, where a retry into a live paper
    directory interleaved two attempt streams and destroyed the archive.
    """

    def test_flags_only_papers_with_artifacts(self) -> None:
        from stella.benchmark.extraction_run import papers_with_existing_artifacts

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "1111.00001" / "attempts").mkdir(parents=True)
            (run_dir / "2222.00002").mkdir()
            (run_dir / "2222.00002" / "report.json").write_text("{}", encoding="utf-8")
            (run_dir / "3333.00003").mkdir()
            (run_dir / "3333.00003" / "literature_hvs_candidates.json").write_text(
                "{}", encoding="utf-8"
            )
            # Only a context manifest (no attempts/report/candidates) is not
            # a completed or in-flight extraction; a fresh dir is clean too.
            (run_dir / "4444.00004").mkdir()
            (run_dir / "4444.00004" / "context_manifest.json").write_text(
                "{}", encoding="utf-8"
            )

            dirty = papers_with_existing_artifacts(
                run_dir,
                ["1111.00001", "2222.00002", "3333.00003", "4444.00004", "5555.00005"],
            )

        self.assertEqual(dirty, ["1111.00001", "2222.00002", "3333.00003"])

    def test_missing_run_dir_is_clean(self) -> None:
        from stella.benchmark.extraction_run import papers_with_existing_artifacts

        dirty = papers_with_existing_artifacts(
            Path("/nonexistent/run/dir"), ["1111.00001"]
        )
        self.assertEqual(dirty, [])


class ChatCompletionRawTest(unittest.TestCase):
    def _http_error(self, code: int) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            "https://example.invalid", code, "err", hdrs=None, fp=io.BytesIO(b"")
        )

    def test_retries_429_then_succeeds(self) -> None:
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"model": "m"}'
        with mock.patch(
            "stella.lit.llm_batch.urllib.request.urlopen",
            side_effect=[self._http_error(429), ok],
        ), mock.patch("stella.lit.llm_batch.time.sleep"):
            response = chat_completion_raw(
                api_key="k",
                base_url="https://example.invalid/v1",
                model="m",
                messages=[{"role": "user", "content": "hi"}],
            )
        self.assertEqual(response, {"model": "m"})

    def test_extra_body_merges_without_overriding_core_fields(self) -> None:
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"model": "m"}'
        with mock.patch(
            "stella.lit.llm_batch.urllib.request.urlopen", return_value=ok
        ) as urlopen:
            chat_completion_raw(
                api_key="k",
                base_url="https://example.invalid/v1",
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                extra_body={
                    "provider": {"order": ["deepseek"]},
                    "models": ["fallback-model"],
                    "model": "evil-override",
                },
            )
        sent = json.loads(urlopen.call_args[0][0].data.decode("utf-8"))
        self.assertEqual(sent["provider"], {"order": ["deepseek"]})
        self.assertEqual(sent["models"], ["fallback-model"])
        self.assertEqual(sent["model"], "m")  # explicit args win

    def test_retries_remote_disconnect_then_succeeds(self) -> None:
        import http.client

        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"model": "m"}'
        with mock.patch(
            "stella.lit.llm_batch.urllib.request.urlopen",
            side_effect=[
                http.client.RemoteDisconnected("closed without response"),
                ok,
            ],
        ), mock.patch("stella.lit.llm_batch.time.sleep"):
            response = chat_completion_raw(
                api_key="k",
                base_url="https://example.invalid/v1",
                model="m",
                messages=[{"role": "user", "content": "hi"}],
            )
        self.assertEqual(response, {"model": "m"})

    def test_auth_error_raises_immediately(self) -> None:
        with mock.patch(
            "stella.lit.llm_batch.urllib.request.urlopen",
            side_effect=self._http_error(401),
        ):
            with self.assertRaises(LLMTransportError) as raised:
                chat_completion_raw(
                    api_key="k",
                    base_url="https://example.invalid/v1",
                    model="m",
                    messages=[{"role": "user", "content": "hi"}],
                )
        self.assertEqual(raised.exception.category, "authentication")
        self.assertTrue(raised.exception.manual_retry_eligible)


if __name__ == "__main__":
    unittest.main()
