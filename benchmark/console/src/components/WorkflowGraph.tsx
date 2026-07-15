import { memo, useCallback, useEffect, useMemo, useRef } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import type { Method, RunStatus, TraceEvent } from "../types";

export interface GraphSelection {
  kind: "node" | "edge";
  id: string;
  label: string;
  source?: string;
  target?: string;
}

const statusClass = (status: string) => `graph-node status-${status || "unknown"}`;

function latestStageStatus(events: TraceEvent[], ids: string[]) {
  const matching = events
    .filter((event) => ids.some((id) => event.node_id === id || event.stage === id || event.stage?.startsWith(id)))
    .sort((left, right) => right.seq - left.seq);
  for (const event of matching) {
    if (event.status === "failed" || event.type.includes("failed") || event.type.includes("exhausted")) return "failed";
    if (["completed", "passed", "ok", "ok_with_cjk_warnings"].includes(event.status || "") || event.type.includes("completed") || event.type === "context.packed") return "completed";
    if (["running", "retrying"].includes(event.status || "") || event.type.includes("delta") || event.type.includes("started")) return "running";
  }
  return "queued";
}

function overviewPaperStatus(paper: string, rawStatus: string, runStatus: RunStatus, events: TraceEvent[]) {
  const paperEvents = events.filter((event) => event.paper_id === paper).sort((left, right) => right.seq - left.seq);
  const completed = paperEvents.find((event) => event.type === "paper.completed");
  const success = new Set(["ok", "ok_with_cjk_warnings", "completed", "sealed"]);
  if (completed) return success.has(completed.status || rawStatus) ? "completed" : "failed";
  if (paperEvents.some((event) => event.status === "failed" || event.type.includes("failed") || event.type.includes("exhausted"))) return "failed";
  if (paperEvents.length > 0) return ["failed", "stopped"].includes(runStatus) ? runStatus : "running";
  if (success.has(rawStatus)) return "completed";
  if (rawStatus && !["missing", "waiting", "queued", "unknown"].includes(rawStatus)) return "failed";
  return "queued";
}

function overviewStatusLabel(status: string, rawStatus: string) {
  if (status === "running") return "运行中";
  if (status === "queued") return "等待调度";
  if (status === "completed") return "已完成";
  if (status === "stopped") return "已停止";
  if (status === "failed") {
    return rawStatus && !["missing", "waiting", "queued", "unknown"].includes(rawStatus)
      ? `失败 · ${rawStatus}`
      : "失败";
  }
  return "等待状态";
}

export const OverviewGraph = memo(function OverviewGraph({
  papers,
  paperStatuses,
  runStatus,
  events = [],
  onSelect,
  viewKey = "overview",
}: {
  papers: string[];
  paperStatuses: Record<string, string>;
  runStatus: RunStatus;
  events?: TraceEvent[];
  onSelect: (selection: GraphSelection) => void;
  viewKey?: string;
}) {
  const { nodes, edges } = useMemo(() => {
    const rows = papers.map((paper, index) => ({ paper, status: overviewPaperStatus(paper, paperStatuses[paper] || "", runStatus, events), x: 290 + (index % 5) * 180, y: 70 + Math.floor(index / 5) * 145 }));
    const nextNodes: Node[] = [
      { id: "scheduler", position: { x: 20, y: 145 }, data: { label: <><small>实验调度</small><strong>Scheduler</strong></> }, className: statusClass(runStatus) },
      ...rows.map(({ paper, status, x, y }, index) => ({ id: `paper:${paper}`, position: { x, y }, data: { label: <><small>论文 {String(index + 1).padStart(2, "0")}</small><strong>{paper}</strong><em>{overviewStatusLabel(status, paperStatuses[paper] || "")}</em></> }, className: statusClass(status) })),
      { id: "collector", position: { x: 1210, y: 145 }, data: { label: <><small>交付汇聚</small><strong>Results</strong></> }, className: statusClass(runStatus === "completed" || runStatus === "sealed" ? "completed" : "queued") },
    ];
    const nextEdges: Edge[] = rows.flatMap(({ paper, status }, index) => [
      { id: `dispatch:${paper}`, source: "scheduler", target: `paper:${paper}`, label: index === 0 ? "分发上下文" : undefined, markerEnd: { type: MarkerType.ArrowClosed }, animated: status === "running" },
      { id: `collect:${paper}`, source: `paper:${paper}`, target: "collector", label: index === 0 ? "提交结果" : undefined, markerEnd: { type: MarkerType.ArrowClosed }, animated: status === "completed" },
    ]);
    return { nodes: nextNodes, edges: nextEdges };
  }, [events, paperStatuses, papers, runStatus]);
  return <Graph nodes={nodes} edges={edges} onSelect={onSelect} viewKey={viewKey} />;
});

const flows: Record<Method, { id: string; label: string; aliases: string[] }[]> = {
  B: [
    { id: "context", label: "打包上下文", aliases: ["context"] },
    { id: "scaffold", label: "候选骨架", aliases: ["scaffold"] },
    { id: "batch", label: "分批提取", aliases: ["batch", "rebatch"] },
    { id: "validate", label: "结构校验", aliases: ["validate", "validation"] },
    { id: "review", label: "独立复核", aliases: ["review"] },
    { id: "final", label: "最终交付", aliases: ["final"] },
  ],
  C: [
    { id: "context", label: "打包上下文", aliases: ["context"] },
    { id: "plan", label: "规划候选", aliases: ["plan"] },
    { id: "candidate", label: "候选 ReAct", aliases: ["cand-"] },
    { id: "validate", label: "结构校验", aliases: ["validate", "validation"] },
    { id: "review", label: "独立复核", aliases: ["review"] },
    { id: "final", label: "最终交付", aliases: ["final"] },
  ],
};

export const PaperGraph = memo(function PaperGraph({ method, events, onSelect, viewKey = `paper:${method}` }: { method: Method; events: TraceEvent[]; onSelect: (selection: GraphSelection) => void; viewKey?: string }) {
  const { nodes, edges } = useMemo(() => paperGraphModel(method, events), [events, method]);
  return <Graph nodes={nodes} edges={edges} onSelect={onSelect} viewKey={viewKey} />;
});

export function paperGraphModel(method: Method, events: TraceEvent[]) {
  const stages = flows[method];
  const stageStatuses = Object.fromEntries(stages.map((stage) => [stage.id, latestStageStatus(events, stage.aliases)]));
  const nodes: Node[] = stages.map((stage, index) => {
    const status = stageStatuses[stage.id];
    const activity = events.filter((event) => stage.aliases.some((alias) => event.stage?.startsWith(alias) || event.node_id?.startsWith(alias))).length;
    return { id: stage.id, position: { x: 70 + index * 205, y: index % 2 ? 210 : 85 }, data: { label: <><small>{String(index + 1).padStart(2, "0")}</small><strong>{stage.label}</strong><em>{status === "running" ? "正在工作" : activity ? `${activity} 条事件` : "等待"}</em></> }, className: statusClass(status) };
  });
  const edges: Edge[] = stages.slice(0, -1).map((stage, index) => {
    const target = stages[index + 1];
    const directCommunication = events.some((event) =>
      stage.aliases.some((value) => event.source_node_id?.startsWith(value)) && target.aliases.some((value) => event.target_node_id?.startsWith(value)),
    );
    return { id: `${stage.id}->${target.id}`, source: stage.id, target: target.id, label: index === 1 ? "信息包" : undefined, markerEnd: { type: MarkerType.ArrowClosed }, animated: directCommunication || stageStatuses[target.id] === "running" };
  });
  for (const stage of stages) {
    const retried = events.some((event) => stage.aliases.some((alias) => event.stage?.startsWith(alias)) && (event.type.includes("retry") || (event.attempt || 1) > 1));
    if (retried) edges.push({ id: `retry:${stage.id}`, source: stage.id, target: stage.id, label: "调用重试", type: "smoothstep", animated: true, markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: "#e39739" } });
  }
  const repairTarget = method === "B" ? "batch" : "candidate";
  if (events.some((event) => event.type === "validation.completed" && event.status === "needs_repair")) {
    edges.push({ id: `repair:validate->${repairTarget}`, source: "validate", target: repairTarget, label: "校验回修", type: "smoothstep", animated: stageStatuses[repairTarget] === "running", markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: "#e39739" } });
  }
  const latestReview = Math.max(0, ...events.filter((event) => event.stage?.startsWith("review")).map((event) => event.seq));
  if (latestReview && events.some((event) => event.seq > latestReview && flows[method].find((stage) => stage.id === repairTarget)?.aliases.some((alias) => event.stage?.startsWith(alias)))) {
    edges.push({ id: `revision:review->${repairTarget}`, source: "review", target: repairTarget, label: "复核修订", type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: "#8f72db" } });
  }
  return { nodes, edges };
}

function Graph({ nodes, edges, onSelect, viewKey }: { nodes: Node[]; edges: Edge[]; onSelect: (selection: GraphSelection) => void; viewKey: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  const frameRef = useRef(0);
  const nodeKey = nodes.map((node) => node.id).join("|");
  const refit = useCallback(() => {
    window.cancelAnimationFrame(frameRef.current);
    frameRef.current = window.requestAnimationFrame(() => {
      if (instanceRef.current) void instanceRef.current.fitView({ padding: 0.18, minZoom: 0.45, maxZoom: 1.5, duration: 0 });
    });
  }, []);

  useEffect(() => {
    refit();
  }, [nodeKey, refit, viewKey]);

  useEffect(() => {
    if (!containerRef.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(refit);
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(frameRef.current);
    };
  }, [refit]);

  return (
    <div className="flow-canvas" aria-label="工作流图" ref={containerRef}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.18, minZoom: 0.45, maxZoom: 1.5 }}
        minZoom={0.45}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        onInit={(instance) => { instanceRef.current = instance; refit(); }}
        onNodeClick={(_, node) => onSelect({ kind: "node", id: node.id, label: typeof node.data.label === "string" ? node.data.label : node.id })}
        onEdgeClick={(_, edge) => onSelect({ kind: "edge", id: edge.id, label: String(edge.label || "信息交互"), source: edge.source, target: edge.target })}
      >
        <Background color="#354153" gap={28} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
