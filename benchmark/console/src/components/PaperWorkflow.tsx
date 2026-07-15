import { useEffect, useMemo, useState } from "react";
import type { Method, PaperDiagnostic, TraceEvent } from "../types";

type NodeStatus = "queued" | "running" | "completed" | "failed";

interface StageDefinition {
  id: string;
  label: string;
  shortLabel: string;
  description: string;
  aliases: string[];
}

interface WorkflowNode extends StageDefinition {
  status: NodeStatus;
  eventCount: number;
}

export interface ToolCallGroup {
  name: string;
  count: number;
  running: number;
  completed: number;
  lastSeq: number;
}

export interface StepSegment {
  key: string;
  kind: "system" | "model" | "tool" | "validation" | "retry";
  label: string;
  count: number;
  status: NodeStatus;
  firstSeq: number;
  lastSeq: number;
  firstAt: string;
  lastAt: string;
  detail: string;
}

const METHOD_STAGES: Record<Method, StageDefinition[]> = {
  B: [
    { id: "context", label: "上下文准备", shortLabel: "上下文", description: "整理论文正文、表格和本次实验所需的确定性输入。", aliases: ["context"] },
    { id: "roster", label: "候选 Roster", shortLabel: "Roster", description: "用与任务字段无关的规则确定候选名单，并冻结后续顺序。", aliases: ["roster"] },
    { id: "scaffold", label: "候选框架", shortLabel: "框架", description: "生成论文级结构、方法链和候选字段骨架。", aliases: ["scaffold"] },
    { id: "extraction", label: "分批提取", shortLabel: "提取", description: "按固定工作流分批填写候选记录；必要时只回修受影响批次。", aliases: ["batch", "rebatch", "repair"] },
    { id: "validation", label: "结构校验", shortLabel: "校验", description: "检查 schema、证据定位、标识符和阻断级结构规则。", aliases: ["validation", "validate"] },
    { id: "review", label: "工作流复核", shortLabel: "复核", description: "Method B 使用一次结构化工作流调用完成独立复核。", aliases: ["review"] },
    { id: "final", label: "最终交付", shortLabel: "交付", description: "保存 extraction、review 和 report 等可调试产物。", aliases: ["final"] },
  ],
  C: [
    { id: "context", label: "上下文准备", shortLabel: "上下文", description: "整理论文正文、表格和只读工具可访问的确定性输入。", aliases: ["context"] },
    { id: "roster", label: "候选 Roster", shortLabel: "Roster", description: "受控智能体只负责发现候选；名单在后续阶段保持冻结。", aliases: ["roster"] },
    { id: "plan", label: "候选规划", shortLabel: "规划", description: "建立论文级方法链和候选提取计划。", aliases: ["plan"] },
    { id: "candidate", label: "候选提取", shortLabel: "候选", description: "逐候选运行受控工具循环，读取证据并提交结构化记录。", aliases: ["cand-", "candidate", "repair"] },
    { id: "validation", label: "结构校验", shortLabel: "校验", description: "检查 schema、证据定位、标识符和阻断级结构规则。", aliases: ["validation", "validate"] },
    { id: "review", label: "智能体复核", shortLabel: "复核", description: "受预算和终止规则控制的独立 reviewer 检查可行动问题。", aliases: ["review"] },
    { id: "final", label: "最终交付", shortLabel: "交付", description: "保存 extraction、review 和 report 等可调试产物。", aliases: ["final"] },
  ],
};

const successStatuses = new Set(["ok", "ok_with_cjk_warnings", "completed", "sealed"]);
const waitingStatuses = new Set(["missing", "queued", "waiting"]);

function eventStageMatches(stage: StageDefinition, event: TraceEvent) {
  const values = [event.stage, event.node_id].filter(Boolean) as string[];
  return stage.aliases.some((alias) => values.some((value) => value.startsWith(alias)));
}

function stageIndexForValue(stages: StageDefinition[], value?: string) {
  if (!value) return -1;
  if (value === "completed") return stages.length - 1;
  return stages.findIndex((stage) => stage.aliases.some((alias) => value.startsWith(alias)));
}

function explicitEventStatus(events: TraceEvent[]): NodeStatus | null {
  if (!events.length) return null;
  const latest = [...events].sort((left, right) => right.seq - left.seq)[0];
  if (latest.status === "failed" || latest.type.includes("failed") || latest.type.includes("exhausted")) return "failed";
  if (latest.status === "running" || latest.status === "retrying" || latest.type.endsWith(".started")) return "running";
  if (["completed", "passed", "accepted", "ok", "ok_with_cjk_warnings"].includes(latest.status || "")
    || latest.type.endsWith(".completed") || latest.type === "context.packed") return "completed";
  return null;
}

export function buildWorkflowNodes(method: Method | "unknown", diagnostic: PaperDiagnostic, events: TraceEvent[]): WorkflowNode[] {
  const stages = METHOD_STAGES[method === "C" ? "C" : "B"];
  const currentIndex = stageIndexForValue(stages, diagnostic.stage);
  const success = successStatuses.has(diagnostic.status);
  const waiting = waitingStatuses.has(diagnostic.status);
  const failed = !success && !waiting && diagnostic.status !== "running";

  return stages.map((stage, index) => {
    const stageEvents = events.filter((event) => eventStageMatches(stage, event));
    let status = explicitEventStatus(stageEvents) || "queued";
    if (success) status = "completed";
    else if (waiting) status = "queued";
    else if (currentIndex >= 0) {
      if (index < currentIndex) status = "completed";
      else if (index > currentIndex) status = "queued";
      else status = failed ? "failed" : "running";
    }
    return { ...stage, status, eventCount: stageEvents.length };
  });
}

function toolName(event: TraceEvent) {
  return String(event.summary || event.data?.tool_name || event.data?.name || "工具调用");
}

export function groupRepeatedToolCalls(events: TraceEvent[]): ToolCallGroup[] {
  const starts = events.filter((event) => event.type === "tool.call.started");
  const startedIds = new Set(starts.map((event) => event.call_id).filter(Boolean));
  const completions = events.filter((event) => event.type === "tool.call.completed");
  const completedIds = new Set(completions.map((event) => event.call_id).filter(Boolean));
  const occurrences = [
    ...starts,
    ...completions.filter((event) => !event.call_id || !startedIds.has(event.call_id)),
  ];
  const groups = new Map<string, ToolCallGroup>();
  for (const event of occurrences) {
    const name = toolName(event);
    const group = groups.get(name) || { name, count: 0, running: 0, completed: 0, lastSeq: 0 };
    group.count += 1;
    group.lastSeq = Math.max(group.lastSeq, event.seq);
    const isRunning = event.type === "tool.call.started" && (!event.call_id || !completedIds.has(event.call_id));
    if (isRunning) group.running += 1;
    else group.completed += 1;
    groups.set(name, group);
  }
  return [...groups.values()].sort((left, right) => (right.running - left.running) || (right.lastSeq - left.lastSeq));
}

function activityLabel(event: TraceEvent) {
  if (event.type === "paper.started") return "论文任务已开始";
  if (event.type === "context.packed") return "上下文已打包";
  if (event.type === "llm.request.started") return "正在请求模型完成本阶段";
  if (event.type === "llm.response.completed") return "已收到一次完整模型响应";
  if (event.type === "llm.request.failed") return event.summary || "模型请求失败";
  if (event.type === "tool.call.started") return `正在调用 ${toolName(event)}`;
  if (event.type === "tool.call.completed") return `${toolName(event)} 已完成`;
  if (event.type === "validation.completed") {
    const errors = Number(event.data?.errors || 0);
    return errors ? `校验发现 ${errors} 个阻断错误` : "本轮结构校验通过";
  }
  if (event.type === "paper.completed") return successStatuses.has(event.status || "") ? "论文已成功交付" : "论文运行结束但未成功交付";
  return event.summary || event.type;
}

interface CallState {
  completedModelCalls: Set<string>;
  failedModelCalls: Set<string>;
  completedTools: Set<string>;
  startedTools: Set<string>;
}

function callIds(events: TraceEvent[], type: string) {
  return new Set(events.filter((event) => event.type === type).map((event) => event.call_id).filter((value): value is string => Boolean(value)));
}

function atomicStep(event: TraceEvent, state: CallState): Omit<StepSegment, "count" | "lastSeq" | "lastAt"> | null {
  const { completedModelCalls, failedModelCalls, completedTools, startedTools } = state;
  if (event.type === "llm.request.started") {
    const failed = Boolean(event.call_id && failedModelCalls.has(event.call_id));
    const completed = Boolean(event.call_id && completedModelCalls.has(event.call_id));
    return {
      key: "model-call",
      kind: "model",
      label: "模型调用",
      status: failed ? "failed" : completed ? "completed" : "running",
      firstSeq: event.seq,
      firstAt: event.occurred_at,
      detail: event.summary || "向模型提交本阶段请求",
    };
  }
  if (event.type === "tool.call.started") {
    const completed = Boolean(event.call_id && completedTools.has(event.call_id));
    const name = toolName(event);
    return {
      key: `tool:${name}`,
      kind: "tool",
      label: name,
      status: completed ? "completed" : "running",
      firstSeq: event.seq,
      firstAt: event.occurred_at,
      detail: "工具调用",
    };
  }
  if (event.type === "tool.call.completed" && (!event.call_id || !startedTools.has(event.call_id))) {
    const name = toolName(event);
    return {
      key: `tool:${name}`,
      kind: "tool",
      label: name,
      status: event.status === "failed" ? "failed" : "completed",
      firstSeq: event.seq,
      firstAt: event.occurred_at,
      detail: "工具调用",
    };
  }
  if (event.type === "validation.completed") return {
    key: "validation",
    kind: "validation",
    label: "结构校验",
    status: event.status === "needs_repair" ? "failed" : "completed",
    firstSeq: event.seq,
    firstAt: event.occurred_at,
    detail: activityLabel(event),
  };
  if (event.type.includes("retry") || event.type.includes("repair")) return {
    key: event.type,
    kind: "retry",
    label: event.type.includes("repair") ? "定向修复" : "调用重试",
    status: event.status === "failed" ? "failed" : event.status === "completed" ? "completed" : "running",
    firstSeq: event.seq,
    firstAt: event.occurred_at,
    detail: event.summary || activityLabel(event),
  };
  if (["paper.started", "context.packed", "paper.completed"].includes(event.type)) return {
    key: event.type,
    kind: "system",
    label: activityLabel(event),
    status: event.type === "paper.started" ? "running" : event.status === "failed" ? "failed" : "completed",
    firstSeq: event.seq,
    firstAt: event.occurred_at,
    detail: event.summary || activityLabel(event),
  };
  return null;
}

export function groupConsecutiveSteps(events: TraceEvent[]): StepSegment[] {
  const sorted = [...events].sort((left, right) => left.seq - right.seq);
  const state: CallState = {
    completedModelCalls: callIds(sorted, "llm.response.completed"),
    failedModelCalls: callIds(sorted, "llm.request.failed"),
    completedTools: callIds(sorted, "tool.call.completed"),
    startedTools: callIds(sorted, "tool.call.started"),
  };
  const steps = sorted.map((event) => atomicStep(event, state)).filter(Boolean) as Omit<StepSegment, "count" | "lastSeq" | "lastAt">[];
  const segments: StepSegment[] = [];
  for (const step of steps) {
    const previous = segments.at(-1);
    if (previous?.key === step.key) {
      previous.count += 1;
      previous.lastSeq = step.firstSeq;
      previous.lastAt = step.firstAt;
      previous.detail = step.detail;
      if (step.status === "failed" || (step.status === "running" && previous.status !== "failed")) previous.status = step.status;
      continue;
    }
    segments.push({ ...step, count: 1, lastSeq: step.firstSeq, lastAt: step.firstAt });
  }
  return segments;
}

function statusLabel(status: NodeStatus) {
  return { queued: "等待", running: "正在运行", completed: "已完成", failed: "失败" }[status];
}

function WorkflowInspector({ method, diagnostic, events }: {
  method: Method | "unknown";
  diagnostic: PaperDiagnostic;
  events: TraceEvent[];
}) {
  const nodes = useMemo(() => buildWorkflowNodes(method, diagnostic, events), [method, diagnostic, events]);
  const defaultNode = nodes.find((node) => node.status === "running" || node.status === "failed")?.id
    || [...nodes].reverse().find((node) => node.status === "completed")?.id
    || nodes[0].id;
  const [selectedId, setSelectedId] = useState(defaultNode);

  useEffect(() => {
    setSelectedId(defaultNode);
  }, [diagnostic.paper_id, defaultNode]);

  const selected = nodes.find((node) => node.id === selectedId) || nodes[0];
  const selectedEvents = events.filter((event) => eventStageMatches(selected, event));
  const tools = groupRepeatedToolCalls(selectedEvents);
  const stepSegments = groupConsecutiveSteps(selectedEvents);
  const modelCalls = selectedEvents.filter((event) => event.type === "llm.request.started").length;

  return <section className="paper-detail-section workflow-inspector">
    <div className="workflow-section-heading">
      <div><p className="eyebrow">实时节点</p><h3>执行流程</h3></div>
      <small>每 3 秒刷新 · 只读取结构事件</small>
    </div>
    <div className="paper-workflow-track" aria-label="论文执行流程">
      {nodes.map((node, index) => <div className="workflow-track-item" key={node.id}>
        <button
          className={`workflow-node node-${node.status} ${selected.id === node.id ? "selected" : ""}`}
          aria-label={`${node.label}：${statusLabel(node.status)}`}
          aria-pressed={selected.id === node.id}
          onClick={() => setSelectedId(node.id)}
        >
          <span className="workflow-node-index">{String(index + 1).padStart(2, "0")}</span>
          <strong>{node.shortLabel}</strong>
          <small>{statusLabel(node.status)}</small>
          {node.status === "running" && <i aria-hidden="true" />}
        </button>
        {index < nodes.length - 1 && <span className={`workflow-connector connector-${nodes[index + 1].status}`} aria-hidden="true"><i /></span>}
      </div>)}
    </div>
    <div className={`workflow-node-detail detail-${selected.status}`}>
      <header>
        <div><small>节点 {String(nodes.findIndex((node) => node.id === selected.id) + 1).padStart(2, "0")}</small><h4>{selected.label}</h4></div>
        <span>{statusLabel(selected.status)}</span>
      </header>
      <p>{selected.description}</p>
      <div className="workflow-activity-metrics">
        <span><small>模型调用</small><strong>× {modelCalls}</strong></span>
        <span><small>工具调用</small><strong>× {tools.reduce((total, tool) => total + tool.count, 0)}</strong></span>
        <span><small>结构事件</small><strong>× {selected.eventCount}</strong></span>
      </div>
      <div className="workflow-step-segments">
        <h5>步骤记录（连续重复已合并）</h5>
        {stepSegments.length > 0
          ? <ol>{stepSegments.map((segment) => <li className={`segment-${segment.kind} segment-${segment.status}`} key={`${segment.firstSeq}:${segment.key}`}>
            <span className="segment-mark" aria-hidden="true">{segment.kind === "tool" ? "⌘" : segment.kind === "model" ? "AI" : "•"}</span>
            <div><strong>{segment.label}</strong><small>{segment.detail}</small></div>
            {segment.count > 1 && <b>× {segment.count}</b>}
            <time>{new Date(segment.lastAt).toLocaleTimeString()}</time>
          </li>)}</ol>
          : <p>{selected.status === "queued" ? "该节点尚未开始。" : "该节点没有更多结构事件。"}</p>}
      </div>
    </div>
  </section>;
}

export function PaperWorkflow(props: {
  method: Method | "unknown";
  diagnostic: PaperDiagnostic;
  events: TraceEvent[];
}) {
  return <WorkflowInspector {...props} />;
}
