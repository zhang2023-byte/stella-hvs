import { useEffect, useMemo, useState } from "react";
import type { TraceEvent } from "../types";

const TRACE_FLUSH_MS = 100;
const MAX_STRUCTURAL_EVENTS = 1200;
const MAX_DELTA_EVENTS = 2400;
const MAX_USAGE_EVENTS = 5000;

export type TraceConnectionState = "connecting" | "connected" | "reconnecting";

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

  return { events, graphEvents, usageTotals, connections };
}
