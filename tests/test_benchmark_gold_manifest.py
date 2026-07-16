from __future__ import annotations

import unittest

from stella.benchmark.gold_manifest import validate_append_only_gold_manifest


class GoldManifestAppendOnlyTest(unittest.TestCase):
    def manifest(self, *records: tuple[str, str]) -> dict:
        return {
            "schema": {"name": "benchmark.gold_manifest", "version": 1},
            "files": [
                {"arxiv_id": arxiv_id, "file": f"{arxiv_id}/annotation.json", "sha256": digest, "bytes": 10}
                for arxiv_id, digest in records
            ],
        }

    def test_new_papers_may_be_appended(self) -> None:
        previous = self.manifest(("paper-a", "a" * 64))
        proposed = self.manifest(("paper-a", "a" * 64), ("paper-b", "b" * 64))
        validate_append_only_gold_manifest(previous, proposed)

    def test_existing_hash_change_is_rejected(self) -> None:
        previous = self.manifest(("paper-a", "a" * 64))
        proposed = self.manifest(("paper-a", "b" * 64))
        with self.assertRaisesRegex(ValueError, "paper-a.*hash changed"):
            validate_append_only_gold_manifest(previous, proposed)

    def test_existing_paper_cannot_be_removed(self) -> None:
        previous = self.manifest(("paper-a", "a" * 64))
        with self.assertRaisesRegex(ValueError, "paper-a.*removed"):
            validate_append_only_gold_manifest(previous, self.manifest())

    def test_yaml_and_json_twins_are_one_immutable_paper_snapshot(self) -> None:
        previous = self.manifest(("paper-a", "a" * 64))
        previous["files"].append(
            {
                "arxiv_id": "paper-a",
                "file": "paper-a/annotation.yaml",
                "sha256": "b" * 64,
                "bytes": 10,
            }
        )
        proposed = {"schema": dict(previous["schema"]), "files": [dict(item) for item in previous["files"]]}
        validate_append_only_gold_manifest(previous, proposed)
        proposed["files"][1]["sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "paper-a.*hash changed"):
            validate_append_only_gold_manifest(previous, proposed)


if __name__ == "__main__":
    unittest.main()
