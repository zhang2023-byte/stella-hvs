"""Persistent experiment-group scheduling for the local benchmark console."""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from stella.schema_registry import schema_ref

from .paths import validate_path_segment


ACTIVE_RUN_STATUSES = {"running", "stop_requested"}
REVIEW_RUN_STATUSES = {"failed", "partial", "stopped"}
SUCCESS_RUN_STATUSES = {"completed", "sealed"}
QUEUE_STATUSES = {"queued", "resume_queued"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ExperimentGroupStore:
    """Own group state while delegating individual-run process control."""

    def __init__(
        self,
        logs_root: Path,
        *,
        campaign_id: str,
        launch: Callable[[dict[str, Any], bool], dict[str, Any]],
        stop: Callable[[str], dict[str, Any]],
        status: Callable[[str], dict[str, Any]],
        scheduler: bool = True,
    ) -> None:
        self.logs_root = logs_root.resolve()
        self.campaign_id = validate_path_segment(campaign_id, "campaign id")
        self.root = self.logs_root / self.campaign_id / "_groups"
        self._launch = launch
        self._stop = stop
        self._status = status
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        if scheduler:
            self._scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                name="stella-dev-group-scheduler",
                daemon=True,
            )
            self._scheduler_thread.start()

    def close(self) -> None:
        self._shutdown.set()
        if self._scheduler_thread is not None:
            self._scheduler_thread.join(timeout=2)

    def _group_root(self, group_id: str) -> Path:
        return self.root / validate_path_segment(group_id, "group id")

    def _group_path(self, group_id: str) -> Path:
        return self._group_root(group_id) / "group.json"

    def _events_path(self, group_id: str) -> Path:
        return self._group_root(group_id) / "events.jsonl"

    def evaluation_root(self, group_id: str) -> Path:
        return self._group_root(group_id) / "evaluation"

    def exists(self, group_id: str) -> bool:
        return self._group_path(group_id).is_file()

    def _read(self, group_id: str) -> dict[str, Any]:
        path = self._group_path(group_id)
        if not path.is_file():
            raise ValueError("experiment group does not exist")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("experiment group state is unreadable") from exc
        if not isinstance(payload, dict):
            raise ValueError("experiment group state must be an object")
        return payload

    def _write(self, group: dict[str, Any]) -> dict[str, Any]:
        group_id = validate_path_segment(str(group.get("group_id") or ""), "group id")
        path = self._group_path(group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            **group,
            "schema": group.get("schema") or schema_ref("benchmark.dev_experiment_group"),
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

    def _emit(
        self,
        group_id: str,
        event_type: str,
        *,
        run_id: str = "",
        status: str = "",
        summary: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = self._events_path(group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        seq = 0
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    seq = max(seq, int(json.loads(line).get("seq") or 0))
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
        event: dict[str, Any] = {
            "schema": schema_ref("benchmark.dev_group_event"),
            "seq": seq + 1,
            "occurred_at": _utc_now(),
            "campaign_id": self.campaign_id,
            "group_id": group_id,
            "type": event_type,
        }
        if run_id:
            event["run_id"] = run_id
        if status:
            event["status"] = status
        if summary:
            event["summary"] = summary
        if data:
            event["data"] = data
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
        return event

    @staticmethod
    def _derive_status(group: dict[str, Any]) -> str:
        if group.get("paused"):
            return "paused"
        statuses = {str(item.get("status") or "queued") for item in group.get("experiments", [])}
        if statuses & ACTIVE_RUN_STATUSES:
            return "running"
        if statuses & QUEUE_STATUSES:
            return "queued"
        if statuses & REVIEW_RUN_STATUSES:
            return "needs_review"
        if statuses and statuses <= SUCCESS_RUN_STATUSES:
            return "completed"
        return "queued"

    def create(
        self,
        *,
        group_id: str,
        max_parallel_experiments: int,
        requests: list[dict[str, Any]],
        scope: str = "formal_dev",
        paper_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        group_id = validate_path_segment(group_id, "group id")
        if not 1 <= max_parallel_experiments <= 4:
            raise ValueError("max_parallel_experiments must be between 1 and 4")
        if not requests or len(requests) > 20:
            raise ValueError("experiment group must contain between 1 and 20 experiments")
        run_ids = [str(request.get("run_id") or "") for request in requests]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("experiment run ids must be unique within a group")
        if scope not in {"formal_dev", "regression"}:
            raise ValueError("scope must be formal_dev or regression")
        selected_papers = list(paper_ids or [])
        if len(selected_papers) != len(set(selected_papers)):
            raise ValueError("paper_ids must contain distinct selected papers")
        if scope == "regression" and not selected_papers:
            raise ValueError("regression groups require selected paper_ids")
        with self._lock:
            if self.exists(group_id):
                raise ValueError("experiment group id already exists")
            now = _utc_now()
            group = self._write(
                {
                    "group_id": group_id,
                    "campaign_id": self.campaign_id,
                    "split": "dev",
                    "scope": scope,
                    "paper_ids": selected_papers,
                    "status": "queued",
                    "paused": False,
                    "max_parallel_experiments": max_parallel_experiments,
                    "created_at": now,
                    "experiments": [
                        {
                            "run_id": request["run_id"],
                            "request": request,
                            "status": "queued",
                            "queue_mode": "start",
                            "position": position,
                        }
                        for position, request in enumerate(requests, start=1)
                    ],
                }
            )
            self._emit(
                group_id,
                "group.created",
                status="queued",
                data={"experiments": len(requests), "max_parallel_experiments": max_parallel_experiments},
            )
        return self.tick(group_id)

    def _refresh_experiments(self, group: dict[str, Any]) -> bool:
        changed = False
        for experiment in group.get("experiments", []):
            if experiment.get("status") not in ACTIVE_RUN_STATUSES:
                continue
            try:
                latest = self._status(str(experiment["run_id"]))
            except (OSError, ValueError):
                continue
            next_status = str(latest.get("status") or experiment.get("status") or "failed")
            if next_status != experiment.get("status"):
                experiment["status"] = next_status
                experiment["finished_at"] = latest.get("finished_at")
                experiment["returncode"] = latest.get("returncode")
                self._emit(
                    str(group["group_id"]),
                    "experiment.status.changed",
                    run_id=str(experiment["run_id"]),
                    status=next_status,
                )
                changed = True
        return changed

    def tick(self, group_id: str) -> dict[str, Any]:
        with self._lock:
            group = self._read(group_id)
            changed = self._refresh_experiments(group)
            if not group.get("paused"):
                active = sum(
                    item.get("status") in ACTIVE_RUN_STATUSES
                    for item in group.get("experiments", [])
                )
                slots = max(0, int(group.get("max_parallel_experiments") or 1) - active)
                for experiment in group.get("experiments", []):
                    if slots <= 0:
                        break
                    if experiment.get("status") not in QUEUE_STATUSES:
                        continue
                    resume = experiment.get("queue_mode") == "resume"
                    run_id = str(experiment["run_id"])
                    try:
                        state = self._launch(dict(experiment["request"]), resume)
                    except Exception as exc:
                        experiment["status"] = "failed"
                        experiment["error"] = f"{type(exc).__name__}: {exc}"
                        self._emit(
                            group_id,
                            "experiment.launch.failed",
                            run_id=run_id,
                            status="failed",
                            summary=str(exc),
                        )
                    else:
                        experiment["status"] = str(state.get("status") or "running")
                        experiment["started_at"] = state.get("started_at") or _utc_now()
                        experiment.pop("error", None)
                        self._emit(
                            group_id,
                            "experiment.started" if not resume else "experiment.resumed",
                            run_id=run_id,
                            status=experiment["status"],
                        )
                    slots -= 1
                    changed = True
            next_status = self._derive_status(group)
            if group.get("status") != next_status:
                group["status"] = next_status
                self._emit(group_id, "group.status.changed", status=next_status)
                changed = True
            return self._write(group) if changed else group

    def read(self, group_id: str) -> dict[str, Any]:
        return self.tick(validate_path_segment(group_id, "group id"))

    def list(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        groups: list[dict[str, Any]] = []
        for directory in sorted((item for item in self.root.iterdir() if item.is_dir()), reverse=True):
            try:
                groups.append(self.tick(directory.name))
            except ValueError:
                continue
        groups.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("group_id") or "")), reverse=True)
        return groups

    def stop(self, group_id: str) -> dict[str, Any]:
        with self._lock:
            group = self._read(group_id)
            group["paused"] = True
            for experiment in group.get("experiments", []):
                status = str(experiment.get("status") or "")
                if status in QUEUE_STATUSES:
                    experiment["status"] = "paused"
                elif status == "running":
                    try:
                        self._stop(str(experiment["run_id"]))
                    except ValueError:
                        pass
                    experiment["status"] = "stop_requested"
            group["status"] = "paused"
            self._emit(group_id, "group.paused", status="paused")
            return self._write(group)

    def resume(self, group_id: str) -> dict[str, Any]:
        with self._lock:
            group = self._read(group_id)
            if group.get("scope") == "regression":
                raise ValueError("regression groups cannot resume or retry historical work")
            if not group.get("paused"):
                raise ValueError(
                    "only a manually paused group may resume; failed runs use external-failure paper retry or a new experiment"
                )
            group["paused"] = False
            for experiment in group.get("experiments", []):
                status = str(experiment.get("status") or "")
                if status == "paused":
                    experiment["status"] = "queued"
                elif status in REVIEW_RUN_STATUSES:
                    experiment["status"] = "resume_queued"
                    experiment["queue_mode"] = "resume"
            group["status"] = self._derive_status(group)
            self._emit(group_id, "group.resumed", status=group["status"])
            self._write(group)
        return self.tick(group_id)

    def mark_reset(self, run_id: str) -> None:
        run_id = validate_path_segment(run_id, "run id")
        if not self.root.is_dir():
            return
        with self._lock:
            for directory in (item for item in self.root.iterdir() if item.is_dir()):
                try:
                    group = self._read(directory.name)
                except ValueError:
                    continue
                matched = False
                for experiment in group.get("experiments", []):
                    if experiment.get("run_id") != run_id:
                        continue
                    request = experiment.get("request")
                    position = experiment.get("position")
                    experiment.clear()
                    experiment.update(
                        {
                            "run_id": run_id,
                            "request": request,
                            "status": "paused",
                            "queue_mode": "start",
                            "position": position,
                        }
                    )
                    matched = True
                if matched:
                    group["paused"] = True
                    group["status"] = "paused"
                    self._emit(directory.name, "experiment.reset", run_id=run_id, status="paused")
                    self._write(group)

    def mark_external_retry(self, run_id: str, state: dict[str, Any]) -> None:
        """Attach a directly launched paper repair to any owning group."""

        run_id = validate_path_segment(run_id, "run id")
        if not self.root.is_dir():
            return
        with self._lock:
            for directory in (item for item in self.root.iterdir() if item.is_dir()):
                try:
                    group = self._read(directory.name)
                except ValueError:
                    continue
                matched = False
                for experiment in group.get("experiments", []):
                    if experiment.get("run_id") != run_id:
                        continue
                    experiment["status"] = str(state.get("status") or "running")
                    experiment["started_at"] = state.get("started_at") or _utc_now()
                    experiment["queue_mode"] = "resume"
                    experiment.pop("finished_at", None)
                    experiment.pop("error", None)
                    matched = True
                if matched:
                    group["paused"] = False
                    group["status"] = self._derive_status(group)
                    self._emit(
                        directory.name,
                        "experiment.external_failure_retry.started",
                        run_id=run_id,
                        status="running",
                    )
                    self._write(group)

    def emit(
        self,
        group_id: str,
        event_type: str,
        *,
        run_id: str = "",
        status: str = "",
        summary: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            return self._emit(
                validate_path_segment(group_id, "group id"),
                event_type,
                run_id=run_id,
                status=status,
                summary=summary,
                data=data,
            )

    def events(self, group_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        path = self._events_path(validate_path_segment(group_id, "group id"))
        if not path.is_file():
            return []
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event.get("seq"), int) and event["seq"] > after:
                events.append(event)
        return events

    def _scheduler_loop(self) -> None:
        while not self._shutdown.wait(0.75):
            if not self.root.is_dir():
                continue
            for directory in list(self.root.iterdir()):
                if not directory.is_dir():
                    continue
                try:
                    self.tick(directory.name)
                except Exception:
                    # Persisted groups are isolated: one corrupt or temporarily
                    # unavailable run must not stop scheduling every other group.
                    continue
