import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ReviewPage } from "./ReviewPage";

const mocks = vi.hoisted(() => ({
  refresh: vi.fn().mockResolvedValue(undefined),
  resetRun: vi.fn().mockResolvedValue({ run_id: "run-failed", status: "reset", removed: [] }),
  resumeGroup: vi.fn().mockResolvedValue({}),
}));

vi.mock("../api", () => ({
  api: { resetRun: mocks.resetRun, resumeGroup: mocks.resumeGroup },
}));

vi.mock("../hooks/useGroup", () => ({
  useGroup: () => ({
    error: "",
    refresh: mocks.refresh,
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
          stream_responses: true,
        },
      }],
    },
  }),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

describe("ReviewPage", () => {
  it("必须输入完整 Run ID 才允许清零", async () => {
    render(<MemoryRouter initialEntries={["/review/group-review"]}><Routes><Route path="/review/:groupId" element={<ReviewPage />} /></Routes></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "清零这个 Run" }));
    const confirmButton = screen.getByRole("button", { name: "确认清零" });
    expect(confirmButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText("输入完整 Run ID 确认"), { target: { value: "run-failed" } });
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);
    await waitFor(() => expect(mocks.resetRun).toHaveBeenCalledWith("run-failed"));
  });
});
