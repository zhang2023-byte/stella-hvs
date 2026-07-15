import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageIntro } from "../components/PageIntro";
import { StatusPill } from "../components/StatusPill";
import { useGroup } from "../hooks/useGroup";

const exceptional = new Set(["failed", "partial", "stopped", "paused"]);

export function ReviewPage() {
  const { groupId = "" } = useParams();
  const navigate = useNavigate();
  const { group, error } = useGroup(groupId);
  const [allowUnavailable, setAllowUnavailable] = useState(false);

  if (!group) return <div className="page"><div className="empty-state"><span className="spinner" /><p>{error || "正在读取异常状态…"}</p></div></div>;
  const problems = group.experiments.filter((item) => exceptional.has(item.status));

  function continueToEvaluation() {
    sessionStorage.setItem(`stella-allow-unavailable:${groupId}`, allowUnavailable ? "1" : "0");
    navigate(`/evaluate/${groupId}`);
  }

  return (
    <div className="page review-page">
      <PageIntro eyebrow={`运行复核 · ${group.group_id}`} title={problems.length ? "先判断错误属于哪一类。" : "这个实验组无需异常复核。"} description="外部服务传输故障可回到论文监控中重试；校验、复核、运行器或工作流错误必须先修复工作流，再新建实验。成功论文和已封存 Run 均不可重跑。" actions={<button className="secondary-button" onClick={() => navigate(`/runs/${groupId}`)}>返回论文监控</button>} />
      {problems.length === 0 ? <section className="empty-state success-state"><span>✓</span><h2>全部实验已正常完成</h2><p>可以进入自动评估。评估前仍会执行泄漏审计和封存检查。</p><button className="primary-button compact-button" onClick={continueToEvaluation}>进入自动评估</button></section> : <>
        <section className="review-explainer"><div><span>1</span><strong>外部故障</strong><p>仅确认由网络、限流或服务端导致的 transport_error 可重试。</p></div><div><span>2</span><strong>工作流错误</strong><p>修复代码后新建实验，不修改旧 Run。</p></div><div><span>3</span><strong>按 unavailable 评估</strong><p>明确接受缺失交付后，才允许进入评分。</p></div></section>
        <div className="review-list">{group.experiments.map((experiment) => <article className={exceptional.has(experiment.status) ? "review-card problem" : "review-card"} key={experiment.run_id}><div><p className="eyebrow">Method {experiment.request.method}</p><h2>{experiment.run_id}</h2><p>{experiment.error || (exceptional.has(experiment.status) ? "请在论文监控中查看逐篇错误；只有外部传输故障有重试入口。" : "该实验已有可用交付。")}</p></div><StatusPill status={experiment.status} /><dl><div><dt>提取模型</dt><dd>{experiment.request.extractor_model}</dd></div><div><dt>复核模型</dt><dd>{experiment.request.reviewer_model}</dd></div><div><dt>任务范围</dt><dd>{experiment.request.task_surface}</dd></div></dl></article>)}</div>
        <section className="unavailable-choice"><label className="check-control"><input type="checkbox" checked={allowUnavailable} onChange={(event) => setAllowUnavailable(event.target.checked)} /><span><strong>我确认：未成功实验可按 unavailable 进入评估</strong><small>评分会保留缺失/无效交付，不会把它当作成功结果。这个选择只作用于当前实验组。</small></span></label><button className="primary-button compact-button" disabled={!allowUnavailable} onClick={continueToEvaluation}>确认并进入评估</button></section>
      </>}
    </div>
  );
}
