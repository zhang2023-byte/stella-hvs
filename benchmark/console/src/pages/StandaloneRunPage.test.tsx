import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StandaloneRunPage } from "./StandaloneRunPage";

const mocks = vi.hoisted(() => ({
  run: vi.fn(),
  paperDetail: vi.fn(),
  retryPaper: vi.fn(),
  retryExternalFailures: vi.fn(),
}));

vi.mock("../api", () => ({ api: mocks }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("StandaloneRunPage", () => {
  it("把已封存 Run 明确标为只读且不暴露任何重试入口", async () => {
    mocks.run.mockResolvedValue({
      campaign_id: "hvs-extraction-v2",
      run_id: "sealed-run",
      method: "B",
      status: "sealed",
      created_at: "2026-07-15T00:00:00Z",
      finished_at: "",
      extractor_model: "model-a",
      reviewer_model: "model-b",
      task_surface: "full",
      papers: ["paper-transport"],
      paper_statuses: { "paper-transport": "transport_error" },
      paper_diagnostics: {
        "paper-transport": {
          paper_id: "paper-transport",
          status: "transport_error",
          stage: "transport",
          error_type: "transport_error",
          error_message: "HTTP 503",
          validator_error_count: 0,
          warning_count: 0,
          report_available: true,
          retry_eligible: false,
          retry_reason: "Run 已封存，只读",
        },
      },
      usage_totals: {},
      trace_precision: "legacy_synthesized",
      read_only: true,
      controllable: false,
      resumable: false,
      sealed: true,
      retryable_papers: [],
    });
    render(<MemoryRouter initialEntries={["/runs/single/hvs-extraction-v2/sealed-run"]}><Routes><Route path="/runs/single/:campaignId/:runId" element={<StandaloneRunPage />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("已封存 Run · 只读")).toBeInTheDocument();
    expect(screen.getByText("封存后不可修改或重试。你仍可查看每篇论文的报告和错误。" )).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument();
  });
});
