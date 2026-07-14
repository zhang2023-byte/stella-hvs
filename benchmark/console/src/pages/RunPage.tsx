import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useBootstrap } from "../App";
import { api } from "../api";
import { PageIntro } from "../components/PageIntro";
import { StatusPill } from "../components/StatusPill";
import { OverviewGraph, PaperGraph, type GraphSelection } from "../components/WorkflowGraph";
import { TraceDrawer } from "../components/TraceDrawer";
import { useGroup } from "../hooks/useGroup";
import type { GroupExperiment, Method, RunSummary, TraceEvent } from "../types";

function useClock(startedAt?: string, finishedAt?: string) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  if (!startedAt) return "00:00:00";
  const elapsed = Math.max(0, (finishedAt ? new Date(finishedAt).getTime() : now) - new Date(startedAt).getTime());
  const seconds = Math.floor(elapsed / 1000);
  return [Math.floor(seconds / 3600), Math.floor((seconds % 3600) / 60), seconds % 60].map((value) => String(value).padStart(2, "0")).join(":");
}

function retainTraceEvents(items: TraceEvent[], event: TraceEvent) {
  const merged = [...items.filter((item) => item.seq !== event.seq), event];
  const structural = merged.filter((item) => item.type !== "llm.response.delta").slice(-1200);
  const deltas = merged.filter((item) => item.type === "llm.response.delta").slice(-2400);
  return [...structural, ...deltas].sort((left, right) => left.seq - right.seq);
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
  const [events, setEvents] = useState<Record<string, TraceEvent[]>>({});
  const [usageEvents, setUsageEvents] = useState<Record<string, Record<number, Record<string, number>>>>({});
  const [actionError, setActionError] = useState("");

  useEffect(() => {
    if (!group) return;
    if (!selectedRun || !group.experiments.some((item) => item.run_id === selectedRun)) setSelectedRun(group.experiments[0]?.run_id || "");
    const sources = group.experiments.map((experiment) => {
      const runId = experiment.run_id;
      const load = () => api.run(bootstrap.campaign_id, runId).then((summary) => setSummaries((value) => ({ ...value, [runId]: summary }))).catch(() => undefined);
      void load();
      const source = new EventSource(`/api/runs/${encodeURIComponent(bootstrap.campaign_id)}/${encodeURIComponent(runId)}/events`);
      source.addEventListener("trace", (message) => {
        const event = JSON.parse((message as MessageEvent).data) as TraceEvent;
        setEvents((value) => ({ ...value, [runId]: retainTraceEvents(value[runId] || [], event) }));
        if (event.usage_delta && Object.keys(event.usage_delta).length > 0) setUsageEvents((value) => ({ ...value, [runId]: { ...(value[runId] || {}), [event.seq]: event.usage_delta as Record<string, number> } }));
        if (event.type === "paper.completed") void load();
      });
      return source;
    });
    const timer = window.setInterval(() => group.experiments.forEach((item) => api.run(bootstrap.campaign_id, item.run_id).then((summary) => setSummaries((value) => ({ ...value, [item.run_id]: summary }))).catch(() => undefined)), 3000);
    return () => { sources.forEach((source) => source.close()); window.clearInterval(timer); };
  }, [bootstrap.campaign_id, group?.experiments.map((item) => item.run_id).join("|")]);

  const experiment = group?.experiments.find((item) => item.run_id === selectedRun);
  const summary = summaries[selectedRun];
  const runEvents = events[selectedRun] || [];
  const paperEvents = paperId ? runEvents.filter((event) => event.paper_id === paperId) : runEvents;
  const hasReview = group?.experiments.some((item) => ["failed", "partial", "stopped"].includes(item.status));
  const active = group?.experiments.some((item) => ["running", "stop_requested", "queued", "resume_queued"].includes(item.status));
  const startedAt = group?.experiments.map((item) => item.started_at).filter(Boolean).sort()[0];
  const finishedAt = active ? undefined : group?.experiments.map((item) => item.finished_at).filter(Boolean).sort().at(-1);
  const elapsed = useClock(startedAt, finishedAt);
  const archivedUsage = Object.values(summaries).reduce((acc, value) => {
    for (const [key, number] of Object.entries(value.usage_totals || {})) acc[key] = (acc[key] || 0) + Number(number || 0);
    return acc;
  }, {} as Record<string, number>);
  const liveUsage = Object.values(usageEvents).flatMap((items) => Object.values(items)).reduce((acc, delta) => {
    for (const [key, number] of Object.entries(delta)) acc[key] = (acc[key] || 0) + Number(number || 0);
    return acc;
  }, {} as Record<string, number>);
  const usage = Object.keys(liveUsage).length > 0 ? liveUsage : archivedUsage;

  function selectGraph(value: GraphSelection) {
    if (value.id.startsWith("paper:")) { setPaperId(value.id.slice(6)); setSelection(null); }
    else setSelection(value);
  }
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
            ? <PaperGraph method={(experiment?.request.method || "B") as Method} events={paperEvents} onSelect={selectGraph} />
            : <OverviewGraph papers={summary?.papers || bootstrap.papers} paperStatuses={summary?.paper_statuses || {}} runStatus={experiment?.status || "unknown"} events={runEvents} onSelect={selectGraph} />}
          <div className="graph-caption"><span className="live-pulse" />{experiment?.status === "running" ? "SSE 已连接，图状态会随 trace 事件更新" : "当前展示已保存的运行状态"}<small>点节点查看工作详情 · 点连线查看信息交互</small></div>
        </section>
        {selection && <TraceDrawer campaignId={bootstrap.campaign_id} runId={selectedRun} selection={selection} paperId={paperId || undefined} events={runEvents} onClose={() => setSelection(null)} />}
      </div>
    </div>
  );
}
