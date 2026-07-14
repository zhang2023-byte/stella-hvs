import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TraceEvent } from "../types";
import { mergeTraceEventBatch, useRunTraceStreams } from "./useRunTraceStreams";

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
});
