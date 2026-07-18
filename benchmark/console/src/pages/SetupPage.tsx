import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { PageIntro } from "../components/PageIntro";
import { useBootstrap } from "../App";
import type { GroupPreflight, GroupRequest, RunRequest } from "../types";

type Draft = RunRequest & { key: string; selected: boolean };

const preferredRegressionPapers = ["1804.10179", "1902.05061", "2401.02017"];

function compactTimestamp() {
  return new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 12).toLowerCase();
}

function slug(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 54);
}

function csvValues(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function SetupStep({ number, title, children }: { number: string; title: string; children: React.ReactNode }) {
  return (
    <section className="setup-step">
      <div className="step-heading"><span>{number}</span><h2>{title}</h2></div>
      {children}
    </section>
  );
}

export function SetupPage() {
  const bootstrap = useBootstrap();
  const navigate = useNavigate();
  const newDraft = (index = 1): Draft => {
    const stamp = compactTimestamp();
    const model = bootstrap.models[0] || "deepseek-v4-pro";
    return {
      key: crypto.randomUUID(), selected: true, experiment_name: `实验 ${index}`,
      method: "B", run_id: `dev-b-${stamp}-${index}`,
      extractor_model: model, reviewer_model: bootstrap.defaults.reviewer_model,
      task_surface: bootstrap.defaults.task_surface, parallel: bootstrap.defaults.parallel,
      max_repair_rounds: bootstrap.defaults.max_repair_rounds,
      timeout_seconds: bootstrap.defaults.timeout_seconds, batch_size: bootstrap.defaults.batch_size,
      max_tokens: null, provider_pin: bootstrap.defaults.provider_pin,
      providers: [], fallback_models: [], stream_responses: false,
    };
  };
  const [groupId, setGroupId] = useState(`dev-group-${compactTimestamp()}`);
  const [parallelGroups, setParallelGroups] = useState(bootstrap.defaults.max_parallel_experiments);
  const [scope, setScope] = useState<"formal_dev" | "regression">("formal_dev");
  const [regressionPapers, setRegressionPapers] = useState<string[]>(() => {
    const preferred = bootstrap.papers.filter((paper) => preferredRegressionPapers.includes(paper));
    return preferred.length ? preferred : bootstrap.papers.slice(0, Math.min(3, bootstrap.papers.length));
  });
  const [drafts, setDrafts] = useState<Draft[]>(() => [newDraft(1)]);
  const [preflight, setPreflight] = useState<GroupPreflight | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selected = drafts.filter((draft) => draft.selected);
  const payload = useMemo<GroupRequest>(() => ({
    group_id: slug(groupId),
    max_parallel_experiments: parallelGroups,
    scope,
    paper_ids: scope === "formal_dev" ? bootstrap.papers : regressionPapers,
    experiments: selected.map(({ key: _key, selected: _selected, ...request }) => request),
  }), [bootstrap.papers, drafts, groupId, parallelGroups, regressionPapers, scope]);

  function invalidate() { setPreflight(null); setError(""); }
  function patchDraft(key: string, patch: Partial<Draft>) {
    setDrafts((items) => items.map((item) => item.key === key ? { ...item, ...patch } : item));
    invalidate();
  }
  function addExperiment(source?: Draft) {
    setDrafts((items) => {
      const next = source
        ? { ...source, key: crypto.randomUUID(), experiment_name: `${source.experiment_name} 副本`, run_id: `${source.run_id}-copy-${items.length + 1}` }
        : newDraft(items.length + 1);
      return [...items, next];
    });
    invalidate();
  }
  function togglePaper(paperId: string) {
    setRegressionPapers((papers) => papers.includes(paperId)
      ? papers.filter((paper) => paper !== paperId)
      : bootstrap.papers.filter((paper) => papers.includes(paper) || paper === paperId));
    invalidate();
  }
  function selectScope(nextScope: "formal_dev" | "regression") {
    setScope(nextScope);
    if (nextScope === "formal_dev") {
      setDrafts((items) => items.map((item) => ({ ...item, task_surface: "core_prov" })));
    }
    invalidate();
  }
  async function runPreflight() {
    setBusy(true); setError("");
    try { setPreflight(await api.preflightGroup(payload)); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }
  async function start() {
    if (!preflight?.ok) return;
    setBusy(true); setError("");
    try {
      const group = await api.createGroup(preflight.request);
      navigate(`/runs/${encodeURIComponent(group.group_id)}`);
    } catch (reason) { setError((reason as Error).message); setBusy(false); }
  }

  return (
    <div className="page setup-page">
      <PageIntro
        eyebrow="新的实验组"
        title="先把实验配置清楚，再开始运行。"
        description="每张卡片是一套独立参数。你可以让多个实验同时运行，其余实验会自动排队；只有所有已勾选实验都通过服务端检查，启动按钮才会开放。"
      />

      <div className="setup-layout">
        <div className="setup-main">
          <SetupStep number="1" title="命名实验组并设置并发">
            <div className="field-grid two-columns">
              <label><span>实验组 ID</span><input value={groupId} onChange={(event) => { setGroupId(event.target.value); invalidate(); }} /></label>
              <label><span>同时运行的实验数</span><select value={parallelGroups} onChange={(event) => { setParallelGroups(Number(event.target.value)); invalidate(); }}>
                {[1, 2, 3, 4].map((value) => <option key={value} value={value}>{value} 个实验</option>)}
              </select></label>
            </div>
            <p className="field-help">单篇论文内部的并发由每张实验卡单独控制。实验组并发上限为 4。</p>
            <div className="scope-selector" role="group" aria-label="运行范围">
              <button type="button" className={scope === "formal_dev" ? "active" : ""} onClick={() => selectScope("formal_dev")}>
                <strong>正式 Dev</strong><small>固定运行全部 {bootstrap.papers.length} 篇，可在成功后评估和封存</small>
              </button>
              <button type="button" className={scope === "regression" ? "active" : ""} onClick={() => selectScope("regression")}>
                <strong>定向回归</strong><small>选择 1–{bootstrap.papers.length} 篇，只用于修复验证</small>
              </button>
            </div>
            <div className={`paper-selector ${scope === "formal_dev" ? "locked" : ""}`}>
              <div><strong>{scope === "formal_dev" ? "Dev 文献（固定）" : "选择回归文献"}</strong><small>{scope === "formal_dev" ? "正式实验不可取消论文。" : "同组所有实验使用完全相同的论文集合。"}</small></div>
              <div className="paper-selector-grid">
                {bootstrap.papers.map((paper) => <label className="check-control" key={paper}>
                  <input
                    type="checkbox"
                    checked={scope === "formal_dev" || regressionPapers.includes(paper)}
                    disabled={scope === "formal_dev"}
                    onChange={() => togglePaper(paper)}
                  />
                  <span>{paper}</span>
                </label>)}
              </div>
              {scope === "regression" && regressionPapers.length === 0 && <p className="inline-error">至少选择一篇 dev 文献。</p>}
            </div>
          </SetupStep>

          <SetupStep number="2" title="配置一个或多个实验">
            <div className="experiment-list">
              {drafts.map((draft, index) => (
                <article className={`experiment-card ${draft.selected ? "selected" : "muted"}`} key={draft.key}>
                  <div className="experiment-card-head">
                    <label className="check-control"><input type="checkbox" checked={draft.selected} onChange={(event) => patchDraft(draft.key, { selected: event.target.checked })} /><span>纳入本次运行</span></label>
                    <div className="card-actions">
                      <button className="text-button" type="button" onClick={() => addExperiment(draft)}>复制</button>
                      <button className="text-button danger-text" type="button" disabled={drafts.length === 1} onClick={() => { setDrafts((items) => items.filter((item) => item.key !== draft.key)); invalidate(); }}>删除</button>
                    </div>
                  </div>
                  <div className="experiment-title-row">
                    <input className="experiment-name" aria-label={`实验 ${index + 1} 名称`} value={draft.experiment_name} onChange={(event) => patchDraft(draft.key, { experiment_name: event.target.value })} />
                    <div className="method-switch" aria-label="工作流方法"><strong>Method B</strong></div>
                  </div>
                  <div className="field-grid two-columns">
                    <label><span>Run ID</span><input value={draft.run_id} onChange={(event) => patchDraft(draft.key, { run_id: slug(event.target.value) })} /></label>
                    <label><span>提取模型</span><input list="known-models" value={draft.extractor_model} onChange={(event) => patchDraft(draft.key, { extractor_model: event.target.value })} /></label>
                    <label><span>复核模型</span><input list="known-models" value={draft.reviewer_model} onChange={(event) => patchDraft(draft.key, { reviewer_model: event.target.value })} /></label>
                    <label><span>任务范围</span><select aria-label={`实验 ${index + 1} 任务范围`} value={draft.task_surface} disabled><option value="core_prov">核心字段 + provenance</option></select></label>
                    <label><span>论文并发</span><input type="number" min="1" max="10" value={draft.parallel} onChange={(event) => patchDraft(draft.key, { parallel: Number(event.target.value) })} /></label>
                    <label><span>最多修复轮次</span><input type="number" min="0" max="10" value={draft.max_repair_rounds} onChange={(event) => patchDraft(draft.key, { max_repair_rounds: Number(event.target.value) })} /></label>
                  </div>
                  <details className="advanced-fields"><summary>高级参数</summary>
                    <div className="field-grid two-columns">
                      <label><span>请求超时（秒）</span><input type="number" min="30" max="3600" value={draft.timeout_seconds} onChange={(event) => patchDraft(draft.key, { timeout_seconds: Number(event.target.value) })} /></label>
                      {draft.method === "B" && <><label><span>Batch size</span><input type="number" min="1" max="32" value={draft.batch_size} onChange={(event) => patchDraft(draft.key, { batch_size: Number(event.target.value) })} /></label><label><span>Max tokens（留空使用 Provider 默认值）</span><input type="number" min="1" max="1000000" value={draft.max_tokens ?? ""} onChange={(event) => patchDraft(draft.key, { max_tokens: event.target.value ? Number(event.target.value) : null })} /></label><label><span>Provider 优先级（逗号分隔）</span><input value={draft.providers.join(", ")} onChange={(event) => patchDraft(draft.key, { providers: csvValues(event.target.value) })} placeholder="deepseek, openai" /></label><label className="full-field"><span>Fallback 模型（逗号分隔）</span><input value={draft.fallback_models.join(", ")} onChange={(event) => patchDraft(draft.key, { fallback_models: csvValues(event.target.value) })} placeholder="model-a, model-b" /></label><label className="check-control full-field"><input type="checkbox" checked={draft.provider_pin} onChange={(event) => patchDraft(draft.key, { provider_pin: event.target.checked })} /><span>固定 Provider（推荐用于可复现实验）</span></label></>}
                    </div>
                  </details>
                </article>
              ))}
            </div>
            <datalist id="known-models">{bootstrap.models.map((model) => <option value={model} key={model} />)}</datalist>
            <button className="secondary-button add-button" type="button" onClick={() => addExperiment()}>＋ 添加另一个实验</button>
          </SetupStep>

          <SetupStep number="3" title="统一预检并启动">
            <div className="preflight-box">
              <div><strong>将检查 {selected.length} 个实验 · {payload.paper_ids.length} 篇论文</strong><p>环境、所选 dev 输入、schema/rule 视图、密钥、Run ID 和活动进程都会由服务端检查。</p></div>
              <button className="secondary-button" disabled={busy || selected.length === 0 || !payload.group_id || payload.paper_ids.length === 0} onClick={() => void runPreflight()}>{busy ? "正在检查…" : "运行全部检查"}</button>
            </div>
            {preflight && <div className={`check-results ${preflight.ok ? "checks-ok" : "checks-failed"}`}>
              <h3>{preflight.ok ? "全部检查通过" : "仍有检查未通过"}</h3>
              {[...preflight.group_checks, ...preflight.experiments.flatMap((item) => item.checks.map((check) => ({ ...check, name: `${item.run_id} · ${check.name}` })))].map((check, index) => (
                <div className="check-row" key={`${check.name}-${index}`}><span aria-hidden="true">{check.ok ? "✓" : "!"}</span><strong>{check.name}</strong><small>{check.detail}</small></div>
              ))}
            </div>}
            {error && <p className="inline-error">{error}</p>}
          </SetupStep>
        </div>

        <aside className="launch-summary">
          <p className="eyebrow">运行摘要</p>
          <h2>{selected.length} 个实验</h2>
          <dl><div><dt>运行范围</dt><dd>{scope === "formal_dev" ? "正式 Dev" : "定向回归"}</dd></div><div><dt>实验并发</dt><dd>{parallelGroups}</dd></div><div><dt>Dev 论文</dt><dd>{payload.paper_ids.length} / 实验</dd></div><div><dt>响应模式</dt><dd>整包响应</dd></div></dl>
          <p className="summary-note">{scope === "formal_dev" ? "正式实验完成后可以进入评估和封存；只有明确的外部服务故障可重试。" : "回归 Run 永不评估、封存、恢复或重试；如仍失败，应修复工作流后新开回归实验。"}</p>
          <button className="primary-button launch-button" disabled={!preflight?.ok || busy} onClick={() => void start()}><span>{busy ? "正在创建…" : "开始运行"}</span><span aria-hidden="true">→</span></button>
          {!preflight?.ok && <small className="button-hint">先完成服务端预检，启动按钮才会开放。</small>}
        </aside>
      </div>
    </div>
  );
}
