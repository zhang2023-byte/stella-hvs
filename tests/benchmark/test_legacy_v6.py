"""The read-only V6 legacy boundary.

The legacy reader validates persisted v3 candidates documents and V6
scorecards without ever generating new candidate artifacts. Candidate
schema views survive in the registry only for this boundary, and the
legacy candidate calculator refuses writes.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.legacy_v6 import read_v6_candidates_document
from stella.schema_registry import MODELLED_ARTIFACTS
ROOT = Path(__file__).resolve().parents[2]


HISTORICAL_V1 = next(
    iter(sorted(ROOT.glob("literature/*/literature_hvs_candidates.json")))
)


def _v1_document() -> dict:
    return json.loads(HISTORICAL_V1.read_text(encoding="utf-8"))


class LegacyV6BoundaryTest(unittest.TestCase):
    def test_reader_validates_persisted_historical_documents(self) -> None:
        document = read_v6_candidates_document(HISTORICAL_V1)
        self.assertEqual(
            document["schema"]["name"], "literature_hvs_candidates"
        )
        self.assertEqual(document["schema"]["version"], 1)

    def test_reader_rejects_unknown_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _v1_document()
            document["schema"]["version"] = 99
            path = Path(tmp) / "candidates.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(Exception):
                read_v6_candidates_document(path)

    def test_candidate_views_survive_only_for_the_legacy_reader(self) -> None:
        candidates = [
            version
            for name, version in MODELLED_ARTIFACTS
            if name == "literature_hvs_candidates"
        ]
        self.assertEqual(
            candidates,
            [1],
            "only the v1 view with persisted historical instances stays "
            "in the active registry",
        )

    def test_legacy_candidate_calculator_is_read_only(self) -> None:
        from stella.dyn.dynamics import calculate_catalog_dynamics

        with tempfile.TemporaryDirectory() as tmp:
            catalog_dir = Path(tmp) / "catalog"
            candidates_dir = catalog_dir / "candidates"
            candidates_dir.mkdir(parents=True)
            (candidates_dir / "obj.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                calculate_catalog_dynamics(catalog_dir, write=True)
            self.assertIn("read-only", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
