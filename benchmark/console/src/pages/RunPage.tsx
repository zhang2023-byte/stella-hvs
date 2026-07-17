import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useBootstrap } from "../App";
import { api } from "../api";
import { PageIntro } from "../components/PageIntro";
import { PaperWorkflow } from "../components/PaperWorkflow";
import { StatusPill } from "../components/StatusPill";
import { useGroup } from "../hooks/useGroup";
import type { DeliverySummary, PaperDetail, PaperDiagnostic, RunSummary, ValidatorGroup } from "../types";

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
    roster_failed: "Roster 失败",
    scaffold_failed: "框架失败",
    plan_failed: "规划失败",
    candidate_failed: "候选提取失败",
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
  if (stage === "roster") return "共享候选 Roster";
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
    warning_details_available: false,
    historical_warning_count_only: false,
    validator_groups: [],
    report_available: status !== "missing",
    retry_eligible: false,
    retry_reason: "尚无可重试的外部服务失败报告",
  };
}

function tokenTotal(usage: Record<string, number> | undefined) {
  if (!usage) return 0;
  return usage.total_tokens
    || (usage.prompt_tokens || usage.input_tokens || 0)
    + (usage.completion_tokens || usage.output_tokens || 0);
}

function ValidatorGroups({ groups }: { groups: ValidatorGroup[] }) {
  if (!groups.length) return null;
  return <section className="paper-detail-section validator-groups">
    <h3>按根因聚合 · {groups.length} 组</h3>
    {groups.map((group, index) => <details key={`${group.severity}:${group.root_key}:${index}`}>
      <summary><span className={`root-severity root-${group.severity}`}>{group.severity === "error" ? "错误" : "警告"}</span><strong>{group.root_key}</strong><small>{group.count} 项</small></summary>
      {group.rule_ids.length > 0 && <p>规则：{group.rule_ids.join(", ")}</p>}
      {group.messages.length > 0 && <ul>{group.messages.map((message) => <li key={message}>{message}</li>)}</ul>}
      {group.paths.length > 0 && <small className="root-paths">位置：{group.paths.join(", ")}</small>}
    </details>)}
  </section>;
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

function groupedStageLog(entries: Record<string, unknown>[]) {
  const groups: { key: string; label: string; summary: string; count: number }[] = [];
  for (const entry of entries) {
    const rawStage = typeof entry.round === "number" ? "validation" : String(entry.stage || entry.unit || "运行记录");
    const key = stageLabel(rawStage.replace(/-\d+$/, ""));
    const previous = groups.at(-1);
    if (previous?.key === key) {
      previous.count += 1;
      previous.summary = stageEntrySummary(entry);
    } else {
      groups.push({ key, label: stageEntryLabel(entry), summary: stageEntrySummary(entry), count: 1 });
    }
  }
  return groups;
}

function PaperDetailPanel({ detail, method, loading, error, onClose, onRetry }: {
  detail: PaperDetail | null;
  method: RunSummary["method"];
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
  const validatorGroups = Array.isArray(report?.validator_groups)
    ? report.validator_groups
    : diagnostic?.validator_groups || [];
  const transportError = report?.transport_error || diagnostic?.transport_error;
  const groupedStages = groupedStageLog(stageLog);

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

        <PaperWorkflow method={method} diagnostic={diagnostic} events={detail?.events || []} />

        {groupedStages.length > 0 && <section className="paper-detail-section">
          <h3>报告阶段摘要</h3>
          <ol className="stage-timeline">
            {groupedStages.map((entry, index) => <li key={`${entry.key}:${index}`}>
              <span aria-hidden="true" />
              <div><strong>{entry.label}{entry.count > 1 ? ` × ${entry.count}` : ""}</strong><small>{entry.summary}</small></div>
            </li>)}
          </ol>
        </section>}

        <ValidatorGroups groups={validatorGroups} />

        {validatorErrors.length > 0 && <section className="paper-detail-section error-list">
          <h3>校验错误 · {validatorErrors.length}</h3>
          <ul>{validatorErrors.map((item, index) => <li key={index}>{String(item)}</li>)}</ul>
        </section>}

        {warnings.length > 0 && <section className="paper-detail-section warning-list">
          <h3>警告 · {warnings.length}</h3>
          <ul>{warnings.map((item, index) => <li key={index}>{String(item)}</li>)}</ul>
        </section>}

        {diagnostic.historical_warning_count_only && <section className="paper-detail-section warning-list historical-warning">
          <h3>历史警告 · {diagnostic.warning_count}</h3>
          <p>旧报告只保存了警告数量，没有可展开的详细列表；这里不会用当前 validator 改写历史结论。</p>
        </section>}

        {transportError && <section className="paper-detail-section transport-detail">
          <h3>Transport 错误证据</h3>
          <dl>
            <div><dt>分类</dt><dd>{transportError.category || "transport"}</dd></div>
            <div><dt>HTTP</dt><dd>{transportError.http_status ?? "—"}</dd></div>
            <div><dt>阶段 / Call</dt><dd>{transportError.stage || "—"} / {transportError.call_id || "—"}</dd></div>
            <div><dt>人工重试</dt><dd>{transportError.manual_retry_eligible ? "允许" : "不允许"}</dd></div>
            {transportError.provider_request_id && <div><dt>Request ID</dt><dd>{transportError.provider_request_id}</dd></div>}
          </dl>
          {transportError.response_body_excerpt && <pre>{transportError.response_body_excerpt}</pre>}
        </section>}

        {report?.roster_bundle_id && <section className="paper-detail-section roster-detail">
          <h3>共享候选 Roster</h3>
          <p><code>{report.roster_bundle_id}</code></p>
          <small>{report.roster_cache_hit ? "本 Run 复用了已有 bundle" : "本 Run 生成了该 bundle"} · shared {tokenTotal(report.shared_roster_usage).toLocaleString()} tokens · downstream {tokenTotal(report.downstream_usage).toLocaleString()} tokens</small>
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

function deliveryStatusLabel(status: string) {
  const labels: Record<string, string> = {
    complete: "完整",
    partial: "部分",
    unavailable: "不可用",
    not_requested: "未请求",
  };
  return labels[status] || status || "未知";
}

function DeliveryFigure({ label, delivery }: { label: string; delivery: DeliverySummary | null | undefined }) {
  if (!delivery) return null;
  const total = delivery.valid + delivery.invalid + delivery.missing;
  if (delivery.status === "not_requested") {
    return <div><small>{label}</small><strong>未请求</strong></div>;
  }
  return <div><small>{label}</small><strong>{delivery.valid}/{total} 有效</strong><small>{deliveryStatusLabel(delivery.status)} · 无效 {delivery.invalid} · 缺失 {delivery.missing}</small></div>;
}

function DeliveryStrip({ summary }: { summary: RunSummary | undefined }) {
  const deliveries = summary?.deliveries;
  if (!deliveries?.core) return null;
  // CORE 是正式评分产品，富化是单独校验的诊断产品：两者并列展示，绝不合并成一个成功率。
  return <section className="delivery-strip" aria-label="封存交付">
    <DeliveryFigure label="CORE 交付（正式产品）" delivery={deliveries.core} />
    <DeliveryFigure label="富化交付（诊断）" delivery={deliveries.enrichment} />
  </section>;
}

function failureClusters(diagnostics: PaperDiagnostic[]) {
  const clusters = new Map<string, { errorType: string; stage: string; count: number; papers: Set<string> }>();
  diagnostics.forEach((diagnostic) => {
    if (statusKind(diagnostic.status) !== "failed") return;
    const errorType = diagnostic.error_type || diagnostic.status || "failed";
    const stage = diagnostic.stage || "final";
    const key = `${errorType}:${stage.replace(/-\d+$/, "-candidate")}`;
    const cluster = clusters.get(key) || { errorType, stage, count: 0, papers: new Set<string>() };
    cluster.count += 1;
    cluster.papers.add(diagnostic.paper_id);
    clusters.set(key, cluster);
  });
  return [...clusters.values()].sort((left, right) => right.count - left.count || left.errorType.localeCompare(right.errorType));
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
  const selectedPaperId = detail?.diagnostic.paper_id || "";

  const refreshPaper = useCallback(async (paperId: string, showLoading = false) => {
    if (showLoading) setDetailLoading(true);
    try {
      setDetail(await api.paperDetail(campaignId, runId, paperId));
      setDetailError("");
    } catch (reason) {
      setDetailError((reason as Error).message);
    } finally {
      if (showLoading) setDetailLoading(false);
    }
  }, [campaignId, runId]);

  useEffect(() => {
    if (!selectedPaperId) return;
    const timer = window.setInterval(() => void refreshPaper(selectedPaperId), 3000);
    return () => window.clearInterval(timer);
  }, [refreshPaper, selectedPaperId]);

  async function openPaper(paper: PaperDiagnostic) {
    setDetail({ diagnostic: paper, report: null, events: [] });
    setDetailError("");
    await refreshPaper(paper.paper_id, true);
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
    <DeliveryStrip summary={summary} />
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
          <span><StatusPill status={statusKind(paper.status)} /><small>{paperStatusLabel(paper.status)}</small>{paper.warning_count > 0 && <em className="warning-badge">{paper.warning_count} 警告</em>}</span>
          <span>{stageLabel(paper.stage)}</span>
          <span className="paper-error-summary">{paper.error_type && <b>{errorTypeLabel(paper.error_type)}</b>}{paper.error_message && <small>{paper.error_message}</small>}{!paper.error_type && <small>—</small>}</span>
          <span aria-hidden="true">›</span>
        </button>)}
      </div>
      {detail && <PaperDetailPanel detail={detail} method={summary?.method || "unknown"} loading={detailLoading} error={detailError} onClose={() => setDetail(null)} onRetry={(paperId) => setRetryConfirmation({ kind: "paper", paperId })} />}
    </div>
    <p className="paper-monitor-note">页面每 3 秒读取一次紧凑状态，并同步已打开论文的结构事件；节点与连续步骤会实时更新，不加载或重建模型逐段回复。</p>
    {retryError && <p className="inline-error retry-error">{retryError}</p>}
    {retryConfirmation && <div className="modal-backdrop" role="presentation"><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="retry-title">
      <p className="eyebrow">外部故障修复</p>
      <h2 id="retry-title">{retryConfirmation.kind === "paper" ? `重试 ${retryConfirmation.paperId}？` : `重试 ${retryConfirmation.count} 篇论文？`}</h2>
      <p>旧失败尝试会先归档，然后发起真实 API 调用。只处理网络、超时、限流、服务端故障、已修复凭据的 401/403，或结构化确认的 provider 解析故障；成功论文、普通 HTTP 400、context limit 和工作流错误不会运行。</p>
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
  const groupScope = group?.scope || group?.experiments[0]?.request.scope || "formal_dev";
  const groupPapers = group?.paper_ids?.length ? group.paper_ids : bootstrap.papers;
  const diagnostics = paperDiagnostics(summary, groupPapers);
  const groupDiagnostics = (group?.experiments || []).flatMap((item) =>
    paperDiagnostics(summaries[item.run_id], groupPapers),
  );
  const groupCounts = diagnosticCounts(groupDiagnostics);
  const clusters = failureClusters(groupDiagnostics);
  const hasReview = group?.experiments.some((item) => ["failed", "partial", "stopped"].includes(item.status));
  const active = group?.experiments.some((item) => ["running", "stop_requested", "queued", "resume_queued"].includes(item.status));
  const startedAt = group?.experiments.map((item) => item.started_at).filter(Boolean).sort()[0];
  const finishedAt = active ? undefined : group?.experiments.map((item) => item.finished_at).filter(Boolean).sort().at(-1);
  const elapsed = useClock(startedAt, finishedAt);
  const usage = Object.values(summaries).reduce((acc, value) => {
    for (const [key, number] of Object.entries(value.usage_totals || {})) acc[key] = (acc[key] || 0) + Number(number || 0);
    return acc;
  }, {} as Record<string, number>);
  const downstreamUsage = Object.values(summaries).reduce((acc, value) => {
    for (const [key, number] of Object.entries(value.downstream_usage_totals || {})) acc[key] = (acc[key] || 0) + Number(number || 0);
    return acc;
  }, {} as Record<string, number>);
  const sharedRosterBundles = new Map<string, Record<string, number>>();
  Object.values(summaries).forEach((value) => value.shared_roster_bundles?.forEach((bundle) => {
    if (!sharedRosterBundles.has(bundle.bundle_id)) sharedRosterBundles.set(bundle.bundle_id, bundle.usage_totals || {});
  }));
  const sharedRosterUsage = [...sharedRosterBundles.values()].reduce((acc, value) => {
    for (const [key, number] of Object.entries(value)) acc[key] = (acc[key] || 0) + Number(number || 0);
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
        eyebrow={`${groupScope === "regression" ? "定向回归" : "正式 Dev"} · ${group.group_id}`}
        title="论文运行监控"
        description="上方按“配置 × 论文 attempt”统计真实交付率；Run 状态表示该实验是否含失败，不再把部分失败误解为全部论文失败。"
        actions={<div className="run-actions">
          {active && !group.paused && <button className="danger-button" onClick={() => void groupAction("stop")}>停止整个实验组</button>}
          {group.paused && groupScope === "formal_dev" && <button className="primary-button compact-button" onClick={() => void groupAction("resume")}>从断点恢复</button>}
          {hasReview && <button className="secondary-button" onClick={() => navigate(`/review/${groupId}`)}>进入运行复核</button>}
          {!active && !hasReview && groupScope === "formal_dev" && <button className="primary-button compact-button" onClick={() => navigate(`/evaluate/${groupId}`)}>开始自动评估</button>}
        </div>}
      />
      {actionError && <p className="inline-error">{actionError}</p>}
      <section className="telemetry-strip">
        <div><small>实验组状态</small><StatusPill status={group.status} /></div>
        <div><small>已运行</small><strong>{elapsed}</strong></div>
        <div><small>实际 tokens</small><strong>{tokenTotal(usage).toLocaleString()}</strong></div>
        <div><small>共享 Roster</small><strong>{tokenTotal(sharedRosterUsage).toLocaleString()}</strong></div>
        <div><small>下游 tokens</small><strong>{tokenTotal(downstreamUsage).toLocaleString()}</strong></div>
        <div><small>成功尝试</small><strong>{groupCounts.completed || 0}/{groupDiagnostics.length}</strong></div>
        <div><small>失败尝试</small><strong>{groupCounts.failed || 0}</strong></div>
      </section>

      {clusters.length > 0 && <section className="group-failure-overview" aria-label="实验组失败根因">
        <div className="group-failure-heading">
          <div><p className="eyebrow">实验组诊断</p><h2>失败根因 · {clusters.length} 类</h2></div>
          <p>共 {groupCounts.failed || 0} 个失败 attempt；选择左侧实验，再点论文即可查看完整报告与节点轨迹。</p>
        </div>
        <div className="group-failure-clusters">
          {clusters.map((cluster) => <article key={`${cluster.errorType}:${cluster.stage}`}>
            <span>{errorTypeLabel(cluster.errorType)}</span>
            <strong>{cluster.count} 次</strong>
            <small>{stageLabel(cluster.stage)} · {[...cluster.papers].join("、")}</small>
          </article>)}
        </div>
      </section>}

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

        <PaperMonitor key={selectedRun} campaignId={bootstrap.campaign_id} runId={selectedRun} summary={summary} fallbackPapers={groupPapers} onRetryStarted={() => Promise.all([loadSummary(selectedRun), refresh()]).then(() => undefined)} />
      </div>
    </div>
  );
}
