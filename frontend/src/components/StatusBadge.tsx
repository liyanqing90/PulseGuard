import { Tag } from "antd";
import type { Check, RunStatus, TaskSurfaceStatus } from "../types";
import { runStatusLabel, taskStatus, taskStatusLabel } from "../utils";

export function TaskStatusBadge({ check }: { check: Check }) {
  const status = taskStatus(check);
  return <Tag color={taskColor(status)}>{taskStatusLabel(status)}</Tag>;
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <Tag color={runColor(status)}>{runStatusLabel(status)}</Tag>;
}

function taskColor(status: TaskSurfaceStatus): string {
  if (status === "ok") return "success";
  if (status === "failed") return "error";
  if (status === "disabled") return "default";
  return "processing";
}

function runColor(status: RunStatus): string {
  if (status === "ok") return "success";
  if (status === "failed" || status === "timeout") return "error";
  if (status === "running" || status === "pending") return "processing";
  return "default";
}
