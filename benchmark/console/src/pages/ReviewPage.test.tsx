import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ReviewPage } from "./ReviewPage";

vi.mock("../api", () => ({ api: {} }));

vi.mock("../hooks/useGroup", () => ({
  useGroup: () => ({
    error: "",
    group: {
      schema: { name: "benchmark.dev_experiment_group", version: 1 },
      group_id: "group-review",
      campaign_id: "hvs-extraction-v2",
      split: "dev",
      status: "needs_review",
      paused: true,
      max_parallel_experiments: 2,
      created_at: "2026-07-14T00:00:00Z",
      updated_at: "2026-07-14T00:00:00Z",
      experiments: [{
        run_id: "run-failed",
        status: "failed",
        queue_mode: "resume",
        position: 0,
        error: "provider interrupted",
        request: {
          method: "B",
          run_id: "run-failed",
          extractor_model: "model-a",
          reviewer_model: "model-b",
          task_surface: "full",
          parallel: 1,
          max_repair_rounds: 2,
          timeout_seconds: 60,
          batch_size: 1,
          max_tokens: null,
          provider_pin: false,
          providers: [],
          fallback_models: [],
          stream_responses: false,
        },
      }],
    },
  }),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

describe("ReviewPage", () => {
  it("工作流错误只引导新开实验，不提供恢复或清零重跑", async () => {
    render(<MemoryRouter initialEntries={["/review/group-review"]}><Routes><Route path="/review/:groupId" element={<ReviewPage />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("修复代码后新建实验，不修改旧 Run。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "从断点恢复" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "清零这个 Run" })).not.toBeInTheDocument();
  });
});
