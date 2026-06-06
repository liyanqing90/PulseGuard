import type { Check, CheckType, NotificationStatus, RunStatus, TaskSurfaceStatus } from "./types";

export function taskStatus(check: Check): TaskSurfaceStatus {
  if (!check.enabled) return "disabled";
  if (!check.current_status) return "never";
  return check.current_status;
}

export function taskStatusLabel(status: TaskSurfaceStatus): string {
  return {
    ok: "正常",
    failed: "失败",
    never: "未运行",
    disabled: "禁用"
  }[status];
}

export function runStatusLabel(status: RunStatus): string {
  return {
    pending: "等待中",
    running: "运行中",
    ok: "正常",
    failed: "失败",
    timeout: "超时",
    skipped: "已跳过"
  }[status];
}

export function runStatusTone(status: RunStatus): "ok" | "failed" | "neutral" | "running" {
  if (status === "ok") return "ok";
  if (status === "failed" || status === "timeout") return "failed";
  if (status === "running" || status === "pending") return "running";
  return "neutral";
}

export function notificationStatusMeta(status?: NotificationStatus | null): { label: string; color: string } {
  if (!status) {
    return { label: "未记录", color: "default" };
  }
  return (
    {
      disabled: { label: "未启用", color: "default" },
      not_required: { label: "无需告警", color: "default" },
      suppressed: { label: "未触发", color: "processing" },
      sent: { label: "已发送", color: "success" },
      failed: { label: "发送失败", color: "error" }
    } satisfies Record<NotificationStatus, { label: string; color: string }>
  )[status];
}

export function notificationChannelLabel(channel?: string | null, status?: NotificationStatus | null): string {
  if (status === "disabled" || status === "not_required") return "未使用";
  if (!channel) return "-";
  return (
    {
      feishu: "飞书",
      wecom: "企业微信",
      dingtalk: "钉钉"
    }[channel] || channel
  );
}

export function formatDate(value?: string | null): string {
  if (!value) return "未执行";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function formatDuration(value?: number | null): string {
  if (value === null || value === undefined) return "-";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

export function intervalLabel(seconds: number): string {
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds % 3600 === 0) return `${seconds / 3600} 小时`;
  if (seconds % 60 === 0) return `${seconds / 60} 分钟`;
  return `${seconds} 秒`;
}

export function artifactHref(path?: string | null): string | null {
  return path ? `/artifacts/${path.replace(/\\/g, "/")}` : null;
}

export function checkListPath(type: CheckType, checkId?: number | string | null): string {
  const basePath = type === "ui" ? "/ui-checks" : "/api-checks";
  return checkId ? `${basePath}?check_id=${encodeURIComponent(String(checkId))}` : basePath;
}

export function parseSnapshot(value?: string | null): unknown {
  if (!value) return null;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

export function compactUrl(value: string): string {
  if (value.length <= 72) return value;
  return `${value.slice(0, 42)}...${value.slice(-24)}`;
}
