import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    { campaign_id: "hvs-extraction-v2", run_id: "legacy-v2", method: "unknown", status: "completed", extractor_model: "old", papers: ["1804.10179"], trace_precision: "legacy_synthesized" },
    { campaign_id: "hvs-extraction-v1", run_id: "legacy-v1", method: "unknown", status: "completed", extractor_model: "old", papers: ["1804.10179"], trace_precision: "legacy_synthesized" },
  ]),
}));

vi.mock("../api", () => ({ api: { groups: mocks.groups, runs: mocks.runs } }));

afterEach(cleanup);

describe("HistoryPage", () => {
  it("按 campaign 分开呈现实验组与未归组单 run", async () => {
    render(<MemoryRouter><HistoryPage /></MemoryRouter>);
    await screen.findByText("legacy-v2");
    const v2Campaign = screen.getByRole("region", { name: "Campaign hvs-extraction-v2" });
    const v1Campaign = screen.getByRole("region", { name: "Campaign hvs-extraction-v1" });
    const v2Disclosure = v2Campaign.querySelector("details");
    expect(v2Disclosure).not.toBeNull();
    expect(v2Disclosure).not.toHaveAttribute("open");
    expect(within(v2Campaign).getByText("group-new")).toBeInTheDocument();
    expect(within(v2Campaign).getByText("legacy-v2")).toBeInTheDocument();
    expect(within(v2Campaign).queryByText("legacy-v1")).not.toBeInTheDocument();
    expect(within(v2Campaign).getByRole("button", { name: "打开 legacy-v2 论文监控" })).toBeInTheDocument();
    expect(within(v2Campaign).queryByRole("button", { name: "打开 grouped-run 论文监控" })).not.toBeInTheDocument();
    expect(within(v1Campaign).getByText("legacy-v1")).toBeInTheDocument();
    expect(within(v1Campaign).queryByText("legacy-v2")).not.toBeInTheDocument();
    fireEvent.click(v2Disclosure?.querySelector("summary") as HTMLElement);
    expect(v2Disclosure).toHaveAttribute("open");
    await waitFor(() => expect(mocks.groups).toHaveBeenCalledOnce());
  });
});
