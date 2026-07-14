import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TraceEvent } from "../types";
import { mergeModelTranscriptBatch, mergeTraceEventBatch, useRunTraceStreams } from "./useRunTraceStreams";

type EventListenerLike = EventListenerOrEventListenerObject;

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  readonly withCredentials = false;
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSED = 2;
  readyState = this.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  close = vi.fn(() => { this.readyState = this.CLOSED; });
  private listeners = new Map<string, EventListenerLike[]>();

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerLike | null) {
    if (!listener) return;
    this.listeners.set(type, [...(this.listeners.get(type) || []), listener]);
  }

  removeEventListener(type: string, listener: EventListenerLike | null) {
    if (!listener) return;
    this.listeners.set(type, (this.listeners.get(type) || []).filter((item) => item !== listener));
  }

  dispatchEvent() { return true; }

  open() {
    this.readyState = this.OPEN;
    this.onopen?.(new Event("open"));
  }

  fail() {
    this.readyState = this.CONNECTING;
    this.onerror?.(new Event("error"));
  }

  trace(event: TraceEvent) {
    const message = new MessageEvent("trace", { data: JSON.stringify(event) });
    for (const listener of this.listeners.get("trace") || []) {
      if (typeof listener === "function") listener(message);
      else listener.handleEvent(message);
    }
  }
}

function traceEvent(seq: number, type = "llm.response.delta", extra: Partial<TraceEvent> = {}): TraceEvent {
  return {
    seq,
    occurred_at: "2026-07-14T00:00:00Z",
    campaign_id: "campaign",
    run_id: "run-1",
    method: "B",
    type,
    paper_id: "1804.10179",
    stage: "scaffold",
    ...extra,
  };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useRunTraceStreams", () => {
  it("按批刷新 delta，并只把结构事件交给运行图", () => {
    const completed = vi.fn();
    const { result } = renderHook(() => useRunTraceStreams({
      campaignId: "campaign",
      runIds: ["run-1"],
      onPaperCompleted: completed,
    }));
    const source = FakeEventSource.instances[0];

    act(() => {
      for (let seq = 1; seq <= 200; seq += 1) source.trace(traceEvent(seq));
      source.trace(traceEvent(201, "paper.started", { status: "running" }));
      source.trace(traceEvent(202, "paper.completed", { status: "completed" }));
    });

    expect(result.current.events["run-1"]).toBeUndefined();
    expect(completed).toHaveBeenCalledWith("run-1");

    act(() => { vi.advanceTimersByTime(100); });

    expect(result.current.events["run-1"]).toHaveLength(202);
    expect(result.current.graphEvents["run-1"].map((event) => event.type)).toEqual(["paper.started", "paper.completed"]);
  });

  it("根据 EventSource 的真实状态显示连接、重连，并按 seq 去重 usage", () => {
    const { result } = renderHook(() => useRunTraceStreams({ campaignId: "campaign", runIds: ["run-1"] }));
    const source = FakeEventSource.instances[0];

    expect(result.current.connections["run-1"]).toBe("connecting");
    act(() => { source.open(); });
    expect(result.current.connections["run-1"]).toBe("connected");
    act(() => { source.fail(); });
    expect(result.current.connections["run-1"]).toBe("reconnecting");

    act(() => {
      const usage = traceEvent(50, "llm.response.completed", { usage_delta: { prompt_tokens: 10, completion_tokens: 3 } });
      source.trace(usage);
      source.trace(usage);
      vi.advanceTimersByTime(100);
    });

    expect(result.current.usageTotals).toEqual({ prompt_tokens: 10, completion_tokens: 3 });
  });

  it("批量合并时保留最近 1200 个结构事件和 2400 个 delta", () => {
    const structural = Array.from({ length: 1300 }, (_, index) => traceEvent(index + 1, "paper.started"));
    const deltas = Array.from({ length: 2500 }, (_, index) => traceEvent(index + 2000));
    const merged = mergeTraceEventBatch([], [...structural, ...deltas]);

    expect(merged.filter((event) => event.type === "paper.started")).toHaveLength(1200);
    expect(merged.filter((event) => event.type === "llm.response.delta")).toHaveLength(2400);
  });

  it("把大量 delta 聚合成一个持续增长的模型回复，并分离可见推理与正文", () => {
    const deltas = Array.from({ length: 20_000 }, (_, index) => traceEvent(index + 2, "llm.response.delta", {
      call_id: "1804.10179:scaffold:1",
      attempt: 1,
      data: { channel: index % 2 === 0 ? "reasoning" : "content", text: String(index % 10) },
    }));
    const state = mergeModelTranscriptBatch(undefined, [
      traceEvent(1, "llm.request.started", { call_id: "1804.10179:scaffold:1", attempt: 1 }),
      ...deltas,
      traceEvent(20_002, "llm.response.completed", {
        call_id: "1804.10179:scaffold:1",
        status: "completed",
        duration_ms: 4_200,
        usage_delta: { completion_tokens: 2_000, reasoning_tokens: 1_000 },
        data: { served_model: "deepseek-v4-pro", tool_call_count: 0 },
      }),
    ]);

    expect(state.calls).toHaveLength(1);
    expect(state.calls[0].reasoning).toHaveLength(10_000);
    expect(state.calls[0].content).toHaveLength(10_000);
    expect(state.calls[0]).toMatchObject({
      status: "completed",
      model: "deepseek-v4-pro",
      duration_ms: 4_200,
      usage: { completion_tokens: 2_000, reasoning_tokens: 1_000 },
    });
  });

  it("忽略 SSE 重放的旧 seq，并在 call_id 被论文重跑复用时新建调用代次", () => {
    const first = mergeModelTranscriptBatch(undefined, [
      traceEvent(1, "llm.request.started", { call_id: "shared-call", attempt: 1 }),
      traceEvent(2, "llm.response.delta", { call_id: "shared-call", attempt: 1, data: { channel: "content", text: "first" } }),
      traceEvent(3, "llm.response.completed", { call_id: "shared-call", status: "completed" }),
    ]);
    const second = mergeModelTranscriptBatch(first, [
      traceEvent(2, "llm.response.delta", { call_id: "shared-call", attempt: 1, data: { channel: "content", text: "first" } }),
      traceEvent(4, "llm.request.started", { call_id: "shared-call", attempt: 1 }),
      traceEvent(5, "llm.response.delta", { call_id: "shared-call", attempt: 1, data: { channel: "content", text: "second" } }),
    ]);

    expect(second.calls.map((call) => call.content)).toEqual(["first", "second"]);
    expect(second.calls[1].generation).toBe(2);
  });

  it("把断流后的网络重试拆成独立 attempt，避免重复拼接部分输出", () => {
    const state = mergeModelTranscriptBatch(undefined, [
      traceEvent(1, "llm.request.started", { call_id: "retry-call", attempt: 1 }),
      traceEvent(2, "llm.response.delta", { call_id: "retry-call", attempt: 1, data: { channel: "content", text: "partial" } }),
      traceEvent(3, "llm.stream.interrupted", { call_id: "retry-call", attempt: 1 }),
      traceEvent(4, "llm.retry.scheduled", { call_id: "retry-call", attempt: 1, data: { next_attempt: 2 } }),
      traceEvent(5, "llm.stream.started", { call_id: "retry-call", attempt: 2 }),
      traceEvent(6, "llm.response.delta", { call_id: "retry-call", attempt: 2, data: { channel: "content", text: "complete" } }),
      traceEvent(7, "llm.response.completed", { call_id: "retry-call", status: "completed" }),
    ]);

    expect(state.calls.map((call) => ({ attempt: call.attempt, status: call.status, content: call.content }))).toEqual([
      { attempt: 1, status: "retrying", content: "partial" },
      { attempt: 2, status: "completed", content: "complete" },
    ]);
  });
});
