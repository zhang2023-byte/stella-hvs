"""Local-only benchmark development console and process controller."""

from __future__ import annotations

import fcntl
import json
import mimetypes
import os
import re
import secrets
import signal
import shutil
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
from .dev_console_evaluation import DevEvaluationService
from .dev_console_groups import ExperimentGroupStore
from .method_policy import (
    PRIMARY_DIRECT_METHOD,
    PRIMARY_TASK_SURFACE,
    require_legacy_opt_in,
)
from .paths import campaign_paths, validate_path_segment
from .run_contract import (
    EXTERNAL_RETRY_STATUSES,
    SUCCESS_STATUSES,
    external_failure_retry_eligibility,
    git_state,
    paper_status,
)
from .run_trace import RunTrace


DEFAULT_PORT = 8766
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
TRACE_ROOT_RELATIVE = Path("logs") / "benchmark-dev-console"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_BLOB_RE = re.compile(r"^[0-9a-f]{64}$")

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
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
    experiment_name: str = ""
    reviewer_model: str = "glm-5.2"
    task_surface: str = "core_prov"
    parallel: int = 1
    max_repair_rounds: int = 3
    timeout_seconds: int = 1800
    batch_size: int = 8
    max_tokens: int | None = None
    provider_pin: bool = True
    providers: tuple[str, ...] = field(default_factory=tuple)
    fallback_models: tuple[str, ...] = field(default_factory=tuple)
    stream_responses: bool = False
    scope: str = "formal_dev"
    paper_ids: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_payload(cls, payload: Any) -> "DevRunRequest":
        if not isinstance(payload, dict):
            raise DevConsoleError("request body must be a JSON object")
        method = str(payload.get("method") or "").upper()
        surface = str(payload.get("task_surface") or PRIMARY_TASK_SURFACE)
        try:
            require_legacy_opt_in(method=method, task_surface=surface)
        except ValueError as exc:
            raise DevConsoleError(str(exc)) from exc
        try:
            run_id = validate_path_segment(str(payload.get("run_id") or ""), "run id")
        except ValueError as exc:
            raise DevConsoleError(str(exc)) from exc
        extractor = _model(payload.get("extractor_model"), "extractor_model")
        reviewer = _model(payload.get("reviewer_model", "glm-5.2"), "reviewer_model")
        if extractor == reviewer:
            raise DevConsoleError("extractor and reviewer models must be distinct")
        experiment_name = str(payload.get("experiment_name") or run_id).strip()
        if not experiment_name or len(experiment_name) > 80 or any(ord(character) < 32 for character in experiment_name):
            raise DevConsoleError("experiment_name must be a non-empty label with at most 80 characters")
        max_tokens = payload.get("max_tokens")
        if max_tokens in (None, ""):
            parsed_max_tokens = None
        elif isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 1_000_000:
            raise DevConsoleError("max_tokens must be empty or an integer between 1 and 1000000")
        else:
            parsed_max_tokens = max_tokens
        scope = str(payload.get("scope") or "formal_dev")
        if scope not in {"formal_dev", "regression"}:
            raise DevConsoleError("scope must be formal_dev or regression")
        if surface != PRIMARY_TASK_SURFACE:
            raise DevConsoleError("new dev experiments require task_surface core_prov")
        raw_papers = payload.get("paper_ids")
        if raw_papers in (None, "", []):
            paper_ids: tuple[str, ...] = ()
        elif not isinstance(raw_papers, list) or not 1 <= len(raw_papers) <= 10:
            raise DevConsoleError("paper_ids must contain between 1 and 10 papers")
        else:
            try:
                paper_ids = tuple(
                    validate_path_segment(str(value or ""), "paper id")
                    for value in raw_papers
                )
            except ValueError as exc:
                raise DevConsoleError(str(exc)) from exc
            if len(paper_ids) != len(set(paper_ids)):
                raise DevConsoleError("paper_ids must be distinct")
        return cls(
            method=method,
            run_id=run_id,
            extractor_model=extractor,
            experiment_name=experiment_name,
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
            # Dev Console runs intentionally use whole responses. Keep the
            # field in persisted requests for schema compatibility, but never
            # allow a browser or an older saved request to re-enable streaming.
            stream_responses=False,
            scope=scope,
            paper_ids=paper_ids,
        )

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["providers"] = list(self.providers)
        payload["fallback_models"] = list(self.fallback_models)
        payload["paper_ids"] = list(self.paper_ids)
        return payload


def build_runner_command(
    workspace: Path,
    logs_root: Path,
    request: DevRunRequest,
    *,
    retry_external_papers: tuple[str, ...] = (),
) -> list[str]:
    try:
        require_legacy_opt_in(
            method=request.method,
            task_surface=request.task_surface,
        )
    except ValueError as exc:
        raise DevConsoleError(str(exc)) from exc
    script = "run_benchmark_extraction.py"
    command = [
        sys.executable,
        str(workspace / "scripts" / script),
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
    if request.scope == "regression":
        command.extend(
            [
                "--runs-dir",
                str(campaign_paths(workspace, ACTIVE_BENCHMARK_CAMPAIGN).runs),
                "--trace-campaign-id",
                ACTIVE_BENCHMARK_CAMPAIGN,
            ]
        )
        for paper_id in request.paper_ids:
            command.extend(["--arxiv-id", validate_path_segment(paper_id, "paper id")])
    else:
        command.extend(
            [
                "--campaign",
                ACTIVE_BENCHMARK_CAMPAIGN,
                "--split",
                "dev",
            ]
        )
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
    for paper_id in retry_external_papers:
        command.extend(
            [
                "--retry-external-paper",
                validate_path_segment(paper_id, "paper id"),
            ]
        )
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
        self._trace_readers: dict[tuple[str, str], RunTrace] = {}
        self.groups = ExperimentGroupStore(
            self.logs_root,
            campaign_id=self.campaign_id,
            launch=self._launch_group_request,
            stop=self.stop,
            status=lambda run_id: self.run_status(self.campaign_id, run_id),
        )
        self.evaluations = DevEvaluationService(
            self.workspace,
            groups=self.groups,
            campaign_id=self.campaign_id,
        )

    def close(self) -> None:
        self.groups.close()

    def _launch_group_request(self, payload: dict[str, Any], resume: bool) -> dict[str, Any]:
        request = DevRunRequest.from_payload(payload)
        if resume:
            return self.resume(request.run_id)
        return self.start(request)

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
                "task_surface": "core_prov",
                "parallel": 1,
                "max_repair_rounds": 3,
                "timeout_seconds": 1800,
                "batch_size": 8,
                "provider_pin": True,
                "max_parallel_experiments": 2,
            },
            "credentials": {
                "api_key_configured": bool(env_value("LLM_API_KEY")),
                "base_url_configured": bool(env_value("LLM_BASE_URL")),
            },
            "session_token": self.session_token,
            "capabilities": {
                "experiment_groups": True,
                "local_dev_evaluation": True,
                "streaming_responses": False,
                "checkpoint_granularity": "paper",
            },
        }

    def group_preflight(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise DevConsoleError("request body must be a JSON object")
        try:
            group_id = validate_path_segment(str(payload.get("group_id") or ""), "group id")
        except ValueError as exc:
            raise DevConsoleError(str(exc)) from exc
        max_parallel = _bounded_int(payload, "max_parallel_experiments", 2, 1, 4)
        scope = str(payload.get("scope") or "formal_dev")
        if scope not in {"formal_dev", "regression"}:
            raise DevConsoleError("scope must be formal_dev or regression")
        dev_papers = self.dev_papers()
        raw_papers = payload.get("paper_ids")
        if scope == "formal_dev":
            if raw_papers not in (None, [], dev_papers):
                raise DevConsoleError("formal_dev must use the exact full 10-paper dev split")
            paper_ids = list(dev_papers)
        else:
            if not isinstance(raw_papers, list) or not 1 <= len(raw_papers) <= len(dev_papers):
                raise DevConsoleError("regression paper_ids must select 1-10 dev papers")
            requested = [str(value or "") for value in raw_papers]
            if len(requested) != len(set(requested)):
                raise DevConsoleError("regression paper_ids must be distinct")
            invalid = [paper_id for paper_id in requested if paper_id not in dev_papers]
            if invalid:
                raise DevConsoleError(
                    "regression may select only active dev papers: " + ", ".join(invalid)
                )
            paper_ids = [paper_id for paper_id in dev_papers if paper_id in requested]
        values = payload.get("experiments")
        if not isinstance(values, list) or not 1 <= len(values) <= 20:
            raise DevConsoleError("experiments must contain between 1 and 20 run configurations")
        requests = [
            DevRunRequest.from_payload(
                {**value, "scope": scope, "paper_ids": paper_ids}
                if isinstance(value, dict)
                else value
            )
            for value in values
        ]
        run_ids = [request.run_id for request in requests]
        if len(run_ids) != len(set(run_ids)):
            raise DevConsoleError("experiment run ids must be unique within a group")
        results = [self.preflight(request) for request in requests]
        group_open = not self.groups.exists(group_id)
        group_checks = [
            {"name": "group id is open", "ok": group_open, "detail": group_id},
            {
                "name": "experiment concurrency",
                "ok": True,
                "detail": f"{max_parallel} active experiment(s); up to {sum(request.parallel for request in requests[:max_parallel])} paper workers initially",
            },
            {
                "name": "paper scope",
                "ok": True,
                "detail": f"{scope}: {len(paper_ids)} paper(s)",
            },
        ]
        return {
            "ok": group_open and all(result["ok"] for result in results),
            "group_id": group_id,
            "max_parallel_experiments": max_parallel,
            "group_checks": group_checks,
            "experiments": [
                {"run_id": request.run_id, **result}
                for request, result in zip(requests, results, strict=True)
            ],
            "request": {
                "group_id": group_id,
                "scope": scope,
                "paper_ids": paper_ids,
                "max_parallel_experiments": max_parallel,
                "experiments": [request.public_dict() for request in requests],
            },
        }

    def create_group(self, payload: Any) -> dict[str, Any]:
        preflight = self.group_preflight(payload)
        if not preflight["ok"]:
            raise DevConsoleError("experiment group preflight failed")
        request = preflight["request"]
        try:
            return self.groups.create(
                group_id=request["group_id"],
                scope=request["scope"],
                paper_ids=request["paper_ids"],
                max_parallel_experiments=request["max_parallel_experiments"],
                requests=request["experiments"],
            )
        except ValueError as exc:
            raise DevConsoleError(str(exc)) from exc

    @staticmethod
    def _request_from_run_config(run_id: str, config: dict[str, Any]) -> DevRunRequest:
        method_data = config.get("method") if isinstance(config.get("method"), dict) else {}
        producer = str(method_data.get("producer") or "")
        if "agentic" in producer:
            method = "C"
        elif "extraction" in producer:
            method = "B"
        else:
            raise DevConsoleError("only Method B/C formal runs support external failure retry")
        models = method_data.get("models") if isinstance(method_data.get("models"), dict) else {}
        parameters = (
            method_data.get("parameters")
            if isinstance(method_data.get("parameters"), dict)
            else {}
        )
        if parameters.get("stream_responses") is True:
            raise DevConsoleError(
                "this run used streaming responses; the whole-response workflow is different, so start a new experiment"
            )
        providers = (
            method_data.get("providers")
            if isinstance(method_data.get("providers"), dict)
            else {}
        )
        extractor_providers = providers.get("extractor")
        if not isinstance(extractor_providers, list):
            extractor_providers = []
        fallback_models = parameters.get("fallback_extractor_models")
        if not isinstance(fallback_models, list):
            fallback_models = []
        return DevRunRequest.from_payload(
            {
                "method": method,
                "run_id": run_id,
                "experiment_name": run_id,
                "extractor_model": models.get("extractor"),
                "reviewer_model": models.get("reviewer"),
                "task_surface": parameters.get("task_surface") or "full",
                "parallel": int(parameters.get("paper_parallelism") or 1),
                "max_repair_rounds": int(parameters.get("max_repair_rounds") or 0),
                "timeout_seconds": int(parameters.get("timeout_seconds") or 1800),
                "batch_size": int(parameters.get("batch_size") or 8),
                "max_tokens": parameters.get("max_tokens"),
                "provider_pin": bool(extractor_providers),
                "providers": extractor_providers,
                "fallback_models": fallback_models,
                "stream_responses": False,
            }
        )

    def _retry_external_papers(
        self,
        campaign_id: str,
        run_id: str,
        paper_ids: list[str],
    ) -> dict[str, Any]:
        campaign = validate_path_segment(campaign_id, "campaign id")
        run = validate_path_segment(run_id, "run id")
        if campaign != self.campaign_id:
            raise DevConsoleError("only the active campaign may be retried")
        requested = [validate_path_segment(value, "paper id") for value in paper_ids]
        if not requested or len(requested) != len(set(requested)):
            raise DevConsoleError("retry requires one or more distinct papers")
        summary = self.run_detail(campaign, run)
        eligible = set(summary["retryable_papers"])
        invalid = [paper_id for paper_id in requested if paper_id not in eligible]
        if invalid:
            raise DevConsoleError(
                "only unsealed transport_error papers may be retried: "
                + ", ".join(invalid)
            )
        request = self._request_from_run_config(run, summary["run_config"])
        state = self.start(
            request,
            resume=True,
            retry_external_papers=tuple(requested),
        )
        self.groups.mark_external_retry(run, state)
        return state

    def retry_external_paper(
        self,
        campaign_id: str,
        run_id: str,
        paper_id: str,
        payload: Any,
    ) -> dict[str, Any]:
        paper = validate_path_segment(paper_id, "paper id")
        if not isinstance(payload, dict) or payload.get("confirm_paper_id") != paper:
            raise DevConsoleError(
                "paper retry requires confirm_paper_id to exactly match the paper id"
            )
        return self._retry_external_papers(campaign_id, run_id, [paper])

    def retry_external_failures(
        self,
        campaign_id: str,
        run_id: str,
        payload: Any,
    ) -> dict[str, Any]:
        run = validate_path_segment(run_id, "run id")
        if not isinstance(payload, dict) or payload.get("confirm_run_id") != run:
            raise DevConsoleError(
                "run retry requires confirm_run_id to exactly match the run id"
            )
        summary = self.run_detail(campaign_id, run)
        papers = list(summary["retryable_papers"])
        if not papers:
            raise DevConsoleError("run has no retryable external service failures")
        return self._retry_external_papers(campaign_id, run, papers)

    def reset_run(self, run_id: str, payload: Any) -> dict[str, Any]:
        run_id = validate_path_segment(run_id, "run id")
        if not isinstance(payload, dict) or payload.get("confirm_run_id") != run_id:
            raise DevConsoleError("reset requires confirm_run_id to exactly match the run id")
        if self._active_process_group(run_id) is not None or self._run_lock_held(run_id):
            raise DevConsoleError("stop the active run before resetting it")
        run_dir = campaign_paths(self.workspace, self.campaign_id).runs / run_id
        trace_dir = self._trace_root_for(self.campaign_id, run_id)
        if (run_dir / "run_manifest.json").is_file():
            raise DevConsoleError("sealed runs cannot be reset")
        removed: list[str] = []
        for target in (run_dir, trace_dir):
            if target.exists():
                shutil.rmtree(target)
                removed.append(str(target))
        if not removed:
            raise DevConsoleError("run has no resettable local results")
        self.groups.mark_reset(run_id)
        self._trace_readers.pop((self.campaign_id, run_id), None)
        return {"run_id": run_id, "status": "reset", "removed": removed}

    def preflight(
        self,
        request: DevRunRequest,
        *,
        retry_external_papers: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": bool(ok), "detail": detail})

        campaign = self._campaign()
        check("campaign", campaign.get("campaign_id") == self.campaign_id, self.campaign_id)
        dev_papers = papers_for_split(campaign, "dev")
        check("dev split", len(dev_papers) == 10, f"{len(dev_papers)} papers")
        if request.scope == "regression":
            papers = list(request.paper_ids)
            scope_ok = bool(papers) and all(paper in dev_papers for paper in papers)
        else:
            papers = list(dev_papers)
            scope_ok = not request.paper_ids or list(request.paper_ids) == dev_papers
        check("paper scope", scope_ok, f"{request.scope}: {len(papers)} paper(s)")
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
        if retry_external_papers:
            config_path = run_dir / "run_config.json"
            try:
                retry_summary = self.run_detail(self.campaign_id, request.run_id)
                retry_config = retry_summary.get("run_config") or {}
            except (DevConsoleError, OSError, json.JSONDecodeError):
                retry_summary, retry_config = {}, {}
            retryable = set(retry_summary.get("retryable_papers") or [])
            check(
                "external failure selection",
                bool(retry_external_papers)
                and all(paper in retryable for paper in retry_external_papers),
                ", ".join(retry_external_papers),
            )
            stored_code = (
                retry_config.get("code")
                if isinstance(retry_config.get("code"), dict)
                else {}
            )
            check(
                "run code revision",
                bool(config_path.is_file())
                and stored_code.get("commit") == code.get("commit"),
                str(stored_code.get("commit") or "missing"),
            )
        command = build_runner_command(
            self.workspace,
            self.logs_root,
            request,
            retry_external_papers=retry_external_papers,
        )
        return {
            "ok": all(item["ok"] for item in checks),
            "checks": checks,
            "command": command,
            "request": request.public_dict(),
        }

    def start(
        self,
        request: DevRunRequest,
        *,
        resume: bool = False,
        retry_external_papers: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        preflight = self.preflight(
            request,
            retry_external_papers=retry_external_papers,
        )
        if not preflight["ok"]:
            failed = [
                f"{item['name']}: {item['detail']}"
                for item in preflight["checks"]
                if not item["ok"]
            ]
            raise DevConsoleError("preflight failed: " + "; ".join(failed))
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
                    "retry_external_papers": list(retry_external_papers),
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
            terminal_status = (
                "stopped"
                if requested_stop
                else (
                    "failed"
                    if returncode != 0
                    else self._terminal_status_from_archive(run_id)
                )
            )
            state.update(
                {
                    "status": terminal_status,
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
        report_payloads: dict[str, dict[str, Any]] = {}
        usage: dict[str, int] = {}
        downstream_usage: dict[str, int] = {}
        roster_bundles: dict[str, dict[str, Any]] = {}
        for paper in papers if isinstance(papers, list) else []:
            paper_id = str(paper)
            reports[paper_id] = paper_status(run_dir / paper_id)
            report_path = run_dir / paper_id / "report.json"
            if report_path.is_file():
                try:
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    report = {}
                if isinstance(report, dict):
                    report_payloads[paper_id] = report
                for key, value in (report.get("usage_totals") or {}).items():
                    if isinstance(value, int):
                        usage[key] = usage.get(key, 0) + value
                for key, value in (report.get("downstream_usage") or {}).items():
                    if isinstance(value, int):
                        downstream_usage[key] = downstream_usage.get(key, 0) + value
                bundle_id = str(report.get("roster_bundle_id") or "")
                if bundle_id:
                    bundle = roster_bundles.setdefault(
                        bundle_id,
                        {
                            "bundle_id": bundle_id,
                            "paper_ids": [],
                            "usage_totals": {},
                            "cache_hit": True,
                        },
                    )
                    bundle["paper_ids"].append(paper_id)
                    bundle["cache_hit"] = bool(bundle["cache_hit"]) and bool(
                        report.get("roster_cache_hit")
                    )
                    for key, value in (report.get("shared_roster_usage") or {}).items():
                        if isinstance(value, int):
                            bundle["usage_totals"][key] = max(
                                int(bundle["usage_totals"].get(key, 0)), value
                            )
            elif (run_dir / paper_id / "roster_bundle.json").is_file():
                try:
                    live_bundle = json.loads(
                        (run_dir / paper_id / "roster_bundle.json").read_text(
                            encoding="utf-8"
                        )
                    )
                except json.JSONDecodeError:
                    live_bundle = {}
                if not isinstance(live_bundle, dict):
                    live_bundle = {}
                bundle_id = str(live_bundle.get("bundle_id") or "")
                if bundle_id:
                    bundle = roster_bundles.setdefault(
                        bundle_id,
                        {
                            "bundle_id": bundle_id,
                            "paper_ids": [],
                            "usage_totals": {},
                            "cache_hit": False,
                        },
                    )
                    bundle["paper_ids"].append(paper_id)
                    live_usage = live_bundle.get("usage")
                    if not isinstance(live_usage, dict):
                        live_usage = {}
                    for key, value in live_usage.items():
                        if isinstance(value, int):
                            bundle["usage_totals"][key] = max(
                                int(bundle["usage_totals"].get(key, 0)), value
                            )
        structural_events = self._structural_events(
            campaign_id, run_dir.name, max_events=50_000
        )
        for event in structural_events:
            paper_id = str(event.get("paper_id") or "")
            if not paper_id or paper_id in report_payloads:
                continue
            usage_delta = event.get("usage_delta")
            if not isinstance(usage_delta, dict):
                continue
            for key, value in usage_delta.items():
                if isinstance(value, int):
                    usage[key] = usage.get(key, 0) + value
                    if str(event.get("stage") or "") != "roster":
                        downstream_usage[key] = downstream_usage.get(key, 0) + value
        state = self._reconcile_state(run_dir.name) if campaign_id == self.campaign_id else None
        saved_request = (
            state.get("request")
            if state and isinstance(state.get("request"), dict)
            else {}
        )
        if method == "unknown" and saved_request.get("method") in {"B", "C"}:
            method = str(saved_request["method"])
        scope = str(saved_request.get("scope") or "")
        if not scope:
            if config.get("mode") == "experimental" and config.get("split") == "experimental":
                scope = "regression"
            elif config.get("mode") == "formal" and config.get("split") == "dev":
                scope = "formal_dev"
            else:
                scope = "legacy"
        if not papers and state:
            requested_papers = saved_request.get("paper_ids")
            papers = (
                list(requested_papers)
                if isinstance(requested_papers, list) and requested_papers
                else self.dev_papers()
            )
        sealed = (run_dir / "run_manifest.json").is_file()
        deliveries: dict[str, Any] | None = None
        if sealed:
            try:
                sealed_manifest = json.loads(
                    (run_dir / "run_manifest.json").read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                sealed_manifest = {}
            # CORE and enrichment delivery are reported side by side and are
            # never collapsed into one success rate.
            deliveries = {
                "core": self._delivery_summary(sealed_manifest.get("core_delivery")),
                "enrichment": self._delivery_summary(
                    sealed_manifest.get("enrichment_delivery")
                ),
            }
        if sealed:
            status = "sealed"
        elif state:
            status = str(state.get("status") or "unknown")
        elif reports and all(value in SUCCESS_STATUSES for value in reports.values()):
            status = "completed"
        elif reports:
            status = "partial"
        else:
            status = "unknown"
        trace_events = self._trace_root_for(campaign_id, run_dir.name) / "events.jsonl"
        read_only = (
            sealed
            or campaign_id != self.campaign_id
            or method != PRIMARY_DIRECT_METHOD
        )
        controllable = bool(
            campaign_id == self.campaign_id
            and not sealed
            and status in {"running", "stop_requested"}
            and self._active_process_group(run_dir.name) is not None
        )
        resumable = bool(
            not read_only
            and not sealed
            and scope == "formal_dev"
            and status in {"stopped", "failed", "partial"}
            and state
            and isinstance(state.get("request"), dict)
        )
        diagnostics = self._paper_diagnostics(
            campaign_id,
            run_dir.name,
            list(papers) if isinstance(papers, list) else [],
            reports,
            report_payloads,
            structural_events=structural_events,
        )
        parameters = (
            method_data.get("parameters")
            if isinstance(method_data.get("parameters"), dict)
            else {}
        )
        campaign_ref = (
            config.get("campaign")
            if isinstance(config.get("campaign"), dict)
            else {}
        )
        retry_run_blocker = ""
        if sealed:
            retry_run_blocker = "Run 已封存，只读"
        elif read_only:
            retry_run_blocker = "此 Run 仅支持只读检查"
        elif config.get("mode") != "formal" or config.get("split") != "dev":
            retry_run_blocker = "只有正式 dev Run 可修复外部故障"
        elif campaign_ref.get("campaign_id") != self.campaign_id:
            retry_run_blocker = "只有当前 campaign 的 Run 可修复"
        elif parameters.get("stream_responses") is True:
            retry_run_blocker = "该 Run 使用旧的流式传输；运行方式已变化，需新开实验"
        elif status in {"running", "stop_requested"}:
            retry_run_blocker = "Run 正在运行"

        retryable_papers: list[str] = []
        for paper_id, diagnostic in diagnostics.items():
            paper_run_status = str(diagnostic.get("status") or "missing")
            external_eligible, external_reason = external_failure_retry_eligibility(
                report_payloads.get(paper_id, {})
            )
            eligible = not retry_run_blocker and external_eligible
            if eligible:
                transport_error = diagnostic.get("transport_error")
                if (
                    isinstance(transport_error, dict)
                    and transport_error.get("category") in {"auth", "authentication"}
                ):
                    reason = "认证失败：修复凭据后可人工重试"
                else:
                    reason = "外部服务传输失败，可重试"
                retryable_papers.append(paper_id)
            elif retry_run_blocker:
                reason = retry_run_blocker
            elif paper_run_status in SUCCESS_STATUSES:
                reason = "成功论文不可重跑"
            elif paper_run_status in {"missing", "queued", "running"}:
                reason = "尚无可重试的外部服务失败报告"
            elif paper_run_status in EXTERNAL_RETRY_STATUSES:
                reason = (
                    "API 请求或配置错误：修复工作流后新开实验"
                    if "request/configuration" in external_reason
                    else "该传输错误无法确认是外部服务故障，需检查后新开实验"
                )
            else:
                reason = "工作流或结果错误：修复工作流后新开实验"
            diagnostic["retry_eligible"] = eligible
            diagnostic["retry_reason"] = reason
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
            "scope": scope,
            "papers": list(papers) if isinstance(papers, list) else [],
            "paper_statuses": reports,
            "paper_diagnostics": diagnostics,
            "usage_totals": usage,
            "downstream_usage_totals": downstream_usage,
            "shared_roster_bundles": list(roster_bundles.values()),
            "trace_precision": "exact" if trace_events.is_file() else "legacy_synthesized",
            "read_only": read_only,
            "controllable": controllable,
            "resumable": resumable,
            "sealed": sealed,
            "deliveries": deliveries,
            "retryable_papers": retryable_papers,
        }

    @staticmethod
    def _delivery_summary(delivery: Any) -> dict[str, Any] | None:
        """Compact sealed-delivery view: status plus per-outcome paper counts."""

        if not isinstance(delivery, dict):
            return None
        papers = delivery.get("papers") if isinstance(delivery.get("papers"), dict) else {}
        return {
            "status": str(delivery.get("status") or ""),
            "validation_mode": str(delivery.get("validation_mode") or ""),
            "valid": len(papers.get("valid") or []),
            "invalid": len(papers.get("invalid") or []),
            "missing": len(papers.get("missing") or []),
        }

    @staticmethod
    def _report_error_message(status: str, report: dict[str, Any]) -> str:
        transport_error = report.get("transport_error")
        if isinstance(transport_error, dict):
            category = str(transport_error.get("category") or "transport")
            http_status = transport_error.get("http_status")
            return f"HTTP {http_status} · {category}" if http_status else category
        error = report.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        validator_errors = report.get("validator_errors")
        if isinstance(validator_errors, list):
            first = next(
                (str(item).strip() for item in validator_errors if str(item).strip()),
                "",
            )
            if first:
                return first
        if status == "review_failed":
            return "独立复核未通过"
        if status == "invalid_report":
            return "report.json 无法读取"
        return ""

    @staticmethod
    def _failure_stage(status: str, report: dict[str, Any]) -> str:
        if status in SUCCESS_STATUSES:
            return "completed"
        if status in {"validator_errors", "invalid", "invalid_report"}:
            return "validation"
        if status == "review_failed":
            return "review"
        transport_error = report.get("transport_error")
        if status == "transport_error" and isinstance(transport_error, dict):
            stage = str(transport_error.get("stage") or "").strip()
            if stage:
                return stage
        error = report.get("error")
        if status == "transport_error" and isinstance(error, str) and ":" in error:
            prefix = error.split(":", 1)[0].strip()
            if prefix:
                return prefix
        if status == "transport_error":
            return "transport"
        if status not in {"missing", "running"}:
            return "final"
        return "queued" if status == "missing" else "running"

    @staticmethod
    def _list_count(value: Any) -> int:
        return len(value) if isinstance(value, list) else 0

    def _structural_events(
        self, campaign_id: str, run_id: str, *, max_events: int = 6000
    ) -> list[dict[str, Any]]:
        return RunTrace(
            self.logs_root,
            campaign_id=campaign_id,
            run_id=run_id,
            method="unknown",
            create=False,
        ).read_structural_events(max_events=max_events)

    def _paper_diagnostics(
        self,
        campaign_id: str,
        run_id: str,
        papers: list[Any],
        statuses: dict[str, str],
        reports: dict[str, dict[str, Any]],
        *,
        structural_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        diagnostics: dict[str, dict[str, Any]] = {}
        for paper in papers:
            paper_id = str(paper)
            status = statuses.get(paper_id, "missing")
            report = reports.get(paper_id, {})
            validator_errors = report.get("validator_errors")
            warnings = report.get("validator_warnings")
            if warnings is None:
                warnings = report.get("warnings")
            warning_details_available = isinstance(warnings, list)
            warning_count = self._list_count(warnings)
            if not warning_details_available:
                historical_count = report.get("validator_warnings_count")
                if isinstance(historical_count, int) and historical_count >= 0:
                    warning_count = historical_count
            validator_groups = report.get("validator_groups")
            if not isinstance(validator_groups, list):
                validator_groups = []
            transport_error = report.get("transport_error")
            diagnostics[paper_id] = {
                "paper_id": paper_id,
                "status": status,
                "stage": self._failure_stage(status, report),
                "error_type": "" if status in SUCCESS_STATUSES or status == "missing" else status,
                "error_message": self._report_error_message(status, report),
                "validator_error_count": self._list_count(validator_errors),
                "warning_count": warning_count,
                "warning_details_available": warning_details_available,
                "historical_warning_count_only": bool(
                    warning_count and not warning_details_available
                ),
                "validator_groups": validator_groups,
                "transport_error": transport_error if isinstance(transport_error, dict) else None,
                "roster_bundle_id": str(report.get("roster_bundle_id") or ""),
                "roster_cache_hit": bool(report.get("roster_cache_hit")),
                "report_available": bool(report),
            }

        for event in (
            structural_events
            if structural_events is not None
            else self._structural_events(campaign_id, run_id)
        ):
            paper_id = str(event.get("paper_id") or "")
            if not paper_id or paper_id not in diagnostics:
                continue
            diagnostic = diagnostics[paper_id]
            if diagnostic["report_available"]:
                continue
            event_type = str(event.get("type") or "")
            if event_type == "paper.started":
                diagnostic["status"] = "running"
                diagnostic["stage"] = str(event.get("stage") or "context")
            elif event_type == "paper.completed":
                status = str(event.get("status") or "failed")
                data = event.get("data") if isinstance(event.get("data"), dict) else {}
                diagnostic.update(
                    {
                        "status": status,
                        "stage": self._failure_stage(status, data),
                        "error_type": "" if status in SUCCESS_STATUSES else status,
                        "error_message": self._report_error_message(status, data),
                        "validator_error_count": self._list_count(data.get("validator_errors")),
                    }
                )
            elif diagnostic["status"] == "running" and event.get("stage"):
                diagnostic["stage"] = str(event["stage"])
        return diagnostics

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        campaigns_root = self.workspace / "benchmark" / "campaigns"
        for campaign_dir in sorted(campaigns_root.glob("*")):
            runs_dir = campaign_dir / "runs"
            if not runs_dir.is_dir():
                continue
            for run_dir in sorted(
                (
                    path
                    for path in runs_dir.iterdir()
                    if path.is_dir() and not path.name.startswith("_")
                ),
                reverse=True,
            ):
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

    def paper_detail(self, campaign_id: str, run_id: str, paper_id: str) -> dict[str, Any]:
        campaign = validate_path_segment(campaign_id, "campaign id")
        run = validate_path_segment(run_id, "run id")
        paper = validate_path_segment(paper_id, "paper id")
        summary = self.run_detail(campaign, run)
        if paper not in summary["papers"]:
            raise DevConsoleError("paper is not part of this run")
        report_path = (
            self.workspace
            / "benchmark"
            / "campaigns"
            / campaign
            / "runs"
            / run
            / paper
            / "report.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else None
        events = [
            event
            for event in self._structural_events(campaign, run)
            if event.get("paper_id") == paper
        ]
        return {
            "diagnostic": summary["paper_diagnostics"][paper],
            "report": report,
            "events": events,
        }

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
        scope = str(request.get("scope") or "formal_dev")
        requested_papers = request.get("paper_ids")
        papers = (
            list(requested_papers)
            if isinstance(requested_papers, list) and requested_papers
            else self.dev_papers()
        )
        return {
            "campaign_id": campaign,
            "run_id": run,
            "method": str(request.get("method") or "unknown"),
            "status": status,
            "created_at": str(state.get("started_at") or ""),
            "finished_at": str(state.get("finished_at") or ""),
            "scope": scope,
            "papers": papers,
            "paper_statuses": {},
            "paper_diagnostics": {
                paper: {
                    "paper_id": paper,
                    "status": "queued",
                    "stage": "queued",
                    "error_type": "",
                    "error_message": "",
                    "validator_error_count": 0,
                    "warning_count": 0,
                    "warning_details_available": False,
                    "historical_warning_count_only": False,
                    "validator_groups": [],
                    "transport_error": None,
                    "roster_bundle_id": "",
                    "roster_cache_hit": False,
                    "report_available": False,
                    "retry_eligible": False,
                    "retry_reason": "尚无可重试的外部服务失败报告",
                }
                for paper in papers
            },
            "usage_totals": {},
            "downstream_usage_totals": {},
            "shared_roster_bundles": [],
            "trace_precision": "exact",
            "read_only": False,
            "controllable": status in {"running", "stop_requested"}
            and self._active_process_group(run) is not None,
            "resumable": scope == "formal_dev"
            and status in {"stopped", "failed", "partial"}
            and bool(request),
            "sealed": False,
            "retryable_papers": [],
        }

    def events(self, campaign_id: str, run_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        campaign = validate_path_segment(campaign_id, "campaign id")
        run = validate_path_segment(run_id, "run id")
        key = (campaign, run)
        trace = self._trace_readers.get(key)
        if trace is None:
            trace = RunTrace(
                self.logs_root,
                campaign_id=campaign,
                run_id=run,
                method="unknown",
                create=False,
            )
            self._trace_readers[key] = trace
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

    def event_snapshot(self, campaign_id: str, run_id: str) -> dict[str, Any]:
        campaign = validate_path_segment(campaign_id, "campaign id")
        run = validate_path_segment(run_id, "run id")
        key = (campaign, run)
        trace = self._trace_readers.get(key)
        if trace is None:
            trace = RunTrace(
                self.logs_root,
                campaign_id=campaign,
                run_id=run,
                method="unknown",
                create=False,
            )
            self._trace_readers[key] = trace
        if trace.events_path.is_file():
            return trace.read_event_snapshot()
        events = self.events(campaign, run, after=0)
        return {
            "last_seq": max((int(event.get("seq", 0)) for event in events), default=0),
            "events": events[-6000:],
            "history_truncated": len(events) > 6000,
        }

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
        allowed = {
            "report.json",
            "context_manifest.json",
            "roster_context_manifest.json",
            "literature_hvs_candidates.json",
            "review.json",
        }
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

        def _serve_asset(self, relative: Path, content_type: str | None = None) -> None:
            root = (controller.assets_root / "benchmark-console").resolve()
            path = (root / relative).resolve()
            if path != root and root not in path.parents:
                raise DevConsoleError("asset path is outside the console bundle")
            if not path.is_file():
                raise DevConsoleError("console asset does not exist")
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK.value)
            guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_header("Content-Type", content_type or guessed)
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
                    self._serve_asset(Path("index.html"), "text/html; charset=utf-8")
                    return
                if segments[0] == "ui":
                    relative = Path(*segments[1:]) if len(segments) > 1 else Path("index.html")
                    self._serve_asset(relative)
                    return
                if segments == ["api", "bootstrap"]:
                    _json_response(self, HTTPStatus.OK, controller.bootstrap())
                    return
                if segments == ["api", "runs"]:
                    _json_response(self, HTTPStatus.OK, {"runs": controller.list_runs()})
                    return
                if segments == ["api", "experiment-groups"]:
                    _json_response(self, HTTPStatus.OK, {"groups": controller.groups.list()})
                    return
                if len(segments) == 3 and segments[:2] == ["api", "experiment-groups"]:
                    _json_response(self, HTTPStatus.OK, controller.groups.read(segments[2]))
                    return
                if len(segments) == 4 and segments[:2] == ["api", "experiment-groups"] and segments[3] == "events":
                    self._serve_group_events(segments[2], query)
                    return
                if len(segments) == 4 and segments[:2] == ["api", "experiment-groups"] and segments[3] == "evaluation":
                    _json_response(self, HTTPStatus.OK, controller.evaluations.get(segments[2]))
                    return
                if len(segments) == 4 and segments[:2] == ["api", "experiment-groups"] and segments[3] == "scorecards":
                    _json_response(self, HTTPStatus.OK, {"scorecards": controller.evaluations.scorecards(segments[2])})
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
                if len(segments) == 5 and segments[:2] == ["api", "runs"] and segments[4] == "trace-snapshot":
                    _json_response(self, HTTPStatus.OK, controller.event_snapshot(segments[2], segments[3]))
                    return
                if len(segments) == 6 and segments[:2] == ["api", "runs"] and segments[4] == "papers":
                    _json_response(self, HTTPStatus.OK, controller.paper_detail(segments[2], segments[3], segments[5]))
                    return
                if len(segments) == 6 and segments[:2] == ["api", "runs"] and segments[4] == "blobs":
                    _json_response(self, HTTPStatus.OK, controller.read_blob(segments[2], segments[3], segments[5]))
                    return
                if len(segments) == 5 and segments[:2] == ["api", "runs"] and segments[4] == "artifact":
                    paper = str((query.get("paper") or [""])[0])
                    name = str((query.get("name") or [""])[0])
                    _json_response(self, HTTPStatus.OK, controller.read_artifact(segments[2], segments[3], paper, name))
                    return
                if segments[0] in {"setup", "runs", "review", "evaluate", "history"}:
                    self._serve_asset(Path("index.html"), "text/html; charset=utf-8")
                    return
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "route not found"})
            except (DevConsoleError, ValueError, OSError, json.JSONDecodeError) as exc:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def _serve_events(self, campaign_id: str, run_id: str, query: dict[str, list[str]]) -> None:
            query_after = int((query.get("after") or ["0"])[0] or 0)
            header_after = int(self.headers.get("Last-Event-ID", "0") or 0)
            after = max(query_after, header_after)
            once = (query.get("once") or ["0"])[0] == "1"
            startup_events: list[dict[str, Any]] = []
            if after <= 0:
                snapshot = controller.event_snapshot(campaign_id, run_id)
                after = int(snapshot["last_seq"])
                startup_events = list(snapshot["events"])
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
                    events = startup_events
                    startup_events = []
                    events.extend(controller.events(campaign_id, run_id, after=after))
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

        def _serve_group_events(self, group_id: str, query: dict[str, list[str]]) -> None:
            query_after = int((query.get("after") or ["0"])[0] or 0)
            header_after = int(self.headers.get("Last-Event-ID", "0") or 0)
            after = max(query_after, header_after)
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
                    events = controller.groups.events(group_id, after=after)
                    for event in events:
                        after = max(after, int(event["seq"]))
                        data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                        self.wfile.write(f"id: {event['seq']}\nevent: group\ndata: {data}\n\n".encode("utf-8"))
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
                if segments == ["api", "experiment-groups", "preflight"]:
                    _json_response(self, HTTPStatus.OK, controller.group_preflight(payload))
                    return
                if segments == ["api", "experiment-groups"]:
                    _json_response(self, HTTPStatus.ACCEPTED, controller.create_group(payload))
                    return
                if segments == ["api", "runs"]:
                    _json_response(self, HTTPStatus.ACCEPTED, controller.start(DevRunRequest.from_payload(payload)))
                    return
                if len(segments) == 4 and segments[:2] == ["api", "experiment-groups"] and segments[3] == "stop":
                    _json_response(self, HTTPStatus.ACCEPTED, controller.groups.stop(segments[2]))
                    return
                if len(segments) == 4 and segments[:2] == ["api", "experiment-groups"] and segments[3] == "resume":
                    _json_response(self, HTTPStatus.ACCEPTED, controller.groups.resume(segments[2]))
                    return
                if len(segments) == 5 and segments[:2] == ["api", "experiment-groups"] and segments[3:] == ["evaluation", "preflight"]:
                    _json_response(self, HTTPStatus.OK, controller.evaluations.preflight(segments[2], payload))
                    return
                if len(segments) == 4 and segments[:2] == ["api", "experiment-groups"] and segments[3] == "evaluation":
                    _json_response(self, HTTPStatus.ACCEPTED, controller.evaluations.start(segments[2], payload))
                    return
                if (
                    len(segments) == 7
                    and segments[:2] == ["api", "runs"]
                    and segments[4] == "papers"
                    and segments[6] == "retry"
                ):
                    _json_response(
                        self,
                        HTTPStatus.ACCEPTED,
                        controller.retry_external_paper(
                            segments[2], segments[3], segments[5], payload
                        ),
                    )
                    return
                if (
                    len(segments) == 5
                    and segments[:2] == ["api", "runs"]
                    and segments[4] == "retry-external-failures"
                ):
                    _json_response(
                        self,
                        HTTPStatus.ACCEPTED,
                        controller.retry_external_failures(
                            segments[2], segments[3], payload
                        ),
                    )
                    return
                if len(segments) == 4 and segments[:2] == ["api", "runs"] and segments[3] == "stop":
                    _json_response(self, HTTPStatus.ACCEPTED, controller.stop(segments[2]))
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
