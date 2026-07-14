"""Local-only benchmark development console and process controller."""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, BinaryIO, Callable
from urllib.parse import parse_qs, urlparse

from stella.lit.env import env_value
from stella.lit.extraction_rules import assert_generated_rule_views_current
from stella.lit.schema_docs import assert_generated_schema_docs_current
from stella.lit.schema_templates import build_hvs_candidates_template
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, schema_ref

from .campaign import papers_for_split
from .context_pack import pack_paper_context
from .paths import campaign_paths, validate_path_segment
from .run_contract import SUCCESS_STATUSES, git_state, paper_status
from .run_trace import RunTrace


DEFAULT_PORT = 8766
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
TRACE_ROOT_RELATIVE = Path("logs") / "benchmark-dev-console"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_BLOB_RE = re.compile(r"^[0-9a-f]{64}$")

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class DevConsoleError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bounded_int(payload: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise DevConsoleError(f"{key} must be an integer between {low} and {high}")
    return value


def _model(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _MODEL_RE.fullmatch(text):
        raise DevConsoleError(f"{label} is missing or invalid")
    return text


def _string_list(value: Any, label: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list) or len(value) > 8:
        raise DevConsoleError(f"{label} must be a list with at most 8 values")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not pattern.fullmatch(text):
            raise DevConsoleError(f"{label} contains an invalid value")
        if text not in result:
            result.append(text)
    return tuple(result)


@dataclass(frozen=True)
class DevRunRequest:
    method: str
    run_id: str
    extractor_model: str
    reviewer_model: str = "glm-5.2"
    task_surface: str = "full"
    parallel: int = 1
    max_repair_rounds: int = 3
    timeout_seconds: int = 1800
    batch_size: int = 8
    max_tokens: int | None = None
    provider_pin: bool = True
    providers: tuple[str, ...] = field(default_factory=tuple)
    fallback_models: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_payload(cls, payload: Any) -> "DevRunRequest":
        if not isinstance(payload, dict):
            raise DevConsoleError("request body must be a JSON object")
        method = str(payload.get("method") or "").upper()
        if method not in {"B", "C"}:
            raise DevConsoleError("method must be B or C")
        try:
            run_id = validate_path_segment(str(payload.get("run_id") or ""), "run id")
        except ValueError as exc:
            raise DevConsoleError(str(exc)) from exc
        extractor = _model(payload.get("extractor_model"), "extractor_model")
        reviewer = _model(payload.get("reviewer_model", "glm-5.2"), "reviewer_model")
        if extractor == reviewer:
            raise DevConsoleError("extractor and reviewer models must be distinct")
        surface = str(payload.get("task_surface") or "full")
        if surface not in {"full", "core_prov"}:
            raise DevConsoleError("task_surface must be full or core_prov")
        max_tokens = payload.get("max_tokens")
        if max_tokens in (None, ""):
            parsed_max_tokens = None
        elif isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 1_000_000:
            raise DevConsoleError("max_tokens must be empty or an integer between 1 and 1000000")
        else:
            parsed_max_tokens = max_tokens
        return cls(
            method=method,
            run_id=run_id,
            extractor_model=extractor,
            reviewer_model=reviewer,
            task_surface=surface,
            parallel=_bounded_int(payload, "parallel", 1, 1, 10),
            max_repair_rounds=_bounded_int(payload, "max_repair_rounds", 3, 0, 10),
            timeout_seconds=_bounded_int(payload, "timeout_seconds", 1800, 30, 3600),
            batch_size=_bounded_int(payload, "batch_size", 8, 1, 32),
            max_tokens=parsed_max_tokens,
            provider_pin=bool(payload.get("provider_pin", True)),
            providers=_string_list(payload.get("providers"), "providers", _PROVIDER_RE),
            fallback_models=_string_list(payload.get("fallback_models"), "fallback_models", _MODEL_RE),
        )

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["providers"] = list(self.providers)
        payload["fallback_models"] = list(self.fallback_models)
        return payload


def build_runner_command(workspace: Path, logs_root: Path, request: DevRunRequest) -> list[str]:
    script = "run_benchmark_extraction.py" if request.method == "B" else "run_agentic_extraction.py"
    command = [
        sys.executable,
        str(workspace / "scripts" / script),
        "--campaign",
        ACTIVE_BENCHMARK_CAMPAIGN,
        "--split",
        "dev",
        "--run-id",
        request.run_id,
        "--model",
        request.extractor_model,
        "--reviewer-model",
        request.reviewer_model,
        "--task-surface",
        request.task_surface,
        "--parallel",
        str(request.parallel),
        "--max-repair-rounds",
        str(request.max_repair_rounds),
        "--timeout-seconds",
        str(request.timeout_seconds),
        "--trace-root",
        str(logs_root),
    ]
    if request.method == "B":
        command.extend(["--batch-size", str(request.batch_size)])
        if request.max_tokens is not None:
            command.extend(["--max-tokens", str(request.max_tokens)])
        if not request.provider_pin:
            command.append("--no-provider-pin")
        for provider in request.providers:
            command.extend(["--provider", provider])
        for model in request.fallback_models:
            command.extend(["--fallback-model", model])
    return command


class DevConsoleController:
    def __init__(
        self,
        workspace: Path,
        *,
        logs_root: Path | None = None,
        popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    ) -> None:
        self.workspace = workspace.resolve()
        self.logs_root = (logs_root or self.workspace / TRACE_ROOT_RELATIVE).resolve()
        self.assets_root = self.workspace / "src" / "stella" / "web" / "assets"
        self.session_token = secrets.token_urlsafe(32)
        self._popen_factory = popen_factory
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[Any]] = {}

    @property
    def campaign_id(self) -> str:
        return ACTIVE_BENCHMARK_CAMPAIGN

    def _campaign(self) -> dict[str, Any]:
        path = campaign_paths(self.workspace, self.campaign_id).campaign_manifest
        return json.loads(path.read_text(encoding="utf-8"))

    def dev_papers(self) -> list[str]:
        return papers_for_split(self._campaign(), "dev")

    def _trace_root_for(self, campaign_id: str, run_id: str) -> Path:
        campaign = validate_path_segment(campaign_id, "campaign id")
        run = validate_path_segment(run_id, "run id")
        return self.logs_root / campaign / run

    def _state_path(self, run_id: str) -> Path:
        return self._trace_root_for(self.campaign_id, run_id) / "controller.json"

    def _run_lock_path(self, run_id: str) -> Path:
        return self._trace_root_for(self.campaign_id, run_id) / "runner.lock"

    def _acquire_run_lock(self, run_id: str) -> BinaryIO:
        path = self._run_lock_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("a+b")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            stream.close()
            raise DevConsoleError("run already has an active process") from None
        return stream

    def _run_lock_held(self, run_id: str) -> bool:
        path = self._run_lock_path(run_id)
        if not path.is_file():
            return False
        stream = path.open("a+b")
        try:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return False
        finally:
            stream.close()

    @staticmethod
    def _process_group_alive(pgid: Any) -> bool:
        try:
            group = int(pgid)
        except (TypeError, ValueError):
            return False
        if group <= 1:
            return False
        try:
            os.killpg(group, 0)
        except (ProcessLookupError, PermissionError):
            return False
        return True

    def _read_state(self, run_id: str) -> dict[str, Any] | None:
        path = self._state_path(run_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_state(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = self._state_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"schema": schema_ref("benchmark.dev_console_state"), **payload}
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

    def _terminal_status_from_archive(self, run_id: str) -> str:
        run_dir = campaign_paths(self.workspace, self.campaign_id).runs / run_id
        config_path = run_dir / "run_config.json"
        if not config_path.is_file():
            return "failed"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "failed"
        papers = config.get("expected_papers") or config.get("papers") or []
        if not isinstance(papers, list) or not papers:
            return "failed"
        statuses = [paper_status(run_dir / str(paper)) for paper in papers]
        return "completed" if all(status in SUCCESS_STATUSES for status in statuses) else "failed"

    def _reconcile_state(self, run_id: str) -> dict[str, Any] | None:
        state = self._read_state(run_id)
        if not state or state.get("status") not in {"running", "stop_requested"}:
            return state
        process = self._processes.get(run_id)
        if process is not None and process.poll() is None:
            return state
        pgid = state.get("pgid") or state.get("pid")
        if self._process_group_alive(pgid) or self._run_lock_held(run_id):
            return state
        state.update(
            {
                "status": "stopped"
                if state.get("status") == "stop_requested"
                else self._terminal_status_from_archive(run_id),
                "finished_at": state.get("finished_at") or _utc_now(),
                "reconciled_after_restart": True,
            }
        )
        return self._write_state(
            run_id, {key: value for key, value in state.items() if key != "schema"}
        )

    def _active_process_group(self, run_id: str) -> int | None:
        state = self._reconcile_state(run_id)
        if not state or state.get("status") not in {"running", "stop_requested"}:
            return None
        pgid = state.get("pgid") or state.get("pid")
        if self._process_group_alive(pgid) or self._run_lock_held(run_id):
            try:
                return int(pgid)
            except (TypeError, ValueError):
                return None
        return None

    def inferred_models(self) -> list[str]:
        values = [env_value("LLM_MODEL"), "deepseek-v4-pro", "mimo-v2.5-pro", "glm-5.2"]
        for run in self.list_runs():
            values.extend([run.get("extractor_model", ""), run.get("reviewer_model", "")])
        return list(dict.fromkeys(value for value in values if value))

    def bootstrap(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "split": "dev",
            "papers": self.dev_papers(),
            "models": self.inferred_models(),
            "defaults": {
                "reviewer_model": "glm-5.2",
                "task_surface": "full",
                "parallel": 1,
                "max_repair_rounds": 3,
                "timeout_seconds": 1800,
                "batch_size": 8,
                "provider_pin": True,
            },
            "credentials": {
                "api_key_configured": bool(env_value("LLM_API_KEY")),
                "base_url_configured": bool(env_value("LLM_BASE_URL")),
            },
            "session_token": self.session_token,
        }

    def preflight(self, request: DevRunRequest) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": bool(ok), "detail": detail})

        campaign = self._campaign()
        check("campaign", campaign.get("campaign_id") == self.campaign_id, self.campaign_id)
        papers = papers_for_split(campaign, "dev")
        check("dev split", len(papers) == 10, f"{len(papers)} papers")
        code = git_state(self.workspace)
        check("clean worktree", code["dirty"] is False, code["commit"][:12])
        try:
            assert_generated_rule_views_current(self.workspace)
            rule_detail, rule_ok = "current", True
        except Exception as exc:
            rule_detail, rule_ok = str(exc), False
        check("rule views", rule_ok, rule_detail)
        try:
            assert_generated_schema_docs_current(self.workspace)
            schema_detail, schema_ok = "current", True
        except Exception as exc:
            schema_detail, schema_ok = str(exc), False
        check("schema views", schema_ok, schema_detail)
        input_errors: list[str] = []
        for arxiv_id in papers:
            try:
                skeleton = build_hvs_candidates_template(
                    literature_dir=self.workspace / "literature",
                    arxiv_id=arxiv_id,
                    workspace=self.workspace,
                )
                packed = pack_paper_context(
                    self.workspace,
                    arxiv_id,
                    list(skeleton["inputs"]["ecsv_paths"]),
                )
                if not any(item.kind == "paper_text" for item in packed.files):
                    raise DevConsoleError("no TeX paper text found in arxiv_source")
            except Exception as exc:
                input_errors.append(f"{arxiv_id}: {exc}")
        check(
            "paper context packs",
            not input_errors,
            "ready" if not input_errors else "; ".join(input_errors[:3]),
        )
        check("LLM_API_KEY", bool(env_value("LLM_API_KEY")), "configured" if env_value("LLM_API_KEY") else "missing")
        check("LLM_BASE_URL", bool(env_value("LLM_BASE_URL")), "configured" if env_value("LLM_BASE_URL") else "missing")
        run_dir = campaign_paths(self.workspace, self.campaign_id).runs / request.run_id
        check("run is open", not (run_dir / "run_manifest.json").exists(), str(run_dir))
        check(
            "no active process",
            self._active_process_group(request.run_id) is None
            and not self._run_lock_held(request.run_id),
            request.run_id,
        )
        command = build_runner_command(self.workspace, self.logs_root, request)
        return {
            "ok": all(item["ok"] for item in checks),
            "checks": checks,
            "command": command,
            "request": request.public_dict(),
        }

    def start(self, request: DevRunRequest, *, resume: bool = False) -> dict[str, Any]:
        preflight = self.preflight(request)
        if not preflight["ok"]:
            raise DevConsoleError("preflight failed")
        with self._lock:
            if self._active_process_group(request.run_id) is not None:
                raise DevConsoleError("run already has an active process")
            run_lock = self._acquire_run_lock(request.run_id)
            trace_root = self._trace_root_for(self.campaign_id, request.run_id)
            trace_root.mkdir(parents=True, exist_ok=True)
            log_path = trace_root / "runner.log"
            stream = log_path.open("ab", buffering=0)
            try:
                try:
                    process = self._popen_factory(
                        preflight["command"],
                        cwd=self.workspace,
                        env=dict(os.environ),
                        shell=False,
                        start_new_session=True,
                        pass_fds=(run_lock.fileno(),),
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                    )
                except Exception:
                    fcntl.flock(run_lock.fileno(), fcntl.LOCK_UN)
                    raise
            finally:
                stream.close()
                run_lock.close()
            self._processes[request.run_id] = process
            state = self._write_state(
                request.run_id,
                {
                    "campaign_id": self.campaign_id,
                    "run_id": request.run_id,
                    "status": "running",
                    "resume": bool(resume),
                    "pid": process.pid,
                    "pgid": process.pid,
                    "started_at": _utc_now(),
                    "request": request.public_dict(),
                    "command": preflight["command"],
                    "runner_log": str(log_path),
                },
            )
            threading.Thread(
                target=self._monitor_process,
                args=(request.run_id, process),
                daemon=True,
            ).start()
            return state

    def _monitor_process(self, run_id: str, process: subprocess.Popen[Any]) -> None:
        returncode = process.wait()
        with self._lock:
            state = self._read_state(run_id) or {"run_id": run_id, "campaign_id": self.campaign_id}
            requested_stop = state.get("status") == "stop_requested"
            state.update(
                {
                    "status": "stopped" if requested_stop else ("completed" if returncode == 0 else "failed"),
                    "returncode": returncode,
                    "finished_at": _utc_now(),
                }
            )
            self._write_state(run_id, {key: value for key, value in state.items() if key != "schema"})
            self._processes.pop(run_id, None)

    def stop(self, run_id: str) -> dict[str, Any]:
        run_id = validate_path_segment(run_id, "run id")
        with self._lock:
            pgid = self._active_process_group(run_id)
            if pgid is None:
                raise DevConsoleError("run is no longer running")
            state = self._reconcile_state(run_id) or {
                "campaign_id": self.campaign_id,
                "run_id": run_id,
            }
            state.update({"status": "stop_requested", "stop_requested_at": _utc_now()})
            self._write_state(run_id, {key: value for key, value in state.items() if key != "schema"})
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            threading.Thread(
                target=self._force_stop_group_after_grace,
                args=(pgid,),
                daemon=True,
            ).start()
            return self._read_state(run_id) or state

    @staticmethod
    def _force_stop_group_after_grace(pgid: int) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            except PermissionError:
                return
            time.sleep(0.1)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def resume(self, run_id: str) -> dict[str, Any]:
        state = self._reconcile_state(validate_path_segment(run_id, "run id"))
        if not state or not isinstance(state.get("request"), dict):
            raise DevConsoleError("no saved console request exists for this run")
        return self.start(DevRunRequest.from_payload(state["request"]), resume=True)

    def _infer_run(self, campaign_id: str, run_dir: Path) -> dict[str, Any]:
        config_path = run_dir / "run_config.json"
        config: dict[str, Any] = {}
        if config_path.is_file():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                config = {}
        method_data = config.get("method") if isinstance(config.get("method"), dict) else {}
        producer = str(method_data.get("producer") or config.get("pipeline") or "")
        if "agentic" in producer:
            method = "C"
        elif "skill-agent" in producer:
            method = "A"
        elif "extraction" in producer:
            method = "B"
        else:
            method = "unknown"
        models = method_data.get("models") if isinstance(method_data.get("models"), dict) else {}
        papers = config.get("expected_papers") or config.get("papers") or []
        reports: dict[str, str] = {}
        usage: dict[str, int] = {}
        for paper in papers if isinstance(papers, list) else []:
            paper_id = str(paper)
            reports[paper_id] = paper_status(run_dir / paper_id)
            report_path = run_dir / paper_id / "report.json"
            if report_path.is_file():
                try:
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    report = {}
                for key, value in (report.get("usage_totals") or {}).items():
                    if isinstance(value, int):
                        usage[key] = usage.get(key, 0) + value
        state = self._reconcile_state(run_dir.name) if campaign_id == self.campaign_id else None
        saved_request = (
            state.get("request")
            if state and isinstance(state.get("request"), dict)
            else {}
        )
        if method == "unknown" and saved_request.get("method") in {"B", "C"}:
            method = str(saved_request["method"])
        if not papers and state:
            papers = self.dev_papers()
        if state:
            status = str(state.get("status") or "unknown")
        elif (run_dir / "run_manifest.json").is_file():
            status = "sealed"
        elif reports and all(value in SUCCESS_STATUSES for value in reports.values()):
            status = "completed"
        elif reports:
            status = "partial"
        else:
            status = "unknown"
        trace_events = self._trace_root_for(campaign_id, run_dir.name) / "events.jsonl"
        read_only = campaign_id != self.campaign_id or method not in {"B", "C"}
        controllable = bool(
            campaign_id == self.campaign_id
            and status in {"running", "stop_requested"}
            and self._active_process_group(run_dir.name) is not None
        )
        resumable = bool(
            not read_only
            and status in {"stopped", "failed", "partial"}
            and state
            and isinstance(state.get("request"), dict)
        )
        return {
            "campaign_id": campaign_id,
            "run_id": run_dir.name,
            "method": method,
            "status": status,
            "created_at": str((state or {}).get("started_at") or config.get("created_at") or ""),
            "finished_at": str((state or {}).get("finished_at") or ""),
            "extractor_model": str(
                models.get("extractor")
                or config.get("model")
                or saved_request.get("extractor_model")
                or ""
            ),
            "reviewer_model": str(
                models.get("reviewer")
                or config.get("reviewer_model")
                or saved_request.get("reviewer_model")
                or ""
            ),
            "task_surface": str(
                (method_data.get("parameters") or {}).get("task_surface")
                or saved_request.get("task_surface")
                or "full"
            ),
            "papers": list(papers) if isinstance(papers, list) else [],
            "paper_statuses": reports,
            "usage_totals": usage,
            "trace_precision": "exact" if trace_events.is_file() else "legacy_synthesized",
            "read_only": read_only,
            "controllable": controllable,
            "resumable": resumable,
        }

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        campaigns_root = self.workspace / "benchmark" / "campaigns"
        for campaign_dir in sorted(campaigns_root.glob("*")):
            runs_dir = campaign_dir / "runs"
            if not runs_dir.is_dir():
                continue
            for run_dir in sorted((path for path in runs_dir.iterdir() if path.is_dir()), reverse=True):
                runs.append(self._infer_run(campaign_dir.name, run_dir))
        runs.sort(key=lambda item: (item.get("created_at", ""), item["run_id"]), reverse=True)
        return runs

    def run_detail(self, campaign_id: str, run_id: str) -> dict[str, Any]:
        campaign = validate_path_segment(campaign_id, "campaign id")
        run = validate_path_segment(run_id, "run id")
        run_dir = self.workspace / "benchmark" / "campaigns" / campaign / "runs" / run
        if not run_dir.is_dir():
            raise DevConsoleError("run does not exist")
        summary = self._infer_run(campaign, run_dir)
        config_path = run_dir / "run_config.json"
        summary["run_config"] = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
        return summary

    def run_status(self, campaign_id: str, run_id: str) -> dict[str, Any]:
        campaign = validate_path_segment(campaign_id, "campaign id")
        run = validate_path_segment(run_id, "run id")
        run_dir = self.workspace / "benchmark" / "campaigns" / campaign / "runs" / run
        if run_dir.is_dir():
            return self._infer_run(campaign, run_dir)
        if campaign != self.campaign_id:
            raise DevConsoleError("run does not exist")
        state = self._reconcile_state(run)
        if not state:
            raise DevConsoleError("run does not exist")
        request = state.get("request") if isinstance(state.get("request"), dict) else {}
        status = str(state.get("status") or "unknown")
        return {
            "campaign_id": campaign,
            "run_id": run,
            "method": str(request.get("method") or "unknown"),
            "status": status,
            "created_at": str(state.get("started_at") or ""),
            "finished_at": str(state.get("finished_at") or ""),
            "papers": self.dev_papers(),
            "paper_statuses": {},
            "usage_totals": {},
            "trace_precision": "exact",
            "read_only": False,
            "controllable": status in {"running", "stop_requested"}
            and self._active_process_group(run) is not None,
            "resumable": status in {"stopped", "failed", "partial"}
            and bool(request),
        }

    def events(self, campaign_id: str, run_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        campaign = validate_path_segment(campaign_id, "campaign id")
        run = validate_path_segment(run_id, "run id")
        trace = RunTrace(
            self.logs_root,
            campaign_id=campaign,
            run_id=run,
            method="unknown",
            create=False,
        )
        exact = trace.read_events(after=after)
        if exact or trace.events_path.is_file():
            return exact
        run_dir = self.workspace / "benchmark" / "campaigns" / campaign / "runs" / run
        synthesized: list[tuple[float, dict[str, Any]]] = []
        for paper_dir in sorted(path for path in run_dir.iterdir() if path.is_dir()) if run_dir.is_dir() else []:
            attempts = paper_dir / "attempts"
            if attempts.is_dir():
                for path in attempts.glob("*.json"):
                    event_type = "legacy.llm.response" if path.name.endswith(".response.json") else "legacy.llm.request"
                    synthesized.append(
                        (
                            path.stat().st_mtime,
                            {
                                "type": event_type,
                                "paper_id": paper_dir.name,
                                "stage": path.name.split("-call-")[0],
                                "summary": path.name,
                                "data": {"legacy_artifact": f"attempts/{path.name}"},
                            },
                        )
                    )
            report = paper_dir / "report.json"
            if report.is_file():
                synthesized.append(
                    (
                        report.stat().st_mtime,
                        {
                            "type": "paper.completed",
                            "paper_id": paper_dir.name,
                            "stage": "final",
                            "status": paper_status(paper_dir),
                            "data": {"legacy_artifact": "report.json"},
                        },
                    )
                )
        events: list[dict[str, Any]] = []
        for seq, (mtime, item) in enumerate(sorted(synthesized, key=lambda pair: pair[0]), 1):
            if seq <= after:
                continue
            events.append(
                {
                    "schema": schema_ref("benchmark.run_event"),
                    "seq": seq,
                    "occurred_at": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                    "campaign_id": campaign,
                    "run_id": run,
                    "method": "unknown",
                    "synthetic": True,
                    **item,
                }
            )
        return events

    def read_blob(self, campaign_id: str, run_id: str, digest: str) -> dict[str, Any]:
        if not _BLOB_RE.fullmatch(digest):
            raise DevConsoleError("invalid blob hash")
        return RunTrace(
            self.logs_root,
            campaign_id=validate_path_segment(campaign_id, "campaign id"),
            run_id=validate_path_segment(run_id, "run id"),
            method="unknown",
            create=False,
        ).read_blob(digest)

    def read_artifact(self, campaign_id: str, run_id: str, paper_id: str, name: str) -> Any:
        campaign = validate_path_segment(campaign_id, "campaign id")
        run = validate_path_segment(run_id, "run id")
        paper = validate_path_segment(paper_id, "paper id")
        allowed = {"report.json", "context_manifest.json", "literature_hvs_candidates.json", "review.json"}
        if name.startswith("attempts/"):
            basename = name.removeprefix("attempts/")
            if "/" in basename or not basename.endswith((".request.json", ".response.json")):
                raise DevConsoleError("artifact is not allowlisted")
            relative = Path("attempts") / basename
        elif name in allowed:
            relative = Path(name)
        else:
            raise DevConsoleError("artifact is not allowlisted")
        path = self.workspace / "benchmark" / "campaigns" / campaign / "runs" / run / paper / relative
        if not path.is_file():
            raise DevConsoleError("artifact does not exist")
        return json.loads(path.read_text(encoding="utf-8"))


def _send_security_headers(handler: BaseHTTPRequestHandler) -> None:
    for name, value in SECURITY_HEADERS.items():
        handler.send_header(name, value)


def _json_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    _send_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(controller: DevConsoleController) -> type[BaseHTTPRequestHandler]:
    class DevConsoleHandler(BaseHTTPRequestHandler):
        server_version = "StellaDevConsole/1"

        def _segments(self) -> tuple[list[str], dict[str, list[str]]]:
            parsed = urlparse(self.path)
            return [segment for segment in parsed.path.split("/") if segment], parse_qs(parsed.query)

        def _allowed_hosts(self) -> set[str]:
            port = int(self.server.server_address[1])
            return {f"127.0.0.1:{port}", f"localhost:{port}"}

        def _validate_host(self) -> None:
            host = self.headers.get("Host", "").strip().lower()
            if host not in self._allowed_hosts():
                raise DevConsoleError("invalid Host header for loopback console")

        def _read_json(self) -> dict[str, Any]:
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                raise DevConsoleError("Content-Type must be application/json")
            if self.headers.get("X-Stella-Console-Token") != controller.session_token:
                raise DevConsoleError("invalid console session token")
            origin = self.headers.get("Origin")
            if origin:
                allowed_origins = {f"http://{host}" for host in self._allowed_hosts()}
                if origin.lower() not in allowed_origins:
                    raise DevConsoleError("cross-origin mutation is not allowed")
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1_000_000:
                raise DevConsoleError("request body is too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise DevConsoleError("request body must be a JSON object")
            return payload

        def _serve_asset(self, name: str, content_type: str) -> None:
            path = controller.assets_root / name
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            _send_security_headers(self)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._validate_host()
                segments, query = self._segments()
                if not segments:
                    self._serve_asset("benchmark-console.html", "text/html; charset=utf-8")
                    return
                if segments == ["assets", "benchmark-console.css"]:
                    self._serve_asset("benchmark-console.css", "text/css; charset=utf-8")
                    return
                if segments == ["assets", "benchmark-console.js"]:
                    self._serve_asset("benchmark-console.js", "text/javascript; charset=utf-8")
                    return
                if segments == ["api", "bootstrap"]:
                    _json_response(self, HTTPStatus.OK, controller.bootstrap())
                    return
                if segments == ["api", "runs"]:
                    _json_response(self, HTTPStatus.OK, {"runs": controller.list_runs()})
                    return
                if len(segments) == 4 and segments[:2] == ["api", "runs"]:
                    _json_response(self, HTTPStatus.OK, controller.run_detail(segments[2], segments[3]))
                    return
                if len(segments) == 5 and segments[:2] == ["api", "runs"] and segments[4] == "status":
                    _json_response(self, HTTPStatus.OK, controller.run_status(segments[2], segments[3]))
                    return
                if len(segments) == 5 and segments[:2] == ["api", "runs"] and segments[4] == "events":
                    self._serve_events(segments[2], segments[3], query)
                    return
                if len(segments) == 6 and segments[:2] == ["api", "runs"] and segments[4] == "blobs":
                    _json_response(self, HTTPStatus.OK, controller.read_blob(segments[2], segments[3], segments[5]))
                    return
                if len(segments) == 5 and segments[:2] == ["api", "runs"] and segments[4] == "artifact":
                    paper = str((query.get("paper") or [""])[0])
                    name = str((query.get("name") or [""])[0])
                    _json_response(self, HTTPStatus.OK, controller.read_artifact(segments[2], segments[3], paper, name))
                    return
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "route not found"})
            except (DevConsoleError, ValueError, OSError, json.JSONDecodeError) as exc:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def _serve_events(self, campaign_id: str, run_id: str, query: dict[str, list[str]]) -> None:
            after = int((query.get("after") or [self.headers.get("Last-Event-ID", "0")])[0] or 0)
            once = (query.get("once") or ["0"])[0] == "1"
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close" if once else "keep-alive")
            _send_security_headers(self)
            self.end_headers()
            if once:
                self.close_connection = True
            deadline = time.monotonic() + (0 if once else 30)
            try:
                while True:
                    events = controller.events(campaign_id, run_id, after=after)
                    for event in events:
                        after = max(after, int(event["seq"]))
                        data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                        self.wfile.write(f"id: {event['seq']}\nevent: trace\ndata: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    if once or time.monotonic() >= deadline:
                        return
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    time.sleep(0.75)
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._validate_host()
                segments, _ = self._segments()
                payload = self._read_json()
                if segments == ["api", "preflight"]:
                    _json_response(self, HTTPStatus.OK, controller.preflight(DevRunRequest.from_payload(payload)))
                    return
                if segments == ["api", "runs"]:
                    _json_response(self, HTTPStatus.ACCEPTED, controller.start(DevRunRequest.from_payload(payload)))
                    return
                if len(segments) == 4 and segments[:2] == ["api", "runs"] and segments[3] == "stop":
                    _json_response(self, HTTPStatus.ACCEPTED, controller.stop(segments[2]))
                    return
                if len(segments) == 4 and segments[:2] == ["api", "runs"] and segments[3] == "resume":
                    _json_response(self, HTTPStatus.ACCEPTED, controller.resume(segments[2]))
                    return
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "route not found"})
            except (DevConsoleError, ValueError, OSError, json.JSONDecodeError) as exc:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:
            if os.environ.get("STELLA_DEV_CONSOLE_QUIET"):
                return
            super().log_message(format, *args)

    return DevConsoleHandler


def create_server(host: str, port: int, controller: DevConsoleController) -> ThreadingHTTPServer:
    if host not in LOOPBACK_HOSTS:
        raise DevConsoleError("benchmark dev console may bind only to a loopback host")
    return ThreadingHTTPServer((host, port), make_handler(controller))
