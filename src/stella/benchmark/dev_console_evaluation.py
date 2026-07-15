"""Local dev-only benchmark evaluation orchestration for the console."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from stella.lit.env import env_value
from stella.schema_registry import schema_ref

from .dev_console_groups import ACTIVE_RUN_STATUSES, ExperimentGroupStore, SUCCESS_RUN_STATUSES
from .paths import campaign_paths, require_external_path, validate_path_segment


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DevEvaluationService:
    """Audit, seal, and locally score selected dev runs in the background."""

    def __init__(
        self,
        workspace: Path,
        *,
        groups: ExperimentGroupStore,
        campaign_id: str,
        run_command: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    ) -> None:
        self.workspace = workspace.resolve()
        self.groups = groups
        self.campaign_id = validate_path_segment(campaign_id, "campaign id")
        self._run_command = run_command
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def _root(self, group_id: str) -> Path:
        return self.groups.evaluation_root(validate_path_segment(group_id, "group id"))

    def _state_path(self, group_id: str) -> Path:
        return self._root(group_id) / "controller.json"

    def _scorecards_root(self, group_id: str) -> Path:
        return self._root(group_id) / "scorecards"

    def _read_state(self, group_id: str) -> dict[str, Any] | None:
        path = self._state_path(group_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _reconcile_state(self, group_id: str, state: dict[str, Any] | None) -> dict[str, Any] | None:
        if not state or state.get("status") not in {"queued", "running"}:
            return state
        thread = self._threads.get(group_id)
        if thread is not None and thread.is_alive():
            return state
        state["status"] = "failed"
        state["finished_at"] = state.get("finished_at") or _utc_now()
        state["error"] = "evaluation was interrupted by a console restart"
        for run in state.get("runs", {}).values():
            if isinstance(run, dict) and run.get("status") in {"queued", "running"}:
                run["status"] = "failed"
                run["error"] = state["error"]
        return self._write_state(group_id, state)

    def _write_state(self, group_id: str, state: dict[str, Any]) -> dict[str, Any]:
        path = self._state_path(group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            **state,
            "schema": schema_ref("benchmark.dev_evaluation"),
            "group_id": group_id,
            "campaign_id": self.campaign_id,
            "updated_at": _utc_now(),
        }
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            temporary.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return document

    @staticmethod
    def _selected_run_ids(group: dict[str, Any], requested: Any) -> list[str]:
        available = [str(item.get("run_id") or "") for item in group.get("experiments", [])]
        if requested in (None, []):
            return available
        if not isinstance(requested, list) or not requested:
            raise ValueError("run_ids must be a non-empty list")
        selected: list[str] = []
        for value in requested:
            run_id = validate_path_segment(str(value or ""), "run id")
            if run_id not in available:
                raise ValueError(f"run {run_id} is not part of this experiment group")
            if run_id not in selected:
                selected.append(run_id)
        return selected

    def preflight(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        group = self.groups.read(group_id)
        selected = self._selected_run_ids(group, payload.get("run_ids"))
        allow_unavailable = bool(payload.get("allow_unavailable", False))
        checks: list[dict[str, Any]] = []

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": bool(ok), "detail": detail})

        experiment_by_run = {
            str(item.get("run_id") or ""): item for item in group.get("experiments", [])
        }
        formal_scope = group.get("scope", "formal_dev") == "formal_dev"
        check(
            "formal dev scope",
            formal_scope,
            "formal_dev" if formal_scope else "regression groups cannot be evaluated or sealed",
        )
        active = [run_id for run_id in selected if experiment_by_run[run_id].get("status") in ACTIVE_RUN_STATUSES]
        unavailable = [run_id for run_id in selected if experiment_by_run[run_id].get("status") not in SUCCESS_RUN_STATUSES]
        check("selected runs", bool(selected), f"{len(selected)} run(s)")
        check("no active extraction", not active, "ready" if not active else ", ".join(active))
        check(
            "unavailable acknowledgement",
            not unavailable or allow_unavailable,
            "all completed" if not unavailable else f"{len(unavailable)} run(s) include unavailable deliveries",
        )
        paths = campaign_paths(self.workspace, self.campaign_id)
        missing_configs = [run_id for run_id in selected if not (paths.runs / run_id / "run_config.json").is_file()]
        check("run configs", not missing_configs, "ready" if not missing_configs else ", ".join(missing_configs))
        gold_value = env_value("STELLA_GOLD_DIR")
        gold_dir: Path | None = None
        if gold_value:
            try:
                gold_dir = require_external_path(
                    Path(gold_value), workspace=self.workspace, label="gold directory"
                )
            except ValueError:
                gold_dir = None
        check("private gold store", bool(gold_dir and gold_dir.is_dir()), "configured" if gold_dir and gold_dir.is_dir() else "missing or unsafe")
        check("gold manifest", paths.gold_manifest.is_file(), str(paths.gold_manifest))
        contaminated: list[str] = []
        for run_id in selected:
            manifest_path = paths.runs / run_id / "run_manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                contaminated.append(run_id)
                continue
            if (manifest.get("leakage_audit") or {}).get("status") != "clean":
                contaminated.append(run_id)
        check("sealed audit status", not contaminated, "clean or pending audit" if not contaminated else ", ".join(contaminated))
        current = self._reconcile_state(group_id, self._read_state(group_id))
        check(
            "no active evaluation",
            not current or current.get("status") not in {"queued", "running"},
            "ready" if not current or current.get("status") not in {"queued", "running"} else "evaluation already running",
        )
        return {
            "ok": all(item["ok"] for item in checks),
            "checks": checks,
            "group_id": group_id,
            "run_ids": selected,
            "allow_unavailable": allow_unavailable,
        }

    def start(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        preflight = self.preflight(group_id, payload)
        if not preflight["ok"]:
            raise ValueError("evaluation preflight failed")
        with self._lock:
            current = self._reconcile_state(group_id, self._read_state(group_id))
            if current and current.get("status") in {"queued", "running"}:
                raise ValueError("evaluation already running")
            state = self._write_state(
                group_id,
                {
                    "evaluation_id": f"eval-{secrets.token_hex(6)}",
                    "status": "queued",
                    "run_ids": preflight["run_ids"],
                    "allow_unavailable": preflight["allow_unavailable"],
                    "created_at": _utc_now(),
                    "runs": {
                        run_id: {"status": "queued", "stage": "audit"}
                        for run_id in preflight["run_ids"]
                    },
                },
            )
            thread = threading.Thread(
                target=self._execute,
                args=(group_id,),
                name=f"stella-dev-evaluation-{group_id}",
                daemon=True,
            )
            self._threads[group_id] = thread
            thread.start()
        self.groups.emit(group_id, "evaluation.started", status="queued")
        return state

    def _command(self, args: list[str]) -> subprocess.CompletedProcess[Any]:
        return self._run_command(
            args,
            cwd=self.workspace,
            env=dict(os.environ),
            shell=False,
            capture_output=True,
            text=True,
        )

    def _update_run(self, group_id: str, run_id: str, **updates: Any) -> dict[str, Any]:
        with self._lock:
            state = self._read_state(group_id)
            if state is None:
                raise ValueError("evaluation state disappeared")
            state.setdefault("runs", {}).setdefault(run_id, {}).update(updates)
            state["status"] = "running"
            written = self._write_state(group_id, state)
        self.groups.emit(
            group_id,
            "evaluation.stage.changed",
            run_id=run_id,
            status=str(updates.get("status") or "running"),
            data={"stage": updates.get("stage")},
        )
        return written

    def _execute(self, group_id: str) -> None:
        current_run_id = ""
        current_stage = "audit"
        try:
            state = self._read_state(group_id)
            if state is None:
                raise ValueError("evaluation state is missing")
            state["status"] = "running"
            state["started_at"] = _utc_now()
            self._write_state(group_id, state)
            paths = campaign_paths(self.workspace, self.campaign_id)
            gold_dir = require_external_path(
                Path(env_value("STELLA_GOLD_DIR")),
                workspace=self.workspace,
                label="gold directory",
            )
            details_root = require_external_path(
                gold_dir.parent / "scoring-details" / "dev-console" / group_id,
                workspace=self.workspace,
                label="private dev scoring details",
            )
            scorecards_root = self._scorecards_root(group_id)
            for run_id in state["run_ids"]:
                current_run_id = run_id
                run_dir = paths.runs / run_id
                manifest_path = run_dir / "run_manifest.json"
                if not manifest_path.is_file():
                    current_stage = "audit"
                    self._update_run(group_id, run_id, status="running", stage="audit")
                    audit_path = run_dir / "leakage_audit.json"
                    result = self._command(
                        [
                            sys.executable,
                            str(self.workspace / "scripts" / "audit_extraction_run.py"),
                            str(run_dir),
                            "--report",
                            str(audit_path),
                        ]
                    )
                    audit: dict[str, Any] = {}
                    if audit_path.is_file():
                        try:
                            audit = json.loads(audit_path.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            audit = {}
                    if result.returncode != 0 or audit.get("status") != "clean":
                        files = sorted(
                            {
                                str(item.get("file") or "")
                                for item in audit.get("hits", [])
                                if item.get("file")
                            }
                        )
                        self._update_run(
                            group_id,
                            run_id,
                            status="failed",
                            stage="audit",
                            error="leakage audit did not pass",
                            contaminated_files=files,
                            hit_count=len(audit.get("hits", [])),
                        )
                        raise ValueError(f"run {run_id} failed leakage audit")
                    self._update_run(group_id, run_id, status="running", stage="seal")
                    current_stage = "seal"
                    result = self._command(
                        [
                            sys.executable,
                            str(self.workspace / "scripts" / "seal_benchmark_run.py"),
                            str(run_dir),
                            "--audit-report",
                            str(audit_path),
                        ]
                    )
                    if result.returncode != 0:
                        raise ValueError(f"run {run_id} could not be sealed")
                current_stage = "score"
                self._update_run(group_id, run_id, status="running", stage="score")
                result = self._command(
                    [
                        sys.executable,
                        str(self.workspace / "scripts" / "score_benchmark_run.py"),
                        "--run-dir",
                        str(run_dir),
                        "--campaign-manifest",
                        str(paths.campaign_manifest),
                        "--gold-manifest",
                        str(paths.gold_manifest),
                        "--releases-root",
                        str(paths.releases),
                        "--split",
                        "dev",
                        "--run-label",
                        run_id,
                        "--scoring-dir",
                        str(scorecards_root),
                        "--details-dir",
                        str(details_root),
                    ]
                )
                scorecard_path = scorecards_root / run_id / "scorecard.json"
                if result.returncode != 0 or not scorecard_path.is_file():
                    raise ValueError(f"run {run_id} could not be scored")
                self._update_run(
                    group_id,
                    run_id,
                    status="completed",
                    stage="completed",
                    scorecard=f"scorecards/{run_id}/scorecard.json",
                )
            with self._lock:
                completed = self._read_state(group_id) or state
                completed["status"] = "completed"
                completed["finished_at"] = _utc_now()
                self._write_state(group_id, completed)
            self.groups.emit(group_id, "evaluation.completed", status="completed")
        except Exception as exc:
            with self._lock:
                failed = self._read_state(group_id) or {
                    "evaluation_id": "unknown",
                    "run_ids": [],
                    "runs": {},
                }
                if current_run_id:
                    failed.setdefault("runs", {}).setdefault(current_run_id, {}).update(
                        {
                            "status": "failed",
                            "stage": current_stage,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                failed["status"] = "failed"
                failed["finished_at"] = _utc_now()
                failed["error"] = f"{type(exc).__name__}: {exc}"
                self._write_state(group_id, failed)
            self.groups.emit(group_id, "evaluation.failed", status="failed", summary=str(exc))
        finally:
            self._threads.pop(group_id, None)

    def get(self, group_id: str) -> dict[str, Any]:
        group_id = validate_path_segment(group_id, "group id")
        state = self._reconcile_state(group_id, self._read_state(group_id))
        if state is None:
            return {
                "schema": schema_ref("benchmark.dev_evaluation"),
                "group_id": group_id,
                "campaign_id": self.campaign_id,
                "status": "not_started",
                "run_ids": [],
                "runs": {},
            }
        return state

    def scorecards(self, group_id: str) -> list[dict[str, Any]]:
        root = self._scorecards_root(validate_path_segment(group_id, "group id"))
        if not root.is_dir():
            return []
        cards: list[dict[str, Any]] = []
        for path in sorted(root.glob("*/scorecard.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                cards.append(payload)
        return cards
