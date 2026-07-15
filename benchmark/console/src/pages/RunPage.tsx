import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useBootstrap } from "../App";
import { api } from "../api";
import { PageIntro } from "../components/PageIntro";
import { StatusPill } from "../components/StatusPill";
import { useGroup } from "../hooks/useGroup";
import type { PaperDetail, PaperDiagnostic, RunSummary } from "../types";

const successStatuses = new Set(["ok", "ok_with_cjk_warnings"]);

function useClock(startedAt?: string, finishedAt?: string) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  if (!startedAt) return "00:00:00";
  const elapsed = Math.max(0, (finishedAt ? new Date(finishedAt).getTime() : now) - new Date(startedAt).getTime());
  const seconds = Math.floor(elapsed / 1000);
  return [Math.floor(seconds / 3600), Math.floor((seconds % 3600) / 60), seconds % 60]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}

function statusKind(status: string) {
  if (successStatuses.has(status)) return "completed";
  if (status === "running") return "running";
  if (["missing", "queued"].includes(status)) return "queued";
  return "failed";
}

function paperStatusLabel(status: string) {
  if (successStatuses.has(status)) return "OK";
  if (status === "running") return "运行中";
  if (["missing", "queued"].includes(status)) return "等待中";
  return "失败";
}

function errorTypeLabel(status: string) {
  const labels: Record<string, string> = {
    validator_errors: "校验错误",
    review_failed: "复核失败",
    transport_error: "传输错误",
    invalid_report: "报告损坏",
    harness_error: "运行器错误",
    failed: "运行失败",
  };
  return labels[status] || status.replaceAll("_", " ");
}

function stageLabel(stage: string) {
  if (!stage || stage === "queued") return "等待调度";
  if (stage === "completed") return "全部完成";
  if (stage === "context") return "上下文准备";
  if (stage === "scaffold") return "候选框架";
  if (stage === "plan") return "规划与工具循环";
  if (stage === "validation" || stage.startsWith("valid")) return "结构校验";
  if (stage === "review" || stage.startsWith("review")) return "独立复核";
  if (stage === "transport") return "模型传输";
  if (stage.startsWith("batch") || stage.startsWith("cand-")) return `提取 · ${stage}`;
  if (stage.startsWith("repair")) return `修复 · ${stage}`;
  if (stage === "final") return "最终交付";
  return stage;
}

function fallbackDiagnostic(paperId: string, status = "missing"): PaperDiagnostic {
  return {
    paper_id: paperId,
    status,
    stage: successStatuses.has(status) ? "completed" : status === "running" ? "running" : "queued",
    error_type: successStatuses.has(status) || status === "missing" ? "" : status,
    error_message: "",
    validator_error_count: 0,
    warning_count: 0,
    report_available: status !== "missing",
    retry_eligible: false,
    retry_reason: "尚无可重试的外部服务失败报告",
  };
}

function stageEntryLabel(entry: Record<string, unknown>) {
  if (typeof entry.round === "number") return `第 ${entry.round} 轮校验`;
  const stage = String(entry.stage || entry.unit || "运行记录");
  return stageLabel(stage);
}

function stageEntrySummary(entry: Record<string, unknown>) {
  if (typeof entry.parse_error === "string") return entry.parse_error;
  if (entry.failed === true) return "该阶段失败";
  if (typeof entry.errors === "number") return `${entry.errors} 个错误`;
  if (typeof entry.calls === "number") return `${entry.calls} 次调用`;
  const structureErrors = Array.isArray(entry.structure_errors) ? entry.structure_errors : [];
  if (structureErrors.length) return String(structureErrors[0]);
  return "已记录";
}

function PaperDetailPanel({ detail, loading, error, onClose, onRetry }: {
  detail: PaperDetail | null;
  loading: boolean;
  error: string;
  onClose: () => void;
  onRetry: (paperId: string) => void;
}) {
  const diagnostic = detail?.diagnostic;
  const report = detail?.report;
  const stageLog = Array.isArray(report?.stage_log) ? report.stage_log : [];
  const validatorErrors = Array.isArray(report?.validator_errors) ? report.validator_errors : [];
  const warnings = Array.isArray(report?.validator_warnings)
    ? report.validator_warnings
    : Array.isArray(report?.warnings) ? report.warnings : [];

  return (
    <aside className="paper-detail-panel" aria-live="polite">
      <div className="paper-detail-head">
        <div><p className="eyebrow">论文详情</p><h2>{diagnostic?.paper_id || "正在读取…"}</h2></div>
        <button className="icon-button" aria-label="关闭论文详情" onClick={onClose}>×</button>
      </div>
      {loading && <div className="empty-state compact"><span className="spinner" /><p>正在读取该论文的运行报告…</p></div>}
      {error && <p className="inline-error">{error}</p>}
      {!loading && diagnostic && <div className="paper-detail-scroll">
        <section className="paper-detail-summary">
          <StatusPill status={statusKind(diagnostic.status)} />
          <div><small>当前 / 失败环节</small><strong>{stageLabel(diagnostic.stage)}</strong></div>
          {diagnostic.error_type && <div><small>错误类型</small><strong>{errorTypeLabel(diagnostic.error_type)}</strong></div>}
          {diagnostic.error_message && <p>{diagnostic.error_message}</p>}
          {diagnostic.retry_eligible
            ? <button className="primary-button retry-paper-button" onClick={() => onRetry(diagnostic.paper_id)}>重试这篇论文</button>
            : diagnostic.error_type && <small className="retry-guidance">{diagnostic.retry_reason}</small>}
        </section>

        {stageLog.length > 0 && <section className="paper-detail-section">
          <h3>环节记录</h3>
          <ol className="stage-timeline">
            {stageLog.map((entry, index) => <li key={index}>
              <span aria-hidden="true" />
              <div><strong>{stageEntryLabel(entry)}</strong><small>{stageEntrySummary(entry)}</small></div>
            </li>)}
          </ol>
        </section>}

        {validatorErrors.length > 0 && <section className="paper-detail-section error-list">
          <h3>校验错误 · {validatorErrors.length}</h3>
          <ul>{validatorErrors.map((item, index) => <li key={index}>{String(item)}</li>)}</ul>
        </section>}

        {warnings.length > 0 && <section className="paper-detail-section warning-list">
          <h3>警告 · {warnings.length}</h3>
          <ul>{warnings.map((item, index) => <li key={index}>{String(item)}</li>)}</ul>
        </section>}

        {!report && (detail?.events.length || 0) > 0 && <section className="paper-detail-section">
          <h3>当前进度</h3>
          <ol className="stage-timeline">
            {detail?.events.map((event) => <li key={event.seq}>
              <span aria-hidden="true" />
              <div><strong>{stageLabel(event.stage || "running")}</strong><small>{event.type}</small></div>
            </li>)}
          </ol>
        </section>}
      </div>}
    </aside>
  );
}

function paperDiagnostics(summary: RunSummary | undefined, fallbackPapers: string[]) {
  return (summary?.papers || fallbackPapers).map((paperId) =>
    summary?.paper_diagnostics?.[paperId]
      || fallbackDiagnostic(paperId, summary?.paper_statuses?.[paperId]),
  );
}

function diagnosticCounts(diagnostics: PaperDiagnostic[]) {
  return diagnostics.reduce((value, item) => {
    const kind = statusKind(item.status);
    value[kind] = (value[kind] || 0) + 1;
    return value;
  }, {} as Record<string, number>);
}

export function PaperMonitor({ campaignId, runId, summary, fallbackPapers, onRetryStarted }: {
  campaignId: string;
  runId: string;
  summary: RunSummary | undefined;
  fallbackPapers: string[];
  onRetryStarted?: () => void | Promise<void>;
}) {
  const [detail, setDetail] = useState<PaperDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [retryError, setRetryError] = useState("");
  const [retryBusy, setRetryBusy] = useState(false);
  const [retryConfirmation, setRetryConfirmation] = useState<
    { kind: "paper"; paperId: string } | { kind: "all"; count: number } | null
  >(null);
  const diagnostics = paperDiagnostics(summary, fallbackPapers);
  const counts = diagnosticCounts(diagnostics);
  const retryablePapers = summary?.retryable_papers || [];

  async function openPaper(paper: PaperDiagnostic) {
    setDetail({ diagnostic: paper, report: null, events: [] });
    setDetailError("");
    setDetailLoading(true);
    try {
      setDetail(await api.paperDetail(campaignId, runId, paper.paper_id));
    } catch (reason) {
      setDetailError((reason as Error).message);
    } finally {
      setDetailLoading(false);
    }
  }

  async function confirmRetry() {
    if (!retryConfirmation) return;
    setRetryBusy(true);
    setRetryError("");
    try {
      if (retryConfirmation.kind === "paper") {
        await api.retryPaper(campaignId, runId, retryConfirmation.paperId);
      } else {
        await api.retryExternalFailures(campaignId, runId);
      }
      setRetryConfirmation(null);
      await onRetryStarted?.();
    } catch (reason) {
      setRetryError((reason as Error).message);
    } finally {
      setRetryBusy(false);
    }
  }

  return <section className="paper-monitor-panel">
    <div className="paper-monitor-toolbar">
      <div><p className="eyebrow">{runId}</p><h2>论文结果</h2></div>
      <div className="paper-monitor-actions">
        <div className="paper-counts"><span className="count-ok">{counts.completed || 0} OK</span><span className="count-running">{counts.running || 0} 运行中</span><span className="count-failed">{counts.failed || 0} 失败</span></div>
        {retryablePapers.length > 0 && <button className="primary-button compact-button" onClick={() => setRetryConfirmation({ kind: "all", count: retryablePapers.length })}>重试全部外部故障（{retryablePapers.length}）</button>}
      </div>
    </div>
    <div className={`paper-monitor-body ${detail ? "has-detail" : ""}`}>
      <div className="paper-list" aria-label="论文运行状态">
        <div className="paper-list-head"><span>论文</span><span>结果</span><span>当前 / 失败环节</span><span>错误</span><span /></div>
        {diagnostics.map((paper) => <button
          className={`paper-row paper-${statusKind(paper.status)} ${detail?.diagnostic.paper_id === paper.paper_id ? "active" : ""}`}
          key={paper.paper_id}
          aria-label={`查看 ${paper.paper_id} 详情`}
          onClick={() => void openPaper(paper)}
        >
          <strong>{paper.paper_id}</strong>
          <span><StatusPill status={statusKind(paper.status)} /><small>{paperStatusLabel(paper.status)}</small></span>
          <span>{stageLabel(paper.stage)}</span>
          <span className="paper-error-summary">{paper.error_type && <b>{errorTypeLabel(paper.error_type)}</b>}{paper.error_message && <small>{paper.error_message}</small>}{!paper.error_type && <small>—</small>}</span>
          <span aria-hidden="true">›</span>
        </button>)}
      </div>
      {detail && <PaperDetailPanel detail={detail} loading={detailLoading} error={detailError} onClose={() => setDetail(null)} onRetry={(paperId) => setRetryConfirmation({ kind: "paper", paperId })} />}
    </div>
    <p className="paper-monitor-note">页面每 3 秒读取一次紧凑状态；不会加载或重建模型逐段回复。</p>
    {retryError && <p className="inline-error retry-error">{retryError}</p>}
    {retryConfirmation && <div className="modal-backdrop" role="presentation"><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="retry-title">
      <p className="eyebrow">外部故障修复</p>
      <h2 id="retry-title">{retryConfirmation.kind === "paper" ? `重试 ${retryConfirmation.paperId}？` : `重试 ${retryConfirmation.count} 篇论文？`}</h2>
      <p>旧失败尝试会先归档，然后发起真实 API 调用。只处理已识别为网络、限流或服务端故障的 transport_error；成功论文、HTTP 400 和工作流错误不会运行。</p>
      <div><button className="secondary-button" disabled={retryBusy} onClick={() => setRetryConfirmation(null)}>取消</button><button className="primary-button" disabled={retryBusy} onClick={() => void confirmRetry()}>{retryBusy ? "正在启动…" : retryConfirmation.kind === "paper" ? `确认重试 ${retryConfirmation.paperId}` : `确认重试 ${retryConfirmation.count} 篇`}</button></div>
    </section></div>}
  </section>;
}

export function RunPage() {
  const { groupId = "" } = useParams();
  const bootstrap = useBootstrap();
  const navigate = useNavigate();
  const { group, error, refresh } = useGroup(groupId);
  const [selectedRun, setSelectedRun] = useState("");
  const [summaries, setSummaries] = useState<Record<string, RunSummary>>({});
  const [actionError, setActionError] = useState("");
  const runKey = group?.experiments.map((item) => item.run_id).join("|") || "";
  const runIds = useMemo(() => group?.experiments.map((item) => item.run_id) || [], [runKey]);
  const loadSummary = useCallback((runId: string) => api.run(bootstrap.campaign_id, runId)
    .then((summary) => setSummaries((value) => ({ ...value, [runId]: summary })))
    .catch(() => undefined), [bootstrap.campaign_id]);

  useEffect(() => {
    if (!group) return;
    if (!selectedRun || !group.experiments.some((item) => item.run_id === selectedRun)) {
      setSelectedRun(group.experiments[0]?.run_id || "");
    }
  }, [group, selectedRun]);

  useEffect(() => {
    runIds.forEach((runId) => { void loadSummary(runId); });
    const timer = window.setInterval(() => runIds.forEach((runId) => { void loadSummary(runId); }), 3000);
    return () => window.clearInterval(timer);
  }, [runKey, loadSummary]);

  const experiment = group?.experiments.find((item) => item.run_id === selectedRun);
  const summary = summaries[selectedRun];
  const diagnostics = paperDiagnostics(summary, bootstrap.papers);
  const counts = diagnosticCounts(diagnostics);
  const hasReview = group?.experiments.some((item) => ["failed", "partial", "stopped"].includes(item.status));
  const active = group?.experiments.some((item) => ["running", "stop_requested", "queued", "resume_queued"].includes(item.status));
  const startedAt = group?.experiments.map((item) => item.started_at).filter(Boolean).sort()[0];
  const finishedAt = active ? undefined : group?.experiments.map((item) => item.finished_at).filter(Boolean).sort().at(-1);
  const elapsed = useClock(startedAt, finishedAt);
  const usage = Object.values(summaries).reduce((acc, value) => {
    for (const [key, number] of Object.entries(value.usage_totals || {})) acc[key] = (acc[key] || 0) + Number(number || 0);
    return acc;
  }, {} as Record<string, number>);

  async function groupAction(kind: "stop" | "resume") {
    setActionError("");
    try {
      kind === "stop" ? await api.stopGroup(groupId) : await api.resumeGroup(groupId);
      await refresh();
    } catch (reason) {
      setActionError((reason as Error).message);
    }
  }

  if (!group) return <div className="page"><div className="empty-state"><span className="spinner" /><p>{error || "正在载入实验组…"}</p></div></div>;
  return (
    <div className="page run-page">
      <PageIntro
        eyebrow={`实验组 · ${group.group_id}`}
        title="论文运行监控"
        description="按论文检查结果是否可用；失败时直接查看错误类型、失败环节和该论文的运行报告。"
        actions={<div className="run-actions">
          {active && !group.paused && <button className="danger-button" onClick={() => void groupAction("stop")}>停止整个实验组</button>}
          {group.paused && <button className="primary-button compact-button" onClick={() => void groupAction("resume")}>从断点恢复</button>}
          {hasReview && <button className="secondary-button" onClick={() => navigate(`/review/${groupId}`)}>进入运行复核</button>}
          {!active && !hasReview && <button className="primary-button compact-button" onClick={() => navigate(`/evaluate/${groupId}`)}>开始自动评估</button>}
        </div>}
      />
      {actionError && <p className="inline-error">{actionError}</p>}
      <section className="telemetry-strip">
        <div><small>实验组状态</small><StatusPill status={group.status} /></div>
        <div><small>已运行</small><strong>{elapsed}</strong></div>
        <div><small>输入 tokens</small><strong>{(usage.prompt_tokens || usage.input_tokens || 0).toLocaleString()}</strong></div>
        <div><small>输出 tokens</small><strong>{(usage.completion_tokens || usage.output_tokens || 0).toLocaleString()}</strong></div>
        <div><small>成功论文</small><strong>{counts.completed || 0}/{diagnostics.length}</strong></div>
        <div><small>失败论文</small><strong>{counts.failed || 0}</strong></div>
      </section>

      <div className="run-workspace paper-monitor-workspace">
        <aside className="experiment-rail">
          <div className="rail-head"><p className="eyebrow">实验</p><span>{group.max_parallel_experiments} 并发</span></div>
          {group.experiments.map((item, index) => <button
            className={selectedRun === item.run_id ? "active" : ""}
            onClick={() => setSelectedRun(item.run_id)}
            key={item.run_id}
          >
            <span className="experiment-index">{String(index + 1).padStart(2, "0")}</span>
            <span><strong>{item.request.experiment_name || item.run_id}</strong><small>{item.run_id} · Method {item.request.method}</small></span>
            <StatusPill status={item.status} />
          </button>)}
        </aside>

        <PaperMonitor key={selectedRun} campaignId={bootstrap.campaign_id} runId={selectedRun} summary={summary} fallbackPapers={bootstrap.papers} onRetryStarted={() => Promise.all([loadSummary(selectedRun), refresh()]).then(() => undefined)} />
      </div>
    </div>
  );
}
