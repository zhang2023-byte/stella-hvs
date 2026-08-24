"""Local controller for the one-action contribution gold form.

The controller is the importable, GUI-free core of the local expert
form: an HTTP layer would wrap ``GoldFormController.handle_request``,
while every scientific gate (PDF-only input, validate-before-save,
explicit expert approval, one JSON per paper and expert) is enforced
here. The unified CLI's gold_annotation workflow drives the same
underlying actions; this controller serves the interactive localhost
form session for one paper and expert.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stella.benchmark.hvs_contribution_gold_form import (
    ContributionGoldFormError,
    build_empty_contribution_payload,
    draft_path,
    load_draft,
    save_expert_annotation,
    save_draft,
    validate_and_lint,
)

WORK_DIR_ENV = "STELLA_GOLD_WORK_DIR"
GOLD_DIR_ENV = "STELLA_GOLD_DIR"


class GoldFormController:
    """Route one expert's form requests for one paper.

    ``root`` is the repository/workspace root carrying the archived
    paper PDF; ``gold_dir`` is the private store root and ``work_dir``
    the annotator-scoped draft area (both default to the documented
    environment locations so tests can inject temporary roots).
    """

    def __init__(
        self,
        *,
        root: Path,
        gold_dir: Path | None = None,
        work_dir: Path | None = None,
        expert: str = "",
    ) -> None:
        import os

        self.root = Path(root)
        self.gold_dir = Path(
            gold_dir or os.environ.get(GOLD_DIR_ENV, "")
        )
        self.work_dir = Path(
            work_dir or os.environ.get(WORK_DIR_ENV, "")
        )
        self.expert = expert

    def handle_request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        """Pure routing core: (status_code, payload) without any socket."""

        body = body or {}
        segments = [seg for seg in path.strip("/").split("/") if seg]
        if len(segments) < 2 or segments[0] != "papers":
            return 404, {"error": "unknown form route"}
        paper_id = segments[1]
        try:
            if method == "GET" and len(segments) == 1 + 1:
                return 200, self._form_document(paper_id)
            if method == "POST" and segments[2:] == ["draft"]:
                return 200, self._save_draft(paper_id, body)
            if method == "POST" and segments[2:] == ["validate"]:
                return 200, self._validate(paper_id)
            if method == "POST" and segments[2:] == ["save"]:
                return self._save(paper_id, body)
        except ContributionGoldFormError as error:
            return 422, {"error": str(error)}
        return 404, {"error": "unknown form route"}

    def _form_document(self, paper_id: str) -> dict[str, Any]:
        try:
            draft = load_draft(self.work_dir, paper_id, self.expert)
        except ContributionGoldFormError:
            draft = build_empty_contribution_payload(
                arxiv_id=paper_id, annotator=self.expert
            )
            save_draft(draft, self.work_dir)
        pdf = self._paper_pdf(paper_id)
        return {
            "paper_id": paper_id,
            "expert": self.expert,
            "pdf": str(pdf) if pdf else None,
            "draft": draft,
            "draft_path": str(
                draft_path(self.work_dir, paper_id, self.expert)
            ),
        }

    def _paper_pdf(self, paper_id: str) -> Path | None:
        assets = self.root / "literature" / paper_id / "assets"
        if not assets.is_dir():
            return None
        return next(iter(sorted(assets.glob("*.pdf"))), None)

    def _save_draft(
        self, paper_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        draft = body.get("draft")
        if not isinstance(draft, dict):
            raise ContributionGoldFormError("draft body must be an object")
        draft.setdefault("arxiv_id", paper_id)
        draft.setdefault("annotator", self.expert)
        return save_draft(draft, self.work_dir)

    def _validate(self, paper_id: str) -> dict[str, Any]:
        try:
            draft = load_draft(self.work_dir, paper_id, self.expert)
        except ContributionGoldFormError as error:
            return {
                "paper_id": paper_id,
                "ok": False,
                "errors": [f"draft not loadable: {error}"],
            }
        try:
            result = validate_and_lint(draft)
        except Exception as error:  # noqa: BLE001 - a blocked save is the point
            return {
                "paper_id": paper_id,
                "ok": False,
                "errors": [f"{type(error).__name__}: {error}"],
            }
        return {"paper_id": paper_id, "ok": bool(result.get("ok")), **result}

    def _save(
        self, paper_id: str, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        draft = load_draft(self.work_dir, paper_id, self.expert)
        gate = self._validate(paper_id)
        if not gate.get("ok"):
            return 422, {
                "error": "validate-before-save gate failed",
                "gate": gate,
            }
        if not body.get("expert_approved"):
            return 422, {
                "error": "final save requires explicit expert approval",
            }
        summary = save_expert_annotation(
            draft,
            self.gold_dir,
            work_dir=self.work_dir,
            expected_arxiv_id=paper_id,
            expected_annotator=self.expert,
            expert_approved=True,
        )
        return 200, summary


def render_form_http_response(status: int, payload: dict[str, Any]) -> str:
    """Render one controller response as an HTTP body (text, no socket)."""

    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
