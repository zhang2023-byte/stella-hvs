import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { TraceDrawer } from "./TraceDrawer";
import type { TraceEvent } from "../types";

afterEach(cleanup);

describe("TraceDrawer", () => {
  it("将 provider 可见 reasoning 与普通输出分栏且声明边界", () => {
    const events: TraceEvent[] = [
      { seq: 1, occurred_at: "2026-07-14T00:00:00Z", campaign_id: "c", run_id: "r", method: "C", type: "llm.response.delta", paper_id: "p", stage: "plan", node_id: "plan", data: { channel: "reasoning", text: "visible reasoning" } },
      { seq: 2, occurred_at: "2026-07-14T00:00:01Z", campaign_id: "c", run_id: "r", method: "C", type: "llm.response.delta", paper_id: "p", stage: "plan", node_id: "plan", data: { channel: "content", text: "answer" } },
    ];
    render(<TraceDrawer campaignId="c" runId="r" paperId="p" selection={{ kind: "node", id: "plan", label: "规划候选" }} events={events} onClose={() => undefined} />);
    expect(screen.getByText(/不会展示或推测隐藏思考/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "可见推理" }));
    expect(screen.getByText("visible reasoning")).toBeInTheDocument();
    expect(screen.queryByText("answer")).not.toBeInTheDocument();
  });
});
