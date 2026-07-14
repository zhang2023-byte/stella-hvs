import type { RunStatus } from "../types";

const labels: Record<string, string> = {
  queued: "排队中",
  resume_queued: "等待恢复",
  paused: "已暂停",
  running: "运行中",
  stop_requested: "正在停止",
  stopped: "已停止",
  partial: "部分完成",
  failed: "失败",
  completed: "已完成",
  sealed: "已封存",
  unknown: "未知",
  needs_review: "需要复核",
  not_started: "未开始",
};

export function StatusPill({ status }: { status: RunStatus | string }) {
  return <span className={`status-pill status-${status}`}>{labels[status] || status}</span>;
}
