import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RunPage } from "./RunPage";

const mocks = vi.hoisted(() => ({
  run: vi.fn(),
  paperDetail: vi.fn(),
  retryPaper: vi.fn().mockResolvedValue({}),
  retryExternalFailures: vi.fn().mockResolvedValue({}),
  refresh: vi.fn().mockResolvedValue(undefined),
  group: null as any,
}));

vi.mock("../App", () => ({
  useBootstrap: () => ({ campaign_id: "hvs-extraction-v2", papers: ["paper-ok", "paper-failed"] }),
}));

vi.mock("../api", () => ({
  api: {
    run: mocks.run,
    paperDetail: mocks.paperDetail,
    retryPaper: mocks.retryPaper,
    retryExternalFailures: mocks.retryExternalFailures,
    stopGroup: vi.fn(),
    resumeGroup: vi.fn(),
  },
}));

vi.mock("../hooks/useGroup", () => ({
  useGroup: () => ({
    error: "",
    refresh: mocks.refresh,
    group: mocks.group,
  }),
}));

const summary = {
  campaign_id: "hvs-extraction-v2",
  run_id: "run-monitor",
  method: "B",
  status: "failed",
  created_at: "2026-07-15T00:00:00Z",
  finished_at: "2026-07-15T00:01:00Z",
  extractor_model: "model-a",
  reviewer_model: "model-b",
  task_surface: "full",
  papers: ["paper-ok", "paper-failed", "paper-transport"],
  paper_statuses: { "paper-ok": "ok", "paper-failed": "validator_errors", "paper-transport": "transport_error" },
  paper_diagnostics: {
    "paper-ok": { paper_id: "paper-ok", status: "ok", stage: "completed", error_type: "", error_message: "", validator_error_count: 0, warning_count: 0, report_available: true, retry_eligible: false, retry_reason: "成功论文不可重跑" },
    "paper-failed": { paper_id: "paper-failed", status: "validator_errors", stage: "validation", error_type: "validator_errors", error_message: "identifier is required", validator_error_count: 1, warning_count: 0, report_available: true, retry_eligible: false, retry_reason: "需修改工作流后新开实验" },
    "paper-transport": { paper_id: "paper-transport", status: "transport_error", stage: "transport", error_type: "transport_error", error_message: "HTTP 503", validator_error_count: 0, warning_count: 0, report_available: true, retry_eligible: true, retry_reason: "外部服务传输失败，可重试" },
  },
  usage_totals: { prompt_tokens: 100, completion_tokens: 20 },
  trace_precision: "exact",
  read_only: false,
  controllable: false,
  resumable: true,
  sealed: false,
  retryable_papers: ["paper-transport"],
};

beforeEach(() => {
  mocks.group = {
    group_id: "group-monitor",
    status: "needs_review",
    scope: "formal_dev",
    paper_ids: ["paper-ok", "paper-failed", "paper-transport"],
    paused: false,
    max_parallel_experiments: 1,
    experiments: [{
      run_id: "run-monitor",
      status: "failed",
      request: { method: "B", experiment_name: "Method B full", scope: "formal_dev" },
    }],
  };
  mocks.run.mockResolvedValue(summary);
  mocks.paperDetail.mockResolvedValue({
    diagnostic: summary.paper_diagnostics["paper-failed"],
    report: {
      status: "validator_errors",
      validator_errors: ["identifier is required"],
      stage_log: [{ round: 3, errors: 1, errors_sample: ["identifier is required"] }],
    },
    events: [],
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("RunPage paper monitor", () => {
  it("按论文展示状态并下钻失败阶段和错误", async () => {
    render(<MemoryRouter initialEntries={["/runs/group-monitor"]}><Routes><Route path="/runs/:groupId" element={<RunPage />} /></Routes></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "论文运行监控" })).toBeInTheDocument();
    expect(screen.getByText("identifier is required")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看 paper-failed 详情" }));
    await waitFor(() => expect(mocks.paperDetail).toHaveBeenCalledWith("hvs-extraction-v2", "run-monitor", "paper-failed"));
    expect(await screen.findByRole("heading", { name: "paper-failed" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "执行流程" })).toBeInTheDocument();
    expect(screen.getByText("第 3 轮校验")).toBeInTheDocument();
    expect(screen.queryByText("模型输入")).not.toBeInTheDocument();
    expect(screen.queryByText("可见推理")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试这篇论文" })).not.toBeInTheDocument();
  });

  it("只为外部传输故障提供单篇和批量确认重试", async () => {
    mocks.paperDetail.mockResolvedValueOnce({
      diagnostic: summary.paper_diagnostics["paper-transport"],
      report: { status: "transport_error", error: "HTTP 503", transport_error: { category: "server", http_status: 503, manual_retry_eligible: true, provider_request_id: "req-123", stage: "roster", call_id: "paper-transport:roster:1" } },
      events: [],
    });
    render(<MemoryRouter initialEntries={["/runs/group-monitor"]}><Routes><Route path="/runs/:groupId" element={<RunPage />} /></Routes></MemoryRouter>);
    const retryAll = await screen.findByRole("button", { name: "重试全部外部故障（1）" });
    fireEvent.click(retryAll);
    fireEvent.click(screen.getByRole("button", { name: "确认重试 1 篇" }));
    await waitFor(() => expect(mocks.retryExternalFailures).toHaveBeenCalledWith("hvs-extraction-v2", "run-monitor"));

    fireEvent.click(screen.getByRole("button", { name: "查看 paper-transport 详情" }));
    expect(await screen.findByRole("button", { name: "重试这篇论文" })).toBeInTheDocument();
    expect(screen.getByText("req-123")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试这篇论文" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重试 paper-transport" }));
    await waitFor(() => expect(mocks.retryPaper).toHaveBeenCalledWith("hvs-extraction-v2", "run-monitor", "paper-transport"));
  });

  it("成功论文显示警告徽标并按 root_key 展开诊断", async () => {
    const diagnostic = {
      ...summary.paper_diagnostics["paper-ok"],
      warning_count: 2,
      warning_details_available: true,
      validator_groups: [{ severity: "warning", root_key: "method-lineage", count: 2, rule_ids: ["method.semantic"], paths: ["candidates[0].quantities"], messages: ["lineage is incomplete"] }],
    };
    mocks.run.mockResolvedValue({
      ...summary,
      paper_diagnostics: { ...summary.paper_diagnostics, "paper-ok": diagnostic },
    });
    mocks.paperDetail.mockResolvedValueOnce({
      diagnostic,
      report: { status: "ok", validator_warnings: ["first", "second"], validator_groups: diagnostic.validator_groups },
      events: [],
    });
    render(<MemoryRouter initialEntries={["/runs/group-monitor"]}><Routes><Route path="/runs/:groupId" element={<RunPage />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("2 警告")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看 paper-ok 详情" }));
    expect(await screen.findByText("method-lineage")).toBeInTheDocument();
    expect(screen.getByText("lineage is incomplete")).toBeInTheDocument();
  });

  it("定向回归完成后不显示恢复或评估入口", async () => {
    mocks.group = {
      ...mocks.group,
      scope: "regression",
      status: "completed",
      paused: true,
      experiments: [{ ...mocks.group.experiments[0], status: "completed", request: { ...mocks.group.experiments[0].request, scope: "regression" } }],
    };
    mocks.run.mockResolvedValue({ ...summary, status: "completed", scope: "regression", retryable_papers: [] });
    render(<MemoryRouter initialEntries={["/runs/group-monitor"]}><Routes><Route path="/runs/:groupId" element={<RunPage />} /></Routes></MemoryRouter>);
    expect(await screen.findByText(/定向回归 · group-monitor/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "从断点恢复" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始自动评估" })).not.toBeInTheDocument();
  });

  it("旧报告只有 warning 数量时明确标注无详细列表", async () => {
    const diagnostic = {
      ...summary.paper_diagnostics["paper-ok"],
      warning_count: 4,
      warning_details_available: false,
      historical_warning_count_only: true,
    };
    mocks.run.mockResolvedValue({
      ...summary,
      paper_diagnostics: { ...summary.paper_diagnostics, "paper-ok": diagnostic },
    });
    mocks.paperDetail.mockResolvedValueOnce({
      diagnostic,
      report: { status: "ok", validator_warnings_count: 4 },
      events: [],
    });
    render(<MemoryRouter initialEntries={["/runs/group-monitor"]}><Routes><Route path="/runs/:groupId" element={<RunPage />} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "查看 paper-ok 详情" }));
    expect(await screen.findByText("历史警告 · 4")).toBeInTheDocument();
    expect(screen.getByText(/不会用当前 validator 改写历史结论/)).toBeInTheDocument();
  });
});
