import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { PageIntro } from "../components/PageIntro";
import { StatusPill } from "../components/StatusPill";
import type { ExperimentGroup, RunSummary } from "../types";

interface CampaignHistory {
  campaignId: string;
  groups: ExperimentGroup[];
  legacyRuns: RunSummary[];
}

function historyByCampaign(groups: ExperimentGroup[], runs: RunSummary[]): CampaignHistory[] {
  const groupedRunKeys = new Set(groups.flatMap((group) => group.experiments.map((item) => `${group.campaign_id}:${item.run_id}`)));
  const campaigns = new Map<string, CampaignHistory>();
  const getCampaign = (campaignId: string) => {
    const existing = campaigns.get(campaignId);
    if (existing) return existing;
    const next = { campaignId, groups: [], legacyRuns: [] };
    campaigns.set(campaignId, next);
    return next;
  };

  groups.forEach((group) => getCampaign(group.campaign_id).groups.push(group));
  runs.filter((run) => !groupedRunKeys.has(`${run.campaign_id}:${run.run_id}`)).forEach((run) => getCampaign(run.campaign_id).legacyRuns.push(run));
  return [...campaigns.values()];
}

export function HistoryPage() {
  const navigate = useNavigate();
  const [groups, setGroups] = useState<ExperimentGroup[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { Promise.all([api.groups(), api.runs()]).then(([groupValues, runValues]) => { setGroups(groupValues); setRuns(runValues); }).catch((reason: Error) => setError(reason.message)); }, []);
  const campaigns = useMemo(() => historyByCampaign(groups, runs), [groups, runs]);
  return <div className="page history-page"><PageIntro eyebrow="运行档案" title="按 Campaign 归档历史运行。" description="每个 Campaign 内保留实验组与未归组单 Run；历史记录仍可按原有入口打开详情。" actions={<button className="primary-button compact-button" onClick={() => navigate("/setup")}>＋ 新建实验组</button>} />
    {error && <p className="inline-error">{error}</p>}
    <section className="history-section"><div className="section-title"><div><p className="eyebrow">Campaign</p><h2>实验运行历史</h2></div><span>{campaigns.length} 个</span></div><div className="campaign-history-list">{campaigns.map((campaign) => <section className="campaign-history" aria-label={`Campaign ${campaign.campaignId}`} key={campaign.campaignId}><details className="campaign-history-disclosure"><summary className="campaign-history-head"><div><p className="eyebrow">Campaign</p><h2>{campaign.campaignId}</h2></div><div className="campaign-history-meta"><p>{campaign.groups.length} 个实验组 · {campaign.legacyRuns.length} 个未归组单 Run</p><span className="campaign-history-toggle" aria-hidden="true" /></div></summary>{campaign.groups.length > 0 && <div className="campaign-history-block"><div className="campaign-history-block-head"><div><p className="eyebrow">实验组</p><h3>引导式 Console 运行</h3></div><span>{campaign.groups.length} 组</span></div><div className="history-grid">{campaign.groups.map((group) => <button className="history-card" key={group.group_id} onClick={() => navigate(`/runs/${group.group_id}`)}><div><small>{new Date(group.created_at).toLocaleString()}</small><StatusPill status={group.status} /></div><h3>{group.group_id}</h3><p>{group.experiments.length} 个实验 · 最多 {group.max_parallel_experiments} 个并发</p><div className="history-runs">{group.experiments.map((experiment) => <span key={experiment.run_id}>{experiment.request.experiment_name || experiment.run_id}<StatusPill status={experiment.status} /></span>)}</div><strong className="open-arrow">打开运行全景 →</strong></button>)}</div></div>}{campaign.legacyRuns.length > 0 && <div className="campaign-history-block"><div className="campaign-history-block-head"><div><p className="eyebrow">单 Run</p><h3>未归组记录</h3></div><span>{campaign.legacyRuns.length} 个</span></div><div className="legacy-table">{campaign.legacyRuns.map((run) => <button className="legacy-run-row" aria-label={`打开 ${run.run_id} 论文监控`} onClick={() => navigate(`/runs/single/${encodeURIComponent(run.campaign_id)}/${encodeURIComponent(run.run_id)}`)} key={`${run.campaign_id}:${run.run_id}`}><span><strong>{run.run_id}</strong><small>{run.method === "unknown" ? "Legacy" : `Method ${run.method}`} · {run.extractor_model || "未知模型"} · {run.trace_precision === "exact" ? "精确记录" : "报告兼容视图"}</small></span><StatusPill status={run.status} /><span>{run.papers.length} 篇论文</span><span className="open-arrow">打开详情 →</span></button>)}</div></div>}</details></section>)}</div>{campaigns.length === 0 && <div className="empty-state compact"><p>还没有可查看的历史运行。</p></div>}</section>
  </div>;
}
