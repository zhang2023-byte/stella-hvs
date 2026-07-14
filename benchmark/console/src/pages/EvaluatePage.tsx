import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { PageIntro } from "../components/PageIntro";
import { StatusPill } from "../components/StatusPill";
import { useGroup } from "../hooks/useGroup";
import type { EvaluationState, Scorecard } from "../types";

function ratio(value: unknown) { return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—"; }
function ci(value: unknown) { return Array.isArray(value) && value.length === 2 ? `${ratio(value[0])}–${ratio(value[1])}` : "—"; }

export function ScorecardView({ card }: { card: Scorecard }) {
  const l1 = card.l1?.micro || {};
  const l2 = card.l2?.micro || {};
  const l1Boot = card.l1?.bootstrap || {};
  const l2Boot = card.l2?.bootstrap || {};
  const papers = card.l1?.per_paper || [];
  return <article className="scorecard"><div className="scorecard-title"><div><p className="eyebrow">本地 Dev Scorecard</p><h2>{card.run_label || "run"}</h2></div><span>{card.run_source?.model || card.run_source?.pipeline || "local"}</span></div><div className="metric-grid"><div className="metric-feature"><small>L1 F1</small><strong>{ratio(l1.f1)}</strong><em>95% CI {ci(l1Boot.micro_f1_ci95)}</em></div><div><small>L1 Precision</small><strong>{ratio(l1.precision)}</strong><em>95% CI {ci(l1Boot.micro_precision_ci95)}</em></div><div><small>L1 Recall</small><strong>{ratio(l1.recall)}</strong><em>95% CI {ci(l1Boot.micro_recall_ci95)}</em></div><div><small>Strict agreement</small><strong>{ratio(l2.agreement_over_compared_strict)}</strong><em>95% CI {ci(l2Boot.agreement_over_compared_strict_ci95)}</em></div><div><small>Delivery end-to-end</small><strong>{ratio(l2.delivery_end_to_end_strict)}</strong><em>95% CI {ci(l2Boot.delivery_end_to_end_strict_ci95)}</em></div><div><small>Fill precision</small><strong>{ratio(l2.fill_precision_strict)}</strong><em>95% CI {ci(l2Boot.fill_precision_strict_ci95)}</em></div><div><small>Coverage</small><strong>{ratio(l2.coverage)}</strong></div><div><small>AI-only quantities</small><strong>{l2.ai_only ?? "—"}</strong></div></div><div className="paper-metrics"><div className="paper-metrics-head"><strong>逐论文 L1</strong><span>TP / FP / FN</span></div>{papers.map((paper: Record<string, unknown>) => <div className="paper-metric-row" key={String(paper.arxiv_id)}><strong>{String(paper.arxiv_id)}</strong><div className="mini-bar"><span style={{ width: `${Math.max(3, Number(paper.f1 || 0) * 100)}%` }} /></div><span>{String(paper.tp ?? 0)} / {String(paper.fp ?? 0)} / {String(paper.fn ?? 0)}</span></div>)}</div><p className="scorecard-note">这里不生成合成总分；不同层级指标保留各自含义。逐项私有 details 不通过此 API 暴露。</p></article>;
}

export function EvaluatePage() {
  const { groupId = "" } = useParams();
  const navigate = useNavigate();
  const { group, error } = useGroup(groupId);
  const [selected, setSelected] = useState<string[]>([]);
  const [allowUnavailable, setAllowUnavailable] = useState(sessionStorage.getItem(`stella-allow-unavailable:${groupId}`) === "1");
  const [preflight, setPreflight] = useState<{ ok: boolean; checks: { name: string; ok: boolean; detail: string }[] } | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationState | null>(null);
  const [scorecards, setScorecards] = useState<Scorecard[]>([]);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  useEffect(() => { if (group && selected.length === 0) setSelected(group.experiments.map((item) => item.run_id)); }, [group]);
  useEffect(() => {
    let timer = 0;
    const load = async () => {
      try {
        const state = await api.evaluation(groupId); setEvaluation(state);
        if (state.status === "completed") setScorecards(await api.scorecards(groupId));
        if (["queued", "running"].includes(state.status)) timer = window.setTimeout(load, 1200);
      } catch (reason) { setActionError((reason as Error).message); }
    };
    void load(); return () => window.clearTimeout(timer);
  }, [groupId]);
  const hasUnavailable = useMemo(() => group?.experiments.some((item) => selected.includes(item.run_id) && !["completed", "sealed"].includes(item.status)) || false, [group, selected]);

  async function check() { setBusy(true); setActionError(""); try { setPreflight(await api.evaluationPreflight(groupId, selected, allowUnavailable)); } catch (reason) { setActionError((reason as Error).message); } finally { setBusy(false); } }
  async function start() { if (!preflight?.ok) return; setBusy(true); setActionError(""); try { setEvaluation(await api.startEvaluation(groupId, selected, allowUnavailable)); } catch (reason) { setActionError((reason as Error).message); } finally { setBusy(false); } }
  function toggle(runId: string) { setSelected((items) => items.includes(runId) ? items.filter((item) => item !== runId) : [...items, runId]); setPreflight(null); }

  if (!group) return <div className="page"><div className="empty-state"><span className="spinner" /><p>{error || "正在读取评估环境…"}</p></div></div>;
  const running = evaluation && ["queued", "running"].includes(evaluation.status);
  const evaluationRuns = Object.values(evaluation?.runs || {});
  const stageOrder = { audit: 0, seal: 1, score: 2, completed: 3 } as const;
  function stageClass(stage: "audit" | "seal" | "score") {
    if (!evaluation || evaluation.status === "not_started") return stage === "audit" ? "active" : "";
    if (evaluationRuns.some((run) => run.stage === stage && run.status === "failed")) return "failed";
    const index = stageOrder[stage];
    if (evaluationRuns.length > 0 && evaluationRuns.every((run) => stageOrder[run.stage] > index)) return "done";
    if (evaluationRuns.some((run) => run.stage === stage && ["queued", "running"].includes(run.status))) return "active";
    return "";
  }
  return <div className="page evaluate-page"><PageIntro eyebrow={`自动评估 · ${group.group_id}`} title="先审计，再封存，最后评分。" description="评估是显式操作，不会在 run 完成后自动触发。泄漏审计一旦发现污染会立即阻止评分；浏览器只接收清理后的文件名和计数，不接收 canary 或 gold 内容。" actions={<button className="secondary-button" onClick={() => navigate(`/runs/${groupId}`)}>返回运行图</button>} />
    <section className="evaluation-pipeline"><div className={stageClass("audit")}><span>1</span><strong>泄漏审计</strong><small>阻止 contaminated run</small></div><i>→</i><div className={stageClass("seal")}><span>2</span><strong>封存 Run</strong><small>冻结可评分交付</small></div><i>→</i><div className={stageClass("score")}><span>3</span><strong>本地 Dev 评分</strong><small>聚合指标 + 私有 details</small></div></section>
    {!evaluation || evaluation.status === "not_started" ? <div className="evaluation-setup"><section className="selection-panel"><div className="section-title"><div><p className="eyebrow">选择输入</p><h2>要评估哪些实验？</h2></div><span>{selected.length} 已选择</span></div>{group.experiments.map((experiment) => <label className="evaluation-run" key={experiment.run_id}><input type="checkbox" checked={selected.includes(experiment.run_id)} onChange={() => toggle(experiment.run_id)} /><span><strong>{experiment.run_id}</strong><small>Method {experiment.request.method} · {experiment.request.extractor_model}</small></span><StatusPill status={experiment.status} /></label>)}{hasUnavailable && <label className="check-control warning-check"><input type="checkbox" checked={allowUnavailable} onChange={(event) => { setAllowUnavailable(event.target.checked); setPreflight(null); }} /><span><strong>确认按 unavailable 处理缺失/无效交付</strong><small>只有运行复核后的明确确认才应勾选。</small></span></label>}</section><section className="evaluation-confirm"><p className="eyebrow">执行确认</p><h2>评估不会覆盖正式报告</h2><ul><li>聚合 scorecard 写入 ignored console evaluation 目录</li><li>逐项 details 只写到外部私有仓库的 dev-console 目录</li><li>不会覆盖现有私有 report/index.html</li></ul><button className="secondary-button" disabled={busy || selected.length === 0 || (hasUnavailable && !allowUnavailable)} onClick={() => void check()}>{busy ? "正在检查…" : "运行评估预检"}</button>{preflight && <div className={`check-results compact-checks ${preflight.ok ? "checks-ok" : "checks-failed"}`}>{preflight.checks.map((item) => <div className="check-row" key={item.name}><span>{item.ok ? "✓" : "!"}</span><strong>{item.name}</strong><small>{item.detail}</small></div>)}</div>}<button className="primary-button launch-button" disabled={!preflight?.ok || busy} onClick={() => void start()}>确认并开始评估 <span>→</span></button></section></div> : <section className={`evaluation-progress status-${evaluation.status}`}><div className="section-title"><div><p className="eyebrow">评估任务</p><h2>{evaluation.evaluation_id}</h2></div><StatusPill status={evaluation.status} /></div><div className="evaluation-run-progress">{Object.entries(evaluation.runs).map(([runId, state]) => <div key={runId}><span className={state.status === "completed" ? "progress-done" : state.status === "failed" ? "progress-failed" : "progress-active"} /><strong>{runId}</strong><em>{state.stage}</em><small>{state.error || (state.contaminated_files?.length ? `${state.contaminated_files.length} 个受污染文件` : state.status)}</small></div>)}</div>{running && <p className="live-message"><span className="spinner" />评估在本地后台执行，页面可安全刷新。</p>}{evaluation.status === "failed" && <p className="inline-error">{evaluation.error || "评估未完成，请检查上方阶段。"}</p>}</section>}
    {scorecards.length > 0 && <section className="scorecards-section"><div className="section-title"><div><p className="eyebrow">评估结果</p><h2>分层指标</h2></div><span>{scorecards.length} 个 scorecard</span></div>{scorecards.map((card) => <ScorecardView card={card} key={card.run_label || JSON.stringify(card.run_source)} />)}</section>}
    {actionError && <p className="inline-error">{actionError}</p>}
  </div>;
}
