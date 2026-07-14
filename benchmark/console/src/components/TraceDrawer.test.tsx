import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { TraceDrawer } from "./TraceDrawer";
import type { TraceEvent } from "../types";
import type { ModelCallTranscript } from "../hooks/useRunTraceStreams";

afterEach(cleanup);

describe("TraceDrawer", () => {
  const transcript: ModelCallTranscript = {
    key: "call:1:1",
    call_id: "call",
    generation: 1,
    attempt: 1,
    first_seq: 1,
    last_seq: 5,
    occurred_at: "2026-07-14T00:00:00Z",
    paper_id: "p",
    stage: "plan",
    status: "streaming",
    reasoning: "visible reasoning",
    content: "answer in progress",
  };

  it("默认把 delta 聚合为一个会话回复，并折叠 Provider 可见推理", () => {
    const events: TraceEvent[] = [
      { seq: 1, occurred_at: "2026-07-14T00:00:00Z", campaign_id: "c", run_id: "r", method: "C", type: "llm.response.delta", call_id: "call", attempt: 1, paper_id: "p", stage: "plan", node_id: "plan", data: { channel: "reasoning", text: "visible " } },
      { seq: 2, occurred_at: "2026-07-14T00:00:01Z", campaign_id: "c", run_id: "r", method: "C", type: "llm.response.delta", call_id: "call", attempt: 1, paper_id: "p", stage: "plan", node_id: "plan", data: { channel: "reasoning", text: "reasoning" } },
      { seq: 3, occurred_at: "2026-07-14T00:00:02Z", campaign_id: "c", run_id: "r", method: "C", type: "llm.response.delta", call_id: "call", attempt: 1, paper_id: "p", stage: "plan", node_id: "plan", data: { channel: "content", text: "answer in progress" } },
    ];
    render(<TraceDrawer campaignId="c" runId="r" paperId="p" selection={{ kind: "node", id: "plan", label: "规划候选" }} events={events} transcripts={[transcript]} onClose={() => undefined} />);
    expect(screen.getByText(/不会展示或推测隐藏思考/)).toBeInTheDocument();
    expect(screen.getByText("answer in progress")).toBeInTheDocument();
    expect(screen.queryByText("llm.response.delta")).not.toBeInTheDocument();
    const disclosure = screen.getByText("正在思考…").closest("details");
    expect(disclosure).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("正在思考…"));
    expect(disclosure).toHaveAttribute("open");
    expect(screen.getByText("visible reasoning")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "原始 Trace" }));
    expect(screen.getAllByText("llm.response.delta")).toHaveLength(3);
  });

  it("把工具开始与完成事件合并成一张工具卡片", () => {
    const events: TraceEvent[] = [
      { seq: 10, occurred_at: "2026-07-14T00:00:00Z", campaign_id: "c", run_id: "r", method: "C", type: "tool.call.started", call_id: "tool-1", paper_id: "p", stage: "plan", node_id: "plan", summary: "search_paper", status: "running" },
      { seq: 11, occurred_at: "2026-07-14T00:00:01Z", campaign_id: "c", run_id: "r", method: "C", type: "tool.call.completed", call_id: "tool-1", paper_id: "p", stage: "plan", node_id: "plan", summary: "search_paper", status: "completed", duration_ms: 850 },
    ];
    render(<TraceDrawer campaignId="c" runId="r" paperId="p" selection={{ kind: "node", id: "plan", label: "规划候选" }} events={events} transcripts={[]} onClose={() => undefined} />);

    expect(screen.getByText("search_paper")).toBeInTheDocument();
    expect(screen.getByText("已完成 · 850 ms")).toBeInTheDocument();
    expect(screen.getAllByText("search_paper")).toHaveLength(1);
  });

  it("历史 run 已停止时不再把未闭合调用标成正在回复", () => {
    render(<TraceDrawer campaignId="c" runId="r" paperId="p" selection={{ kind: "node", id: "plan", label: "规划候选" }} events={[]} transcripts={[transcript]} runStatus="stopped" onClose={() => undefined} />);

    expect(screen.getByText("已中断")).toBeInTheDocument();
    expect(screen.queryByText("实时生成中")).not.toBeInTheDocument();
    expect(screen.getByText("本次可见推理（已中断）")).toBeInTheDocument();
  });
});
