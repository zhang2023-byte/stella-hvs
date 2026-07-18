import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { GroupRequest } from "../types";

const bootstrap = {
  campaign_id: "hvs-extraction-v2",
  split: "dev",
  papers: Array.from({ length: 10 }, (_, index) => `paper-${index}`),
  models: ["deepseek-v4-pro", "glm-5.2"],
  defaults: { reviewer_model: "glm-5.2", task_surface: "core_prov", parallel: 1, max_repair_rounds: 3, timeout_seconds: 1800, batch_size: 8, provider_pin: true, max_parallel_experiments: 2 },
  credentials: { api_key_configured: true, base_url_configured: true },
  session_token: "test-token",
  capabilities: { experiment_groups: true },
};

function json(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
}

describe("SetupPage", () => {
  beforeEach(() => {
    history.replaceState({}, "", "/setup");
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => `key-${Math.random()}`) });
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("可以添加、复制和删除多个实验卡", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json(bootstrap)));
    render(<BrowserRouter><App /></BrowserRouter>);
    expect(await screen.findByRole("heading", { name: "先把实验配置清楚，再开始运行。" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "＋ 添加另一个实验" }));
    expect(screen.getAllByText("纳入本次运行")).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", { name: "复制" })[0]);
    expect(screen.getAllByText("纳入本次运行")).toHaveLength(3);
    fireEvent.click(screen.getAllByRole("button", { name: "删除" })[2]);
    expect(screen.getAllByText("纳入本次运行")).toHaveLength(2);
  });

  it("参数改变后使预检失效，只有重新检查才能启动", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/bootstrap") return json(bootstrap);
      if (path.endsWith("/preflight")) {
        const request = JSON.parse(String(init?.body));
        return json({ ...request, ok: true, group_checks: [{ name: "group", ok: true, detail: "ready" }], experiments: request.experiments.map((experiment: Record<string, unknown>) => ({ run_id: experiment.run_id, ok: true, checks: [], command: [], request: experiment })), request });
      }
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<BrowserRouter><App /></BrowserRouter>);
    const checkButton = await screen.findByRole("button", { name: "运行全部检查" });
    fireEvent.click(checkButton);
    await waitFor(() => expect(screen.getByRole("button", { name: /开始运行/ })).toBeEnabled());
    fireEvent.change(screen.getByLabelText("实验 1 名称"), { target: { value: "修改后的实验" } });
    expect(screen.getByRole("button", { name: /开始运行/ })).toBeDisabled();
  });

  it("固定使用整包响应且不再暴露流式开关", async () => {
    let preflightRequest: Record<string, unknown> | undefined;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/bootstrap") return json(bootstrap);
      if (path.endsWith("/preflight")) {
        preflightRequest = JSON.parse(String(init?.body));
        const request = preflightRequest as { experiments: Record<string, unknown>[] };
        return json({ ...request, ok: true, group_checks: [], experiments: request.experiments.map((experiment) => ({ run_id: experiment.run_id, ok: true, checks: [], command: [], request: experiment })), request });
      }
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<BrowserRouter><App /></BrowserRouter>);
    expect(await screen.findByRole("heading", { name: "先把实验配置清楚，再开始运行。" })).toBeInTheDocument();
    expect(screen.queryByText("实时流式显示模型响应（Dev Console 专用）")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "运行全部检查" }));
    await waitFor(() => expect(preflightRequest).toBeDefined());
    const request = preflightRequest as { experiments: { stream_responses: boolean }[] };
    expect(request.experiments[0].stream_responses).toBe(false);
  });

  it("新实验固定使用 B-core，C 和 FULL 只保留历史读取", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json(bootstrap)));
    render(<BrowserRouter><App /></BrowserRouter>);
    const surface = await screen.findByLabelText("实验 1 任务范围");
    expect(surface).toBeDisabled();
    expect(surface).toHaveValue("core_prov");
    expect(screen.getByText("Method B")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Method C" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /FULL/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /定向回归/ }));
    expect(surface).toBeDisabled();
    expect(surface).toHaveValue("core_prov");
    expect(screen.queryByRole("option", { name: /FULL/ })).not.toBeInTheDocument();
  });

  it("定向回归默认选择三篇且把同一范围提交到组级预检", async () => {
    let preflightRequest: { scope?: string; paper_ids?: string[] } | undefined;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/bootstrap") return json(bootstrap);
      if (path.endsWith("/preflight")) {
        preflightRequest = JSON.parse(String(init?.body));
        const request = preflightRequest as GroupRequest;
        return json({ ok: true, group_checks: [], experiments: request.experiments.map((experiment) => ({ run_id: experiment.run_id, ok: true, checks: [], command: [], request: experiment })), request });
      }
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<BrowserRouter><App /></BrowserRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /定向回归/ }));
    expect(screen.getByText("同组所有实验使用完全相同的论文集合。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "运行全部检查" }));
    await waitFor(() => expect(preflightRequest).toBeDefined());
    expect(preflightRequest?.scope).toBe("regression");
    expect(preflightRequest?.paper_ids).toEqual(["paper-0", "paper-1", "paper-2"]);
  });
});
