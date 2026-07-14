import { useEffect, useMemo, useState } from "react";
import type { TraceEvent } from "../types";

const TRACE_FLUSH_MS = 100;
const MAX_STRUCTURAL_EVENTS = 1200;
const MAX_DELTA_EVENTS = 2400;
const MAX_USAGE_EVENTS = 5000;

export type TraceConnectionState = "connecting" | "connected" | "reconnecting";
export type ModelCallStatus = "waiting" | "streaming" | "retrying" | "completed" | "failed" | "interrupted";

export interface ModelCallTranscript {
  key: string;
  call_id: string;
  generation: number;
  attempt: number;
  first_seq: number;
  last_seq: number;
  occurred_at: string;
  paper_id?: string;
  stage?: string;
  status: ModelCallStatus;
  reasoning: string;
  content: string;
  model?: string;
  finish_reason?: string;
  tool_call_count?: number;
  duration_ms?: number;
  usage?: Record<string, number>;
  request_event?: TraceEvent;
  response_event?: TraceEvent;
}

export interface ModelTranscriptState {
  calls: ModelCallTranscript[];
  last_seq: number;
}

const OPEN_CALL_STATUSES = new Set<ModelCallStatus>(["waiting", "streaming", "retrying"]);

function numericAttempt(event: TraceEvent, fallback = 1) {
  const value = event.attempt ?? event.data?.attempt ?? fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function stringData(event: TraceEvent, key: string) {
  const value = event.data?.[key];
  return typeof value === "string" && value ? value : undefined;
}

function numberData(event: TraceEvent, key: string) {
  const value = Number(event.data?.[key]);
  return Number.isFinite(value) ? value : undefined;
}

/**
 * Build durable, human-readable model turns before the raw delta retention cap
 * is applied. A call id can be reused when a stopped paper is restarted, while
 * a transport retry reuses the call id but increments attempt.
 */
export function mergeModelTranscriptBatch(
  current: ModelTranscriptState | undefined,
  batch: TraceEvent[],
): ModelTranscriptState {
  const previous = current || { calls: [], last_seq: 0 };
  const unseen = new Map<number, TraceEvent>();
  for (const event of batch) {
    if (event.seq > previous.last_seq) unseen.set(event.seq, event);
  }
  const ordered = [...unseen.values()].sort((left, right) => left.seq - right.seq);
  if (ordered.length === 0) return previous;

  const calls: ModelCallTranscript[] = previous.calls.map((call) => ({
    ...call,
    usage: call.usage ? { ...call.usage } : undefined,
  }));
  const latestByCall = new Map<string, ModelCallTranscript>();
  const latestByAttempt = new Map<string, ModelCallTranscript>();
  const generations = new Map<string, number>();
  for (const call of calls) {
    latestByCall.set(call.call_id, call);
    latestByAttempt.set(`${call.call_id}:${call.attempt}`, call);
    generations.set(call.call_id, Math.max(generations.get(call.call_id) || 0, call.generation));
  }
  const textChunks = new Map<string, { reasoning: string[]; content: string[] }>();

  const createCall = (
    event: TraceEvent,
    attempt: number,
    generation: number,
    requestEvent?: TraceEvent,
  ) => {
    const call: ModelCallTranscript = {
      key: `${event.call_id}:${generation}:${attempt}:${event.seq}`,
      call_id: event.call_id || "",
      generation,
      attempt,
      first_seq: event.seq,
      last_seq: event.seq,
      occurred_at: event.occurred_at,
      paper_id: event.paper_id,
      stage: event.stage,
      status: event.type === "llm.stream.started" ? "streaming" : "waiting",
      reasoning: "",
      content: "",
      request_event: requestEvent,
    };
    calls.push(call);
    latestByCall.set(call.call_id, call);
    latestByAttempt.set(`${call.call_id}:${attempt}`, call);
    generations.set(call.call_id, Math.max(generations.get(call.call_id) || 0, generation));
    return call;
  };

  for (const event of ordered) {
    if (event.type === "run.stopped" || event.type === "run.interrupted" || event.type === "paper.stopped" || event.type === "paper.interrupted") {
      for (const call of calls) {
        const paperMatches = !event.paper_id || call.paper_id === event.paper_id;
        if (paperMatches && OPEN_CALL_STATUSES.has(call.status)) {
          call.status = "interrupted";
          call.last_seq = Math.max(call.last_seq, event.seq);
        }
      }
    }

    if (!event.call_id || !event.type.startsWith("llm.")) continue;
    const latest = latestByCall.get(event.call_id);
    const attempt = numericAttempt(event, latest?.attempt || 1);
    const attemptKey = `${event.call_id}:${attempt}`;
    let call = latestByAttempt.get(attemptKey);

    if (event.type === "llm.request.started") {
      const generation = (generations.get(event.call_id) || 0) + 1;
      call = createCall(event, attempt, generation, event);
    } else if (event.type === "llm.stream.started" && (!call || !OPEN_CALL_STATUSES.has(call.status))) {
      const generation = latest?.generation || (generations.get(event.call_id) || 0) + 1;
      call = createCall(event, attempt, generation, latest?.request_event);
    } else if (!call) {
      const generation = latest?.generation || (generations.get(event.call_id) || 0) + 1;
      call = createCall(event, attempt, generation, latest?.request_event);
    }

    call.last_seq = Math.max(call.last_seq, event.seq);
    call.paper_id ||= event.paper_id;
    call.stage ||= event.stage;

    if (event.type === "llm.stream.started") call.status = "streaming";
    if (event.type === "llm.response.delta") {
      call.status = "streaming";
      const channel = event.data?.channel;
      const text = event.data?.text;
      if (typeof text === "string" && (channel === "reasoning" || channel === "content")) {
        const chunks = textChunks.get(call.key) || { reasoning: [], content: [] };
        chunks[channel].push(text);
        textChunks.set(call.key, chunks);
      }
      if (channel === "tool_call") {
        const index = numberData(event, "tool_call_index");
        call.tool_call_count = Math.max(call.tool_call_count || 0, (index ?? 0) + 1);
      }
    }
    if (event.type === "llm.stream.completed") {
      call.model = stringData(event, "model") || call.model;
      const usage = event.data?.usage;
      if (usage && typeof usage === "object" && !Array.isArray(usage)) {
        call.usage = Object.fromEntries(Object.entries(usage).filter(([, value]) => typeof value === "number")) as Record<string, number>;
      }
    }
    if (event.type === "llm.stream.interrupted") call.status = "interrupted";
    if (event.type === "llm.retry.scheduled") call.status = "retrying";
    if (event.type === "llm.retry.exhausted" || event.type === "llm.request.failed") call.status = "failed";
    if (event.type === "llm.stream.unsupported") call.status = "waiting";
    if (event.type === "llm.response.completed") {
      call.status = "completed";
      call.response_event = event;
      call.model = stringData(event, "served_model") || call.model;
      call.finish_reason = stringData(event, "finish_reason") || call.finish_reason;
      call.tool_call_count = numberData(event, "tool_call_count") ?? call.tool_call_count;
      call.duration_ms = event.duration_ms;
      call.usage = event.usage_delta ? { ...event.usage_delta } : call.usage;
    }
  }

  for (const call of calls) {
    const chunks = textChunks.get(call.key);
    if (!chunks) continue;
    if (chunks.reasoning.length > 0) call.reasoning += chunks.reasoning.join("");
    if (chunks.content.length > 0) call.content += chunks.content.join("");
  }
  return { calls, last_seq: ordered.at(-1)?.seq || previous.last_seq };
}

export function mergeTraceEventBatch(items: TraceEvent[], batch: TraceEvent[]) {
  const bySequence = new Map<number, TraceEvent>();
  for (const event of items) bySequence.set(event.seq, event);
  for (const event of batch) bySequence.set(event.seq, event);
  const merged = [...bySequence.values()].sort((left, right) => left.seq - right.seq);
  const structural = merged.filter((event) => event.type !== "llm.response.delta").slice(-MAX_STRUCTURAL_EVENTS);
  const deltas = merged.filter((event) => event.type === "llm.response.delta").slice(-MAX_DELTA_EVENTS);
  return [...structural, ...deltas].sort((left, right) => left.seq - right.seq);
}

function mergeUsageEvents(
  items: Record<number, Record<string, number>>,
  batch: TraceEvent[],
) {
  const merged = { ...items };
  for (const event of batch) {
    if (event.usage_delta && Object.keys(event.usage_delta).length > 0) {
      merged[event.seq] = event.usage_delta as Record<string, number>;
    }
  }
  return Object.fromEntries(
    Object.entries(merged)
      .sort(([left], [right]) => Number(left) - Number(right))
      .slice(-MAX_USAGE_EVENTS),
  );
}

export function useRunTraceStreams({
  campaignId,
  runIds,
  onPaperCompleted,
}: {
  campaignId: string;
  runIds: string[];
  onPaperCompleted?: (runId: string) => void;
}) {
  const [events, setEvents] = useState<Record<string, TraceEvent[]>>({});
  const [graphEvents, setGraphEvents] = useState<Record<string, TraceEvent[]>>({});
  const [usageEvents, setUsageEvents] = useState<Record<string, Record<number, Record<string, number>>>>({});
  const [transcriptStates, setTranscriptStates] = useState<Record<string, ModelTranscriptState>>({});
  const [connections, setConnections] = useState<Record<string, TraceConnectionState>>({});
  const runKey = runIds.join("|");

  useEffect(() => {
    if (runIds.length === 0) return;
    const pending = new Map<string, TraceEvent[]>();
    let flushTimer: number | undefined;
    let disposed = false;

    const flush = () => {
      flushTimer = undefined;
      if (disposed || pending.size === 0) return;
      const batches = [...pending.entries()];
      pending.clear();
      setEvents((current) => {
        const next = { ...current };
        for (const [runId, batch] of batches) next[runId] = mergeTraceEventBatch(current[runId] || [], batch);
        return next;
      });
      setTranscriptStates((current) => {
        const next = { ...current };
        for (const [runId, batch] of batches) next[runId] = mergeModelTranscriptBatch(current[runId], batch);
        return next;
      });
      const structuralBatches = batches
        .map(([runId, batch]) => [runId, batch.filter((event) => event.type !== "llm.response.delta")] as const)
        .filter(([, batch]) => batch.length > 0);
      if (structuralBatches.length > 0) {
        setGraphEvents((current) => {
          const next = { ...current };
          for (const [runId, batch] of structuralBatches) next[runId] = mergeTraceEventBatch(current[runId] || [], batch);
          return next;
        });
      }
      const usageBatches = batches.filter(([, batch]) => batch.some((event) => event.usage_delta && Object.keys(event.usage_delta).length > 0));
      if (usageBatches.length > 0) {
        setUsageEvents((current) => {
          const next = { ...current };
          for (const [runId, batch] of usageBatches) next[runId] = mergeUsageEvents(current[runId] || {}, batch);
          return next;
        });
      }
    };

    const queue = (runId: string, event: TraceEvent) => {
      pending.set(runId, [...(pending.get(runId) || []), event]);
      if (flushTimer === undefined) flushTimer = window.setTimeout(flush, TRACE_FLUSH_MS);
    };

    setConnections((current) => ({
      ...current,
      ...Object.fromEntries(runIds.map((runId) => [runId, "connecting" as const])),
    }));
    const sources = runIds.map((runId) => {
      const source = new EventSource(`/api/runs/${encodeURIComponent(campaignId)}/${encodeURIComponent(runId)}/events`);
      source.onopen = () => setConnections((current) => ({ ...current, [runId]: "connected" }));
      source.onerror = () => setConnections((current) => ({ ...current, [runId]: "reconnecting" }));
      source.addEventListener("trace", (message) => {
        try {
          const event = JSON.parse((message as MessageEvent).data) as TraceEvent;
          queue(runId, event);
          if (event.type === "paper.completed") onPaperCompleted?.(runId);
        } catch {
          // Ignore a malformed individual frame; EventSource owns transport recovery.
        }
      });
      return source;
    });

    return () => {
      disposed = true;
      if (flushTimer !== undefined) window.clearTimeout(flushTimer);
      sources.forEach((source) => source.close());
    };
  }, [campaignId, runKey, onPaperCompleted]);

  const usageTotals = useMemo(() => Object.values(usageEvents)
    .flatMap((items) => Object.values(items))
    .reduce((totals, delta) => {
      for (const [key, value] of Object.entries(delta)) totals[key] = (totals[key] || 0) + Number(value || 0);
      return totals;
    }, {} as Record<string, number>), [usageEvents]);

  const transcripts = useMemo(() => Object.fromEntries(
    Object.entries(transcriptStates).map(([runId, state]) => [runId, state.calls]),
  ), [transcriptStates]);

  return { events, graphEvents, transcripts, usageTotals, connections };
}
