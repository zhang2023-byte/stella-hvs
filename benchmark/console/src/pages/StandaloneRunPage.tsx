import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { PageIntro } from "../components/PageIntro";
import { StatusPill } from "../components/StatusPill";
import type { RunSummary } from "../types";
import { PaperMonitor } from "./RunPage";

export function StandaloneRunPage() {
  const { campaignId = "", runId = "" } = useParams();
  const navigate = useNavigate();
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try {
      setSummary(await api.run(campaignId, runId));
      setError("");
    } catch (reason) {
      setError((reason as Error).message);
    }
  }, [campaignId, runId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  if (!summary) return <div className="page"><div className="empty-state"><span className="spinner" /><p>{error || "正在读取 Run…"}</p></div></div>;
  const totalTokens = summary.usage_totals.total_tokens
    || (summary.usage_totals.prompt_tokens || 0) + (summary.usage_totals.completion_tokens || 0);
  return <div className="page standalone-run-page">
    <PageIntro
      eyebrow={summary.sealed ? "已封存 Run · 只读" : `未封存 Run · Method ${summary.method}`}
      title="论文运行监控"
      description={summary.sealed
        ? "封存后不可修改或重试。你仍可查看每篇论文的报告和错误。"
        : "直接复用已经保存的论文报告进行调试；只有明确的外部服务传输故障可以重试。"}
      actions={<button className="secondary-button" onClick={() => navigate("/history")}>← 返回历史记录</button>}
    />
    {error && <p className="inline-error">{error}</p>}
    <section className="telemetry-strip standalone-telemetry">
      <div><small>Run 状态</small><StatusPill status={summary.status} /></div>
      <div><small>任务范围</small><strong>{summary.task_surface}</strong></div>
      <div><small>提取模型</small><strong>{summary.extractor_model || "未知"}</strong></div>
      <div><small>论文</small><strong>{summary.papers.length}</strong></div>
      <div><small>总 tokens</small><strong>{totalTokens.toLocaleString()}</strong></div>
      <div><small>数据来源</small><strong>paper reports</strong></div>
    </section>
    <div className="standalone-monitor-shell">
      <PaperMonitor campaignId={campaignId} runId={runId} summary={summary} fallbackPapers={summary.papers} onRetryStarted={refresh} />
    </div>
  </div>;
}
