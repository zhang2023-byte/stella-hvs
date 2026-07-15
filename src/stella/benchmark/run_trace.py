"""Local, content-addressed observability traces for benchmark dev runs."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from stella.schema_registry import schema_ref

from .paths import validate_path_segment
from .tool_loop import accumulate_usage


_BLOB_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SEQ_BYTES_RE = re.compile(rb'"seq"\s*:\s*(\d+)')
_DELTA_TYPE_BYTES_RE = re.compile(rb'"type"\s*:\s*"llm\.response\.delta"')
_DEFAULT_SNAPSHOT_TAIL_BYTES = 32 * 1024 * 1024


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def response_trace_metadata(response: dict[str, Any]) -> dict[str, Any]:
    """Return small UI metadata without treating hidden reasoning as content."""

    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") if isinstance(choice, dict) else {}
    message = message if isinstance(message, dict) else {}
    reasoning = message.get("reasoning_content")
    if reasoning is None:
        reasoning = message.get("reasoning")
    content = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []
    return {
        "served_model": str(response.get("model") or ""),
        "finish_reason": str(choice.get("finish_reason") or "") if isinstance(choice, dict) else "",
        "content_chars": len(content) if isinstance(content, str) else 0,
        "provider_reasoning_available": isinstance(reasoning, str) and bool(reasoning),
        "provider_reasoning_chars": len(reasoning) if isinstance(reasoning, str) else 0,
        "tool_call_count": len(tool_calls) if isinstance(tool_calls, list) else 0,
    }


def stream_trace_callback(
    trace: "RunTrace",
    *,
    paper_id: str,
    stage: str,
    call_id: str,
    parent_seq: int | None,
) -> Callable[[dict[str, Any]], None]:
    """Translate transport stream/retry callbacks into run-event v2 records."""

    def emit(item: dict[str, Any]) -> None:
        kind = str(item.get("type") or "stream.event")
        event_type = f"llm.{kind}"
        incoming = kind in {"response.delta", "stream.completed", "stream.interrupted"}
        status = (
            "failed"
            if kind == "retry.exhausted"
            else "retrying"
            if kind in {"retry.scheduled", "stream.interrupted"}
            else "running"
        )
        trace.emit(
            event_type,
            paper_id=paper_id,
            stage=stage,
            status=status,
            summary=kind.replace(".", " "),
            data=dict(item),
            parent_seq=parent_seq,
            call_id=call_id,
            node_id=stage,
            source_node_id="provider" if incoming else stage,
            target_node_id=stage if incoming else "provider",
            attempt=int(item.get("attempt") or 1),
        )

    return emit


class RunTrace:
    """Append-only JSONL events plus deduplicated gzip JSON payload blobs."""

    def __init__(
        self,
        logs_root: Path,
        *,
        campaign_id: str,
        run_id: str,
        method: str,
        session_id: str | None = None,
        create: bool = True,
    ) -> None:
        self.campaign_id = validate_path_segment(campaign_id, "campaign id")
        self.run_id = validate_path_segment(run_id, "run id")
        if method not in {"A", "B", "C", "unknown"}:
            raise ValueError("trace method must be A, B, C, or unknown")
        self.method = method
        self.session_id = session_id or uuid.uuid4().hex
        self.root = logs_root.expanduser().resolve() / self.campaign_id / self.run_id
        self.blobs_dir = self.root / "blobs"
        self.events_path = self.root / "events.jsonl"
        self.structural_events_path = self.root / "structural-events.jsonl"
        self.state_path = self.root / "controller.json"
        if create:
            self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._seq = self._last_sequence()
        self._read_offset = 0
        self._read_last_seq = 0

    def _last_sequence(self) -> int:
        if not self.events_path.is_file():
            return 0
        # Sequence numbers are at the top level of every compact JSONL event.
        # Reading from the tail keeps opening a multi-gigabyte trace O(1) in
        # memory and avoids replaying the file just to initialize a reader.
        with self.events_path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            window = min(size, 64 * 1024)
            while window:
                stream.seek(size - window)
                raw = stream.read(window)
                lines = raw.splitlines()
                if size > window and lines:
                    lines = lines[1:]
                for line in reversed(lines):
                    try:
                        event = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if isinstance(event, dict) and isinstance(event.get("seq"), int):
                        return int(event["seq"])
                if window == size:
                    break
                window = min(size, window * 2)
        return 0

    def store_blob(self, kind: str, payload: Any) -> dict[str, Any]:
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        envelope = {
            "schema": schema_ref("benchmark.run_trace_blob"),
            "kind": str(kind),
            "payload": payload,
        }
        raw = _canonical_bytes(envelope)
        digest = hashlib.sha256(raw).hexdigest()
        destination = self.blobs_dir / f"{digest}.json.gz"
        if not destination.exists():
            compressed = gzip.compress(raw, compresslevel=6, mtime=0)
            temporary = self.blobs_dir / f".{digest}.{uuid.uuid4().hex}.tmp"
            temporary.write_bytes(compressed)
            try:
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return {
            "sha256": digest,
            "kind": str(kind),
            "bytes": len(raw),
            "encoding": "gzip+json",
        }

    def read_blob(self, digest: str) -> dict[str, Any]:
        if not _BLOB_HASH_RE.fullmatch(str(digest)):
            raise ValueError("invalid trace blob hash")
        path = self.blobs_dir / f"{digest}.json.gz"
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))

    def emit(
        self,
        event_type: str,
        *,
        paper_id: str | None = None,
        stage: str | None = None,
        status: str | None = None,
        summary: str = "",
        data: dict[str, Any] | None = None,
        payload_kind: str | None = None,
        payload: Any = None,
        usage: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        parent_seq: int | None = None,
        call_id: str | None = None,
        node_id: str | None = None,
        source_node_id: str | None = None,
        target_node_id: str | None = None,
        attempt: int | None = None,
    ) -> dict[str, Any]:
        payload_ref = (
            self.store_blob(payload_kind, payload)
            if payload_kind is not None
            else None
        )
        usage_delta: dict[str, int] = {}
        if usage:
            accumulate_usage(usage_delta, usage)
        with self._lock:
            self._seq += 1
            event: dict[str, Any] = {
                "schema": schema_ref("benchmark.run_event"),
                "seq": self._seq,
                "occurred_at": _utc_now(),
                "session_id": self.session_id,
                "campaign_id": self.campaign_id,
                "run_id": self.run_id,
                "method": self.method,
                "type": str(event_type),
            }
            if paper_id:
                event["paper_id"] = str(paper_id)
            if stage:
                event["stage"] = str(stage)
            if status:
                event["status"] = str(status)
            if summary:
                event["summary"] = str(summary)
            if data:
                event["data"] = data
            if payload_ref:
                event["payload_ref"] = payload_ref
            if usage_delta:
                event["usage_delta"] = usage_delta
            if duration_ms is not None:
                event["duration_ms"] = max(0, int(duration_ms))
            if parent_seq is not None:
                event["parent_seq"] = int(parent_seq)
            if call_id:
                event["call_id"] = str(call_id)
            if node_id:
                event["node_id"] = str(node_id)
            if source_node_id:
                event["source_node_id"] = str(source_node_id)
            if target_node_id:
                event["target_node_id"] = str(target_node_id)
            if attempt is not None:
                event["attempt"] = max(1, int(attempt))
            self.root.mkdir(parents=True, exist_ok=True)
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            with self.events_path.open("a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
            if event_type != "llm.response.delta":
                with self.structural_events_path.open("a", encoding="utf-8") as stream:
                    stream.write(line)
                    stream.flush()
        return event

    @staticmethod
    def _bounded_complete_lines(path: Path, *, tail_bytes: int) -> tuple[list[bytes], int, bool]:
        """Read complete JSONL records from a bounded tail and return its cursor."""

        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            start = max(0, size - max(1, tail_bytes))
            stream.seek(start)
            if start:
                stream.readline()  # discard the first, potentially partial record
            records_start = stream.tell()
            raw = stream.read(max(0, size - records_start))
        final_newline = raw.rfind(b"\n")
        if final_newline < 0:
            return [], records_start, start > 0 or bool(raw)
        complete = raw[: final_newline + 1]
        return complete.splitlines(), records_start + len(complete), start > 0

    def read_event_snapshot(
        self,
        *,
        max_events: int = 6000,
        tail_bytes: int = _DEFAULT_SNAPSHOT_TAIL_BYTES,
    ) -> dict[str, Any]:
        """Return a bounded startup view and seed incremental SSE at its cursor.

        New traces keep a compact structural-event index. Older traces fall
        back to a bounded tail, so opening the console never scans or returns
        an unbounded delta history. One latest delta sample is retained to make
        an in-flight call visible before its next live SSE frame arrives.
        """

        if max_events < 1:
            raise ValueError("max_events must be positive")
        if not self.events_path.is_file():
            return {"last_seq": 0, "events": [], "history_truncated": False}
        with self._read_lock:
            tail_lines, safe_offset, tail_truncated = self._bounded_complete_lines(
                self.events_path,
                tail_bytes=tail_bytes,
            )
            last_seq = 0
            latest_delta: bytes | None = None
            tail_structural: deque[dict[str, Any]] = deque(maxlen=max_events)
            for raw in tail_lines:
                match = _SEQ_BYTES_RE.search(raw)
                if match:
                    last_seq = max(last_seq, int(match.group(1)))
                if _DELTA_TYPE_BYTES_RE.search(raw):
                    latest_delta = raw
                    continue
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(event, dict):
                    tail_structural.append(event)

            structural: deque[dict[str, Any]] = deque(maxlen=max_events)
            index_truncated = False
            if self.structural_events_path.is_file():
                indexed_lines, _, index_truncated = self._bounded_complete_lines(
                    self.structural_events_path,
                    tail_bytes=tail_bytes,
                )
                for raw in indexed_lines:
                    try:
                        event = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if isinstance(event, dict):
                        structural.append(event)
            structural.extend(tail_structural)

            events = list(structural)
            if latest_delta is not None:
                try:
                    delta_event = json.loads(latest_delta)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    delta_event = None
                if isinstance(delta_event, dict):
                    events.append(delta_event)
            events = sorted(
                {int(event.get("seq", 0)): event for event in events if isinstance(event.get("seq"), int)}.values(),
                key=lambda event: int(event["seq"]),
            )[-max_events:]
            self._read_offset = safe_offset
            self._read_last_seq = last_seq
            return {
                "last_seq": last_seq,
                "events": events,
                "history_truncated": bool(tail_truncated or index_truncated),
            }

    def read_events(self, *, after: int = 0) -> list[dict[str, Any]]:
        if not self.events_path.is_file():
            return []
        if after > 0 and self._read_offset == 0 and self._read_last_seq == 0:
            snapshot = self.read_event_snapshot()
            return [event for event in snapshot["events"] if int(event.get("seq", 0)) > after]
        with self._read_lock:
            events: list[dict[str, Any]] = []
            start_offset = self._read_offset if after >= self._read_last_seq else 0
            last_seq = self._read_last_seq if start_offset else 0
            with self.events_path.open("rb") as stream:
                stream.seek(start_offset)
                for raw in stream:
                    try:
                        event = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if isinstance(event.get("seq"), int):
                        last_seq = max(last_seq, event["seq"])
                        if event["seq"] > after:
                            events.append(event)
                self._read_offset = stream.tell()
                self._read_last_seq = last_seq
            return events
