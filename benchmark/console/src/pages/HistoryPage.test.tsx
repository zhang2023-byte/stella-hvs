import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { HistoryPage } from "./HistoryPage";

const mocks = vi.hoisted(() => ({
  groups: vi.fn().mockResolvedValue([{
    schema: { name: "benchmark.dev_experiment_group", version: 1 },
    group_id: "group-new",
    campaign_id: "hvs-extraction-v2",
    split: "dev",
    status: "completed",
    paused: false,
    max_parallel_experiments: 2,
    created_at: "2026-07-14T00:00:00Z",
    updated_at: "2026-07-14T00:00:00Z",
    experiments: [{ run_id: "grouped-run", status: "completed", position: 0, queue_mode: "start", request: {} }],
  }]),
  runs: vi.fn().mockResolvedValue([
    { campaign_id: "hvs-extraction-v2", run_id: "grouped-run", method: "B", status: "completed", extractor_model: "m", papers: [], trace_precision: "exact" },
    { campaign_id: "hvs-extraction-v2", run_id: "legacy-run", method: "unknown", status: "completed", extractor_model: "old", papers: ["1804.10179"], trace_precision: "legacy_synthesized" },
  ]),
}));

vi.mock("../api", () => ({ api: { groups: mocks.groups, runs: mocks.runs } }));

afterEach(cleanup);

describe("HistoryPage", () => {
  it("把没有实验组元数据的旧 run 放入兼容历史", async () => {
    render(<MemoryRouter><HistoryPage /></MemoryRouter>);
    await screen.findByText("legacy-run");
    const legacySection = screen.getByText("兼容的单 Run").closest("section");
    expect(legacySection).not.toBeNull();
    expect(within(legacySection as HTMLElement).getByText("legacy-run")).toBeInTheDocument();
    expect(within(legacySection as HTMLElement).queryByText("grouped-run")).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.groups).toHaveBeenCalledOnce());
  });
});
