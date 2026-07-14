import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useBootstrap } from "../App";
import { api } from "../api";
import { PageIntro } from "../components/PageIntro";
import { StatusPill } from "../components/StatusPill";
import { OverviewGraph, PaperGraph, type GraphSelection } from "../components/WorkflowGraph";
import { TraceDrawer } from "../components/TraceDrawer";
import { useGroup } from "../hooks/useGroup";
import { useRunTraceStreams, type ModelCallTranscript, type TraceConnectionState } from "../hooks/useRunTraceStreams";
import type { Method, RunSummary, TraceEvent } from "../types";

const EMPTY_EVENTS: TraceEvent[] = [];
const EMPTY_TRANSCRIPTS: ModelCallTranscript[] = [];
const EMPTY_PAPER_STATUSES: Record<string, string> = {};

function useClock(startedAt?: string, finishedAt?: string) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  if (!startedAt) return "00:00:00";
  const elapsed = Math.max(0, (finishedAt ? new Date(finishedAt).getTime() : now) - new Date(startedAt).getTime());
  const seconds = Math.floor(elapsed / 1000);
  return [Math.floor(seconds / 3600), Math.floor((seconds % 3600) / 60), seconds % 60].map((value) => String(value).padStart(2, "0")).join(":");
}

function traceConnectionMessage(runStatus: string, connection?: TraceConnectionState) {
  if (runStatus !== "running") return "当前展示已保存的运行状态";
  if (connection === "connected") return "SSE 已连接，图状态会随结构事件更新";
  if (connection === "reconnecting") return "SSE 正在重连，已显示的运行状态会保留";
  return "正在连接实时 trace…";
}

export function RunPage() {
  const { groupId = "" } = useParams();
  const bootstrap = useBootstrap();
  const navigate = useNavigate();
  const { group, error, refresh } = useGroup(groupId);
  const [selectedRun, setSelectedRun] = useState("");
  const [paperId, setPaperId] = useState<string | null>(null);
  const [selection, setSelection] = useState<GraphSelection | null>(null);
  const [summaries, setSummaries] = useState<Record<string, RunSummary>>({});
  const [actionError, setActionError] = useState("");
  const runKey = group?.experiments.map((item) => item.run_id).join("|") || "";
  const runIds = useMemo(() => group?.experiments.map((item) => item.run_id) || [], [runKey]);
  const loadSummary = useCallback((runId: string) => api.run(bootstrap.campaign_id, runId)
    .then((summary) => setSummaries((value) => ({ ...value, [runId]: summary })))
    .catch(() => undefined), [bootstrap.campaign_id]);
  const handlePaperCompleted = useCallback((runId: string) => { void loadSummary(runId); }, [loadSummary]);
  const { events, graphEvents, transcripts, usageTotals: liveUsage, connections } = useRunTraceStreams({
    campaignId: bootstrap.campaign_id,
    runIds,
    onPaperCompleted: handlePaperCompleted,
  });

  useEffect(() => {
    if (!group) return;
    if (!selectedRun || !group.experiments.some((item) => item.run_id === selectedRun)) setSelectedRun(group.experiments[0]?.run_id || "");
  }, [group, selectedRun]);

  useEffect(() => {
    runIds.forEach((runId) => { void loadSummary(runId); });
    const timer = window.setInterval(() => runIds.forEach((runId) => { void loadSummary(runId); }), 3000);
    return () => window.clearInterval(timer);
  }, [runKey, loadSummary]);

  const experiment = group?.experiments.find((item) => item.run_id === selectedRun);
  const summary = summaries[selectedRun];
  const runEvents = events[selectedRun] || EMPTY_EVENTS;
  const runTranscripts = transcripts[selectedRun] || EMPTY_TRANSCRIPTS;
  const graphRunEvents = graphEvents[selectedRun] || EMPTY_EVENTS;
  const paperGraphEvents = useMemo(
    () => paperId ? graphRunEvents.filter((event) => event.paper_id === paperId) : graphRunEvents,
    [graphRunEvents, paperId],
  );
  const hasReview = group?.experiments.some((item) => ["failed", "partial", "stopped"].includes(item.status));
  const active = group?.experiments.some((item) => ["running", "stop_requested", "queued", "resume_queued"].includes(item.status));
  const startedAt = group?.experiments.map((item) => item.started_at).filter(Boolean).sort()[0];
  const finishedAt = active ? undefined : group?.experiments.map((item) => item.finished_at).filter(Boolean).sort().at(-1);
  const elapsed = useClock(startedAt, finishedAt);
  const archivedUsage = Object.values(summaries).reduce((acc, value) => {
    for (const [key, number] of Object.entries(value.usage_totals || {})) acc[key] = (acc[key] || 0) + Number(number || 0);
    return acc;
  }, {} as Record<string, number>);
  const usage = Object.keys(liveUsage).length > 0 ? liveUsage : archivedUsage;
  const connection = connections[selectedRun];
  const connectionMessage = traceConnectionMessage(experiment?.status || "unknown", connection);

  const selectGraph = useCallback((value: GraphSelection) => {
    if (value.id.startsWith("paper:")) { setPaperId(value.id.slice(6)); setSelection(null); }
    else setSelection(value);
  }, []);
  async function groupAction(kind: "stop" | "resume") {
    setActionError("");
    try { kind === "stop" ? await api.stopGroup(groupId) : await api.resumeGroup(groupId); await refresh(); }
    catch (reason) { setActionError((reason as Error).message); }
  }

  if (!group) return <div className="page"><div className="empty-state"><span className="spinner" /><p>{error || "正在载入实验组…"}</p></div></div>;
  return (
    <div className="page run-page">
      <PageIntro eyebrow={`实验组 · ${group.group_id}`} title="运行全景" description="先看 10 篇论文如何被调度；点进一篇论文，再查看真实工作节点、循环、重试和信息交换。" actions={<div className="run-actions">{active && !group.paused && <button className="danger-button" onClick={() => void groupAction("stop")}>停止整个实验组</button>}{group.paused && <button className="primary-button compact-button" onClick={() => void groupAction("resume")}>从断点恢复</button>}{hasReview && <button className="secondary-button" onClick={() => navigate(`/review/${groupId}`)}>进入运行复核</button>}{!active && !hasReview && <button className="primary-button compact-button" onClick={() => navigate(`/evaluate/${groupId}`)}>开始自动评估</button>}</div>} />
      {actionError && <p className="inline-error">{actionError}</p>}
      <section className="telemetry-strip">
        <div><small>实验组状态</small><StatusPill status={group.status} /></div><div><small>已运行</small><strong>{elapsed}</strong></div><div><small>输入 tokens</small><strong>{(usage.prompt_tokens || usage.input_tokens || 0).toLocaleString()}</strong></div><div><small>输出 tokens</small><strong>{(usage.completion_tokens || usage.output_tokens || 0).toLocaleString()}</strong></div><div><small>Reasoning tokens</small><strong>{(usage.reasoning_tokens || 0).toLocaleString()}</strong></div><div><small>实验队列</small><strong>{group.experiments.filter((item) => item.status === "completed" || item.status === "sealed").length}/{group.experiments.length}</strong></div>
      </section>
      <div className="run-workspace">
        <aside className="experiment-rail"><div className="rail-head"><p className="eyebrow">实验</p><span>{group.max_parallel_experiments} 并发</span></div>{group.experiments.map((item, index) => <button className={selectedRun === item.run_id ? "active" : ""} onClick={() => { setSelectedRun(item.run_id); setPaperId(null); setSelection(null); }} key={item.run_id}><span className="experiment-index">{String(index + 1).padStart(2, "0")}</span><span><strong>{item.request.experiment_name || item.run_id}</strong><small>{item.run_id} · Method {item.request.method}</small></span><StatusPill status={item.status} /></button>)}</aside>
        <section className="graph-panel">
          <div className="graph-toolbar"><div>{paperId ? <><button className="back-link" onClick={() => { setPaperId(null); setSelection(null); }}>← 实验全景</button><strong>{paperId} · Method {experiment?.request.method}</strong></> : <><p className="eyebrow">实验全景</p><strong>{selectedRun}</strong></>}</div><div className="graph-legend"><span className="legend-running">进行中</span><span className="legend-completed">已完成</span><span className="legend-failed">失败</span></div></div>
          {paperId
            ? <PaperGraph method={(experiment?.request.method || "B") as Method} events={paperGraphEvents} onSelect={selectGraph} viewKey={`${selectedRun}:${paperId}`} />
            : <OverviewGraph papers={summary?.papers || bootstrap.papers} paperStatuses={summary?.paper_statuses || EMPTY_PAPER_STATUSES} runStatus={experiment?.status || "unknown"} events={graphRunEvents} onSelect={selectGraph} viewKey={selectedRun} />}
          <div className="graph-caption"><span className={`live-pulse connection-${connection || "connecting"}`} />{connectionMessage}<small>点节点查看工作详情 · 点连线查看信息交互</small></div>
        </section>
        {selection && <TraceDrawer campaignId={bootstrap.campaign_id} runId={selectedRun} selection={selection} paperId={paperId || undefined} events={runEvents} transcripts={runTranscripts} runStatus={experiment?.status} onClose={() => setSelection(null)} />}
      </div>
    </div>
  );
}
