import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OverviewGraph, paperGraphModel } from "./WorkflowGraph";

afterEach(cleanup);

describe("WorkflowGraph", () => {
  it("失败论文保持红色并可点入下钻", () => {
    const select = vi.fn();
    render(<OverviewGraph papers={["1804.10179", "1807.00427"]} paperStatuses={{ "1804.10179": "failed", "1807.00427": "ok" }} runStatus="failed" onSelect={select} />);
    const failed = screen.getByText("1804.10179").closest(".react-flow__node");
    expect(failed).toHaveClass("status-failed");
    fireEvent.click(failed!);
    expect(select).toHaveBeenCalledWith(expect.objectContaining({ kind: "node", id: "paper:1804.10179" }));
  });

  it("有重试事件时显示回修循环", () => {
    const model = paperGraphModel("C", [{ seq: 1, occurred_at: "2026-07-14T00:00:00Z", campaign_id: "c", run_id: "r", method: "C", type: "llm.retry.scheduled", paper_id: "p", stage: "cand-001", attempt: 2 }]);
    expect(model.edges).toEqual(expect.arrayContaining([expect.objectContaining({ id: "retry:candidate", label: "调用重试", animated: true })]));
  });

  it("节点以最新事件为准，不会因早先的 started 永久停在运行中", () => {
    const model = paperGraphModel("B", [
      { seq: 1, occurred_at: "2026-07-14T00:00:00Z", campaign_id: "c", run_id: "r", method: "B", type: "llm.request.started", paper_id: "p", stage: "scaffold", status: "running" },
      { seq: 2, occurred_at: "2026-07-14T00:00:01Z", campaign_id: "c", run_id: "r", method: "B", type: "llm.response.completed", paper_id: "p", stage: "scaffold", status: "completed" },
    ]);
    expect(model.nodes.find((node) => node.id === "scaffold")?.className).toContain("status-completed");
  });

  it("大量流式事件更新后仍保留完整节点和边", () => {
    const select = vi.fn();
    const papers = ["1804.10179", "1807.00427"];
    const { rerender } = render(<OverviewGraph papers={papers} paperStatuses={{}} runStatus="running" events={[]} onSelect={select} viewKey="run-1" />);
    const events = Array.from({ length: 2400 }, (_, index) => ({
      seq: index + 1,
      occurred_at: "2026-07-14T00:00:00Z",
      campaign_id: "c",
      run_id: "run-1",
      method: "B" as const,
      type: "llm.response.delta",
      paper_id: "1804.10179",
      stage: "scaffold",
    }));

    rerender(<OverviewGraph papers={papers} paperStatuses={{}} runStatus="running" events={events} onSelect={select} viewKey="run-1" />);

    expect(document.querySelectorAll(".react-flow__node")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Fit View" })).toBeInTheDocument();
  });

  it("Method C 尚未写 report 时根据 trace 显示运行中与等待调度，而不是 missing", () => {
    render(<OverviewGraph
      papers={["1804.10179", "1807.00427"]}
      paperStatuses={{ "1804.10179": "missing", "1807.00427": "missing" }}
      runStatus="running"
      events={[{
        seq: 99,
        occurred_at: "2026-07-14T00:00:00Z",
        campaign_id: "c",
        run_id: "r",
        method: "C",
        type: "llm.response.delta",
        paper_id: "1804.10179",
        stage: "review",
      }]}
      onSelect={() => undefined}
    />);

    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByText("等待调度")).toBeInTheDocument();
    expect(screen.queryByText("missing")).not.toBeInTheDocument();
  });
});
