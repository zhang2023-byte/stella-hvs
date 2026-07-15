import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { ModelCallTranscript } from "../hooks/useRunTraceStreams";
import type { TraceEvent } from "../types";
import type { GraphSelection } from "./WorkflowGraph";

type Tab = "conversation" | "request" | "tool" | "validation" | "raw";

const tabLabels: Record<Tab, string> = {
  conversation: "会话",
  request: "模型输入",
  tool: "工具",
  validation: "校验 / 重试",
  raw: "原始 Trace",
};

const statusLabels: Record<ModelCallTranscript["status"], string> = {
  waiting: "等待模型",
  streaming: "正在回复",
  retrying: "本次中断，正在重试",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
};

interface TraceScope {
  paper_id?: string;
  stage?: string;
  node_id?: string;
  source_node_id?: string;
  target_node_id?: string;
  type?: string;
}

interface ToolCallView {
  key: string;
  call_id?: string;
  first_seq: number;
  name: string;
  started?: TraceEvent;
  completed?: TraceEvent;
}

interface HydratedResponse {
  content: string;
  reasoning: string;
  model?: string;
  tool_call_count?: number;
}

export function extractResponsePresentation(payload: unknown): HydratedResponse {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return { content: "", reasoning: "" };
  const response = payload as Record<string, unknown>;
  const choices = Array.isArray(response.choices) ? response.choices : [];
  const first = choices[0];
  const choice = first && typeof first === "object" && !Array.isArray(first) ? first as Record<string, unknown> : {};
  const rawMessage = choice.message;
  const message = rawMessage && typeof rawMessage === "object" && !Array.isArray(rawMessage)
    ? rawMessage as Record<string, unknown>
    : {};
  const text = (value: unknown) => {
    if (typeof value === "string") return value;
    if (!Array.isArray(value)) return "";
    return value.map((part) => {
      if (typeof part === "string") return part;
      if (!part || typeof part !== "object" || Array.isArray(part)) return "";
      const item = part as Record<string, unknown>;
      return typeof item.text === "string" ? item.text : "";
    }).join("");
  };
  const reasoning = message.reasoning_content ?? message.reasoning;
  return {
    content: text(message.content),
    reasoning: text(reasoning),
    model: typeof response.model === "string" ? response.model : undefined,
    tool_call_count: Array.isArray(message.tool_calls) ? message.tool_calls.length : undefined,
  };
}

function eventText(event: TraceEvent) {
  const text = event.data?.text;
  if (typeof text === "string") return text;
  const delta = event.data?.delta;
  if (typeof delta === "string") return delta;
  return event.summary || event.type;
}

function stageMatches(id: string, event: TraceScope) {
  const aliases: Record<string, string[]> = {
    batch: ["batch", "rebatch"], candidate: ["cand-"], validate: ["valid"],
    context: ["context"], scaffold: ["scaffold"], plan: ["plan"],
    repair: ["repair"], review: ["review"], final: ["final"],
  };
  return (aliases[id] || [id]).some((value) => event.stage?.startsWith(value) || event.node_id?.startsWith(value));
}

function matchesSelection(event: TraceScope, paperId: string | undefined, selection: GraphSelection) {
  if (paperId && event.paper_id !== paperId) return false;
  if (selection.kind === "node") {
    if (selection.id.startsWith("paper:")) return event.paper_id === selection.id.slice(6);
    return stageMatches(selection.id, event) || (selection.id === "final" && event.type === "paper.completed");
  }
  if (!selection.source || !selection.target) return true;
  const source = selection.source.replace("paper:", "");
  const target = selection.target.replace("paper:", "");
  const paperEdge = selection.source.startsWith("paper:") || selection.target.startsWith("paper:");
  const direct = event.source_node_id?.includes(source) && event.target_node_id?.includes(target);
  const adjacentStage = stageMatches(source, event) || stageMatches(target, event);
  const adjacentPaper = event.paper_id === source || event.paper_id === target;
  return Boolean(direct || (paperEdge ? adjacentPaper : adjacentStage));
}

function isValidationEvent(event: TraceEvent) {
  return event.type.includes("valid")
    || event.type.includes("retry")
    || event.type.includes("repair")
    || event.type.includes("failed")
    || event.type.includes("interrupted");
}

function groupToolCalls(events: TraceEvent[]) {
  const calls: ToolCallView[] = [];
  for (const event of events) {
    if (event.type !== "tool.call.started" && event.type !== "tool.call.completed") continue;
    const callId = event.call_id;
    let call = callId ? [...calls].reverse().find((item) => item.call_id === callId && !item.completed) : undefined;
    if (event.type === "tool.call.started" || !call) {
      call = {
        key: `${callId || "tool"}:${event.seq}`,
        call_id: callId,
        first_seq: event.seq,
        name: event.summary || String(event.data?.tool_name || event.data?.name || "工具调用"),
      };
      calls.push(call);
    }
    if (event.type === "tool.call.started") call.started = event;
    else call.completed = event;
  }
  return calls;
}

function stageLabel(stage?: string) {
  if (!stage) return "运行";
  if (stage === "context") return "上下文准备";
  if (stage === "scaffold") return "候选框架";
  if (stage === "plan") return "规划与工具循环";
  if (stage.startsWith("cand-") || stage.startsWith("batch")) return "分批提取";
  if (stage.startsWith("valid")) return "结构校验";
  if (stage.startsWith("repair")) return "修复";
  if (stage.startsWith("review")) return "独立复核";
  if (stage.startsWith("final")) return "最终交付";
  return stage;
}

function formatDuration(duration?: number) {
  if (duration === undefined) return "";
  return duration < 1_000 ? `${duration} ms` : `${(duration / 1_000).toFixed(1)} s`;
}

function reasoningLabel(call: ModelCallTranscript) {
  if (call.status === "waiting" || call.status === "streaming") return "正在思考…";
  if (call.status === "retrying") return "本次可见推理（重试中）";
  if (call.status === "failed") return "本次可见推理（失败）";
  if (call.status === "interrupted") return "本次可见推理（已中断）";
  return call.reasoning ? "可见推理已完成" : "Provider 未返回可见推理";
}

function responsePlaceholder(call: ModelCallTranscript) {
  if (call.tool_call_count) return `模型已请求调用 ${call.tool_call_count} 个工具。`;
  if (call.status === "waiting" || call.status === "streaming") return "模型正在组织回复…";
  if (call.status === "retrying") return "本次响应中断，系统正在重试；新的 attempt 会单独显示。";
  if (call.status === "failed") return "本次模型调用失败。请在“校验 / 重试”中查看原因。";
  if (call.status === "interrupted") return "本次模型调用已中断。";
  return "本轮没有文本回复。";
}

export function TraceDrawer({
  campaignId,
  runId,
  selection,
  paperId,
  events,
  transcripts = [],
  runStatus,
  onClose,
}: {
  campaignId: string;
  runId: string;
  selection: GraphSelection;
  paperId?: string;
  events: TraceEvent[];
  transcripts?: ModelCallTranscript[];
  runStatus?: string;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("conversation");
  const [active, setActive] = useState<TraceEvent | null>(null);
  const [payload, setPayload] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [hydratedResponses, setHydratedResponses] = useState<Record<string, HydratedResponse>>({});
  const hydrating = useRef(new Set<string>());
  const hydrationRun = useRef(runId);
  const scopedEvents = useMemo(
    () => events.filter((event) => matchesSelection(event, paperId, selection)),
    [events, paperId, selection],
  );
  const scopedTranscripts = useMemo(
    () => transcripts.filter((call) => matchesSelection(call, paperId, selection)),
    [transcripts, paperId, selection],
  );
  const toolCalls = useMemo(() => groupToolCalls(scopedEvents), [scopedEvents]);
  const validationEvents = useMemo(() => scopedEvents.filter(isValidationEvent), [scopedEvents]);
  const requestEvents = useMemo(() => scopedEvents.filter((event) => event.type === "llm.request.started"), [scopedEvents]);
  const conversationItems = useMemo(() => [
    ...scopedTranscripts.map((call) => ({ kind: "model" as const, seq: call.first_seq, call })),
    ...toolCalls.map((tool) => ({ kind: "tool" as const, seq: tool.first_seq, tool })),
    ...validationEvents.map((event) => ({ kind: "activity" as const, seq: event.seq, event })),
  ].sort((left, right) => left.seq - right.seq), [scopedTranscripts, toolCalls, validationEvents]);

  useEffect(() => {
    setActive(null);
    setPayload(null);
  }, [selection.id, tab, runId]);

  useEffect(() => {
    hydrationRun.current = runId;
    setHydratedResponses({});
    hydrating.current.clear();
  }, [runId]);

  useEffect(() => {
    for (const call of scopedTranscripts.slice(-16)) {
      const digest = call.response_event?.payload_ref?.sha256;
      if (!digest || hydratedResponses[call.key] || hydrating.current.has(call.key)) continue;
      hydrating.current.add(call.key);
      void api.blob(campaignId, runId, digest)
        .then((response) => {
          if (hydrationRun.current === runId) {
            setHydratedResponses((current) => ({
              ...current,
              [call.key]: extractResponsePresentation(response.payload),
            }));
          }
        })
        .catch(() => undefined)
        .finally(() => hydrating.current.delete(call.key));
    }
  }, [campaignId, runId, scopedTranscripts]);

  async function loadPayload(event: TraceEvent) {
    setActive(event);
    setPayload(null);
    if (!event.payload_ref) return;
    setLoading(true);
    try {
      setPayload((await api.blob(campaignId, runId, event.payload_ref.sha256)).payload);
    } catch (reason) {
      setPayload({ error: (reason as Error).message });
    } finally {
      setLoading(false);
    }
  }

  const rawEventList = (items: TraceEvent[]) => (
    <div className="trace-list raw-trace-list">
      {items.length === 0 && <div className="empty-state compact"><strong>还没有匹配事件</strong><p>节点开始工作后，事件会实时出现在这里。</p></div>}
      {items.slice(-160).reverse().map((event) => (
        <button className={`trace-event ${active?.seq === event.seq ? "active" : ""}`} key={event.seq} onClick={() => void loadPayload(event)}>
          <span className="trace-dot" />
          <span><strong>{event.type}</strong><small>{new Date(event.occurred_at).toLocaleTimeString()} · {event.stage || "run"}{event.attempt ? ` · attempt ${event.attempt}` : ""}</small><em>{eventText(event)}</em></span>
        </button>
      ))}
    </div>
  );

  const toolCard = (tool: ToolCallView) => {
    const event = tool.completed || tool.started;
    const completed = Boolean(tool.completed);
    return (
      <article className={`tool-turn ${completed ? "completed" : "running"}`} key={tool.key}>
        <div className="tool-turn-icon" aria-hidden="true">⌘</div>
        <div className="tool-turn-body">
          <div className="turn-heading"><div><small>工具调用</small><h3>{tool.name}</h3></div><span>{completed ? `已完成${tool.completed?.duration_ms !== undefined ? ` · ${formatDuration(tool.completed.duration_ms)}` : ""}` : "执行中"}</span></div>
          {event && <p>{new Date(event.occurred_at).toLocaleTimeString()} · {stageLabel(event.stage)}</p>}
          <div className="turn-actions">
            {tool.started?.payload_ref && <button onClick={() => void loadPayload(tool.started!)}>查看调用参数</button>}
            {tool.completed?.payload_ref && <button onClick={() => void loadPayload(tool.completed!)}>查看工具结果</button>}
          </div>
        </div>
      </article>
    );
  };

  return (
    <aside className="trace-drawer" aria-label="运行事件详情">
      <div className="drawer-head"><div><p className="eyebrow">{selection.kind === "node" ? "节点详情" : "边上的信息流"}</p><h2>{selection.label}</h2>{paperId && <small>{paperId}</small>}</div><button className="icon-button" aria-label="关闭详情" onClick={onClose}>×</button></div>
      <div className="drawer-notice">“正在思考”仅指 Provider 返回的可见 reasoning；这里不会展示或推测隐藏思考。模型回复已按调用聚合，逐条 delta 仅保留在“原始 Trace”。</div>
      <div className="drawer-tabs" role="tablist">{(Object.keys(tabLabels) as Tab[]).map((value) => <button role="tab" aria-selected={tab === value} className={tab === value ? "active" : ""} onClick={() => setTab(value)} key={value}>{tabLabels[value]}</button>)}</div>

      {tab === "conversation" && <div className="conversation-list" aria-live="polite">
        {conversationItems.length === 0 && <div className="empty-state compact"><strong>这个节点还没有会话</strong><p>模型开始回复或调用工具后，这里会显示为连续的工作记录。</p></div>}
        {conversationItems.map((item) => {
          if (item.kind === "tool") return toolCard(item.tool);
          if (item.kind === "activity") return <article className="activity-turn" key={`activity:${item.event.seq}`}><span className="activity-mark" /><div><strong>{item.event.summary || item.event.type}</strong><small>{new Date(item.event.occurred_at).toLocaleTimeString()} · {statusLabels[item.event.status as ModelCallTranscript["status"]] || item.event.status || "记录"}</small></div></article>;
          const call = item.call;
          const hydrated = hydratedResponses[call.key];
          const presentedCall = hydrated ? {
            ...call,
            content: hydrated.content || call.content,
            reasoning: hydrated.reasoning || call.reasoning,
            model: hydrated.model || call.model,
            tool_call_count: hydrated.tool_call_count ?? call.tool_call_count,
          } : call;
          const transportActive = presentedCall.status === "waiting" || presentedCall.status === "streaming";
          const runActive = !runStatus || ["running", "queued", "resume_queued", "stop_requested"].includes(runStatus);
          const displayedCall = transportActive && !runActive ? { ...presentedCall, status: "interrupted" as const } : presentedCall;
          const activeCall = displayedCall.status === "waiting" || displayedCall.status === "streaming";
          return <article className={`model-turn call-status-${displayedCall.status}`} key={call.key}>
            <div className="turn-heading"><div><small>模型调用 · {stageLabel(call.stage)} · attempt {call.attempt}</small><h3>{call.model || "模型正在工作"}</h3></div><span className={`turn-status ${displayedCall.status}`}>{activeCall && <i />}{statusLabels[displayedCall.status]}</span></div>
            {(call.reasoning || activeCall) && <details className="reasoning-disclosure"><summary><span>{reasoningLabel(displayedCall)}</span><small>{call.reasoning ? `${call.reasoning.length.toLocaleString()} 字符` : "等待 Provider 返回"}</small></summary><pre>{call.reasoning || "Provider 暂未返回可见 reasoning。"}</pre></details>}
            <div className="model-response"><div><strong>模型回复</strong>{activeCall && <span className="streaming-label">实时生成中</span>}</div><pre>{call.content || responsePlaceholder(displayedCall)}</pre></div>
            <div className="turn-footer"><span>{new Date(call.occurred_at).toLocaleTimeString()}{call.duration_ms !== undefined ? ` · ${formatDuration(call.duration_ms)}` : ""}{call.usage?.completion_tokens !== undefined ? ` · ${call.usage.completion_tokens.toLocaleString()} 输出 tokens` : ""}</span><div className="turn-actions">{call.request_event?.payload_ref && <button onClick={() => void loadPayload(call.request_event!)}>查看模型输入</button>}{call.response_event?.payload_ref && <button onClick={() => void loadPayload(call.response_event!)}>查看完整响应</button>}</div></div>
          </article>;
        })}
      </div>}

      {tab === "request" && rawEventList(requestEvents)}
      {tab === "tool" && <div className="conversation-list tool-list">{toolCalls.length === 0 ? <div className="empty-state compact"><strong>还没有工具调用</strong><p>Method C 调用工具后会显示参数、状态与结果入口。</p></div> : toolCalls.map(toolCard)}</div>}
      {tab === "validation" && rawEventList(validationEvents)}
      {tab === "raw" && rawEventList(scopedEvents)}

      {active && <div className="payload-view"><div className="payload-head"><strong>事件 #{active.seq}</strong><span>{active.payload_ref ? `${active.payload_ref.kind} · ${active.payload_ref.bytes} bytes` : "事件元数据"}</span></div>{loading ? <p>正在读取完整 payload…</p> : <pre>{JSON.stringify(payload ?? active, null, 2)}</pre>}</div>}
    </aside>
  );
}
