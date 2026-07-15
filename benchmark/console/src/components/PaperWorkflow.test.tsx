import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { PaperDiagnostic, TraceEvent } from "../types";
import { buildWorkflowNodes, groupConsecutiveSteps, PaperWorkflow } from "./PaperWorkflow";

const diagnostic: PaperDiagnostic = {
  paper_id: "2401.02017",
  status: "running",
  stage: "plan",
  error_type: "",
  error_message: "",
  validator_error_count: 0,
  warning_count: 0,
  warning_details_available: false,
  historical_warning_count_only: false,
  validator_groups: [],
  report_available: false,
  retry_eligible: false,
  retry_reason: "",
};

function event(seq: number, type: string, options: Partial<TraceEvent> = {}): TraceEvent {
  return {
    seq,
    type,
    occurred_at: `2026-07-15T00:00:${String(seq).padStart(2, "0")}Z`,
    campaign_id: "hvs-extraction-v2",
    run_id: "regression-c-full",
    method: "C",
    paper_id: diagnostic.paper_id,
    stage: "plan",
    ...options,
  };
}

const events = [
  event(1, "llm.request.started", { call_id: "model-1", summary: "plan call 1" }),
  event(2, "llm.response.completed", { call_id: "model-1", status: "completed" }),
  event(3, "llm.request.started", { call_id: "model-2", summary: "plan call 2" }),
  event(4, "llm.response.completed", { call_id: "model-2", status: "completed" }),
  event(5, "tool.call.started", { call_id: "read-1", summary: "read_lines" }),
  event(6, "tool.call.completed", { call_id: "read-1", summary: "read_lines", status: "completed" }),
  event(7, "tool.call.started", { call_id: "read-2", summary: "read_lines" }),
  event(8, "tool.call.completed", { call_id: "read-2", summary: "read_lines", status: "completed" }),
  event(9, "tool.call.started", { call_id: "search-1", summary: "search" }),
  event(10, "tool.call.completed", { call_id: "search-1", summary: "search", status: "completed" }),
  event(11, "tool.call.started", { call_id: "read-3", summary: "read_lines" }),
];

afterEach(cleanup);

describe("PaperWorkflow", () => {
  it("把所有连续重复步骤分段折叠但保留非连续的同名步骤", () => {
    const segments = groupConsecutiveSteps(events);
    expect(segments.map(({ label, count, status }) => ({ label, count, status }))).toEqual([
      { label: "模型调用", count: 2, status: "completed" },
      { label: "read_lines", count: 2, status: "completed" },
      { label: "search", count: 1, status: "completed" },
      { label: "read_lines", count: 1, status: "running" },
    ]);
  });

  it("按当前阶段标记节点并允许点开查看分段步骤", () => {
    const nodes = buildWorkflowNodes("C", diagnostic, events);
    expect(nodes.find((node) => node.id === "context")?.status).toBe("completed");
    expect(nodes.find((node) => node.id === "plan")?.status).toBe("running");
    expect(nodes.find((node) => node.id === "candidate")?.status).toBe("queued");

    render(<PaperWorkflow method="C" diagnostic={diagnostic} events={events} />);
    expect(screen.getByRole("button", { name: "候选规划：正在运行" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("步骤记录（连续重复已合并）")).toBeInTheDocument();
    expect(screen.getAllByText("× 2").length).toBeGreaterThanOrEqual(2);

    fireEvent.click(screen.getByRole("button", { name: "候选提取：等待" }));
    expect(screen.getByText("该节点尚未开始。")).toBeInTheDocument();
  });
});
