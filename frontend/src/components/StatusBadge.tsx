import { Tag } from "antd";
import type { Check, RunStatus } from "../types";
import { runStatusLabel, runStatusTagColor, taskStatus, taskStatusLabel, taskStatusTagColor } from "../utils";

export function TaskStatusBadge({ check }: { check: Check }) {
  const status = taskStatus(check);
  return <Tag color={taskStatusTagColor(status)}>{taskStatusLabel(status)}</Tag>;
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <Tag color={runStatusTagColor(status)}>{runStatusLabel(status)}</Tag>;
}
