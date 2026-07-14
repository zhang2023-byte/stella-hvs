import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { PageIntro } from "../components/PageIntro";
import { StatusPill } from "../components/StatusPill";
import { useGroup } from "../hooks/useGroup";

const exceptional = new Set(["failed", "partial", "stopped", "paused"]);

export function ReviewPage() {
  const { groupId = "" } = useParams();
  const navigate = useNavigate();
  const { group, error, refresh } = useGroup(groupId);
  const [resetting, setResetting] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  const [allowUnavailable, setAllowUnavailable] = useState(false);
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!group) return <div className="page"><div className="empty-state"><span className="spinner" /><p>{error || "正在读取异常状态…"}</p></div></div>;
  const problems = group.experiments.filter((item) => exceptional.has(item.status));

  async function resume() {
    setBusy(true); setActionError("");
    try { await api.resumeGroup(groupId); await refresh(); navigate(`/runs/${groupId}`); }
    catch (reason) { setActionError((reason as Error).message); setBusy(false); }
  }
  async function reset() {
    if (!resetting || confirm !== resetting) return;
    setBusy(true); setActionError("");
    try { await api.resetRun(resetting); await refresh(); setResetting(null); setConfirm(""); }
    catch (reason) { setActionError((reason as Error).message); }
    finally { setBusy(false); }
  }
  function continueToEvaluation() {
    sessionStorage.setItem(`stella-allow-unavailable:${groupId}`, allowUnavailable ? "1" : "0");
    navigate(`/evaluate/${groupId}`);
  }

  return (
    <div className="page review-page">
      <PageIntro eyebrow={`运行复核 · ${group.group_id}`} title={problems.length ? "先处理未正常交付的实验。" : "这个实验组无需异常复核。"} description="恢复采用论文级断点：成功论文会跳过；失败或中断论文的旧尝试先归档，再从该篇论文开头重跑。清零则删除该 run 的本地结果，但保留实验配置。" actions={<button className="secondary-button" onClick={() => navigate(`/runs/${groupId}`)}>返回运行图</button>} />
      {problems.length === 0 ? <section className="empty-state success-state"><span>✓</span><h2>全部实验已正常完成</h2><p>可以进入自动评估。评估前仍会执行泄漏审计和封存检查。</p><button className="primary-button compact-button" onClick={continueToEvaluation}>进入自动评估</button></section> : <>
        <section className="review-explainer"><div><span>1</span><strong>恢复</strong><p>保留成功论文，只重跑失败或中断论文。</p></div><div><span>2</span><strong>清零重跑</strong><p>未封存且无活动进程时，删除指定 run/trace。</p></div><div><span>3</span><strong>按 unavailable 评估</strong><p>明确接受缺失交付后，才允许进入评分。</p></div></section>
        <div className="review-list">{group.experiments.map((experiment) => <article className={exceptional.has(experiment.status) ? "review-card problem" : "review-card"} key={experiment.run_id}><div><p className="eyebrow">Method {experiment.request.method}</p><h2>{experiment.run_id}</h2><p>{experiment.error || (exceptional.has(experiment.status) ? "该实验没有形成完整可用的交付。" : "该实验已有可用交付。")}</p></div><StatusPill status={experiment.status} /><dl><div><dt>提取模型</dt><dd>{experiment.request.extractor_model}</dd></div><div><dt>复核模型</dt><dd>{experiment.request.reviewer_model}</dd></div><div><dt>任务范围</dt><dd>{experiment.request.task_surface}</dd></div></dl>{exceptional.has(experiment.status) && <div className="review-card-actions"><button className="secondary-button" disabled={busy} onClick={() => void resume()}>从断点恢复</button><button className="danger-button" disabled={busy || ["running", "stop_requested"].includes(experiment.status)} onClick={() => { setResetting(experiment.run_id); setConfirm(""); }}>清零这个 Run</button></div>}</article>)}</div>
        <section className="unavailable-choice"><label className="check-control"><input type="checkbox" checked={allowUnavailable} onChange={(event) => setAllowUnavailable(event.target.checked)} /><span><strong>我确认：未成功实验可按 unavailable 进入评估</strong><small>评分会保留缺失/无效交付，不会把它当作成功结果。这个选择只作用于当前实验组。</small></span></label><button className="primary-button compact-button" disabled={!allowUnavailable || busy} onClick={continueToEvaluation}>确认并进入评估</button></section>
      </>}
      {actionError && <p className="inline-error">{actionError}</p>}
      {resetting && <div className="modal-backdrop" role="presentation"><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="reset-title"><p className="eyebrow">危险操作</p><h2 id="reset-title">清零 {resetting}？</h2><p>只会删除该 run 的声明结果目录和 trace 目录。封存结果或仍在运行的进程不会被删除。</p><label><span>输入完整 Run ID 确认</span><input autoFocus value={confirm} onChange={(event) => setConfirm(event.target.value)} placeholder={resetting} /></label><div><button className="secondary-button" onClick={() => setResetting(null)}>取消</button><button className="danger-button" disabled={confirm !== resetting || busy} onClick={() => void reset()}>{busy ? "正在清零…" : "确认清零"}</button></div></section></div>}
    </div>
  );
}
