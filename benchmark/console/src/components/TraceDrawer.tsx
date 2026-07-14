import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { TraceEvent } from "../types";
import type { GraphSelection } from "./WorkflowGraph";

type Tab = "all" | "request" | "response" | "reasoning" | "tool" | "validation";

const tabLabels: Record<Tab, string> = { all: "全部", request: "模型输入", response: "模型输出", reasoning: "可见推理", tool: "工具", validation: "校验 / 重试" };

function tabFor(event: TraceEvent): Tab {
  if (event.data?.channel === "reasoning") return "reasoning";
  if (event.data?.channel === "tool_call") return "tool";
  if (event.type.includes("request")) return "request";
  if (event.type.includes("reasoning")) return "reasoning";
  if (event.type.includes("tool")) return "tool";
  if (event.type.includes("valid") || event.type.includes("retry") || event.type.includes("repair") || event.type.includes("failed") || event.type.includes("interrupted")) return "validation";
  return "response";
}

function eventText(event: TraceEvent) {
  const delta = event.data?.delta;
  if (typeof delta === "string") return delta;
  const text = event.data?.text;
  if (typeof text === "string") return text;
  return event.summary || event.type;
}

function stageMatches(id: string, event: TraceEvent) {
  const aliases: Record<string, string[]> = {
    batch: ["batch", "rebatch"], candidate: ["cand-"], validate: ["valid"],
    context: ["context"], scaffold: ["scaffold"], plan: ["plan"],
    review: ["review"], final: ["final"],
  };
  return (aliases[id] || [id]).some((value) => event.stage?.startsWith(value) || event.node_id?.startsWith(value));
}

export function TraceDrawer({
  campaignId,
  runId,
  selection,
  paperId,
  events,
  onClose,
}: {
  campaignId: string;
  runId: string;
  selection: GraphSelection;
  paperId?: string;
  events: TraceEvent[];
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("all");
  const [active, setActive] = useState<TraceEvent | null>(null);
  const [payload, setPayload] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const filtered = useMemo(() => events.filter((event) => {
    if (paperId && event.paper_id !== paperId) return false;
    if (selection.kind === "node") {
      if (selection.id.startsWith("paper:")) return event.paper_id === selection.id.slice(6);
      if (!stageMatches(selection.id, event) && !(selection.id === "final" && event.type === "paper.completed")) return false;
    } else if (selection.source && selection.target) {
      const source = selection.source.replace("paper:", "");
      const target = selection.target.replace("paper:", "");
      const paperEdge = selection.source.startsWith("paper:") || selection.target.startsWith("paper:");
      const direct = event.source_node_id?.includes(source) && event.target_node_id?.includes(target);
      const adjacentStage = stageMatches(source, event) || stageMatches(target, event);
      const adjacentPaper = event.paper_id === source || event.paper_id === target;
      if (!direct && !(paperEdge ? adjacentPaper : adjacentStage)) return false;
    }
    return tab === "all" || tabFor(event) === tab;
  }), [events, paperId, selection, tab]);

  const latestSeq = filtered.at(-1)?.seq;
  useEffect(() => { setActive(filtered.at(-1) || null); setPayload(null); }, [selection.id, tab, latestSeq]);

  async function loadPayload(event: TraceEvent) {
    setActive(event); setPayload(null);
    if (!event.payload_ref) return;
    setLoading(true);
    try { setPayload((await api.blob(campaignId, runId, event.payload_ref.sha256)).payload); }
    catch (reason) { setPayload({ error: (reason as Error).message }); }
    finally { setLoading(false); }
  }

  return (
    <aside className="trace-drawer" aria-label="运行事件详情">
      <div className="drawer-head"><div><p className="eyebrow">{selection.kind === "node" ? "节点详情" : "边上的信息流"}</p><h2>{selection.label}</h2>{paperId && <small>{paperId}</small>}</div><button className="icon-button" aria-label="关闭详情" onClick={onClose}>×</button></div>
      <div className="drawer-notice">这里只显示 Provider 返回的可见 reasoning、模型内容、工具调用与校验记录；不会展示或推测隐藏思考。</div>
      <div className="drawer-tabs" role="tablist">{(Object.keys(tabLabels) as Tab[]).map((value) => <button role="tab" aria-selected={tab === value} className={tab === value ? "active" : ""} onClick={() => setTab(value)} key={value}>{tabLabels[value]}</button>)}</div>
      <div className="trace-list">
        {filtered.length === 0 && <div className="empty-state compact"><strong>还没有匹配事件</strong><p>节点开始工作后，事件会实时出现在这里。</p></div>}
        {filtered.slice(-120).reverse().map((event) => <button className={`trace-event ${active?.seq === event.seq ? "active" : ""}`} key={event.seq} onClick={() => void loadPayload(event)}><span className="trace-dot" /><span><strong>{event.type}</strong><small>{new Date(event.occurred_at).toLocaleTimeString()} · {event.stage || "run"}{event.attempt ? ` · attempt ${event.attempt}` : ""}</small><em>{eventText(event)}</em></span></button>)}
      </div>
      {active && <div className="payload-view"><div className="payload-head"><strong>事件 #{active.seq}</strong><span>{active.payload_ref ? `${active.payload_ref.kind} · ${active.payload_ref.bytes} bytes` : "事件元数据"}</span></div>{loading ? <p>正在读取完整 payload…</p> : <pre>{JSON.stringify(payload ?? active, null, 2)}</pre>}</div>}
    </aside>
  );
}
