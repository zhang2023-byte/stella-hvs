import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { PageIntro } from "../components/PageIntro";
import { StatusPill } from "../components/StatusPill";
import type { ExperimentGroup, RunSummary } from "../types";

export function HistoryPage() {
  const navigate = useNavigate();
  const [groups, setGroups] = useState<ExperimentGroup[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { Promise.all([api.groups(), api.runs()]).then(([groupValues, runValues]) => { setGroups(groupValues); setRuns(runValues); }).catch((reason: Error) => setError(reason.message)); }, []);
  const groupedRuns = useMemo(() => new Set(groups.flatMap((group) => group.experiments.map((item) => item.run_id))), [groups]);
  const legacy = runs.filter((run) => !groupedRuns.has(run.run_id));
  return <div className="page history-page"><PageIntro eyebrow="运行档案" title="按实验组回看，也兼容旧单 Run。" description="新控制台创建的实验按组展示；迁移前的 run 保持只读，不会因为没有实验组元数据而丢失。" actions={<button className="primary-button compact-button" onClick={() => navigate("/setup")}>＋ 新建实验组</button>} />
    {error && <p className="inline-error">{error}</p>}
    <section className="history-section"><div className="section-title"><div><p className="eyebrow">实验组</p><h2>引导式 Console 运行</h2></div><span>{groups.length} 组</span></div><div className="history-grid">{groups.map((group) => <button className="history-card" key={group.group_id} onClick={() => navigate(`/runs/${group.group_id}`)}><div><small>{new Date(group.created_at).toLocaleString()}</small><StatusPill status={group.status} /></div><h3>{group.group_id}</h3><p>{group.experiments.length} 个实验 · 最多 {group.max_parallel_experiments} 个并发</p><div className="history-runs">{group.experiments.map((experiment) => <span key={experiment.run_id}>{experiment.request.experiment_name || experiment.run_id}<StatusPill status={experiment.status} /></span>)}</div><strong className="open-arrow">打开运行全景 →</strong></button>)}</div>{groups.length === 0 && <div className="empty-state compact"><p>还没有实验组。</p></div>}</section>
    <section className="history-section legacy-section"><div className="section-title"><div><p className="eyebrow">旧记录</p><h2>兼容的单 Run</h2></div><span>{legacy.length} 个</span></div><div className="legacy-table">{legacy.map((run) => <div key={`${run.campaign_id}:${run.run_id}`}><span><strong>{run.run_id}</strong><small>{run.method === "unknown" ? "Legacy" : `Method ${run.method}`} · {run.extractor_model || "未知模型"}</small></span><StatusPill status={run.status} /><span>{run.papers.length} 篇论文</span><span>{run.trace_precision === "exact" ? "精确 trace" : "兼容视图"}</span></div>)}</div>{legacy.length === 0 && <div className="empty-state compact"><p>没有未归组的旧记录。</p></div>}</section>
  </div>;
}
