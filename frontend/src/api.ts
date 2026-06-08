import type {
  AlertPreview,
  ApiInspectPayload,
  ApiInspectResult,
  Check,
  CheckPayload,
  CheckType,
  NotificationStatus,
  Overview,
  Run,
  RunStatus,
  RuntimeStatus,
  SettingsValues,
  UiInspectPayload,
  UiInspectResult
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init
  });
  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    try {
      const data = await response.json();
      message = formatErrorDetail(data.detail, message);
    } catch {
      // keep default message
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

const FIELD_LABELS: Record<string, string> = {
  name: "任务名称",
  type: "任务类型",
  enabled: "启用状态",
  interval_seconds: "执行频率",
  timeout_ms: "超时时间",
  entry_url: "目标 URL",
  viewport_mode: "页面模式",
  method: "Method",
  headers_json: "Headers",
  body: "Body",
  assertions_json: "校验项",
  setup_script: "前置脚本",
  script: "Python 脚本",
  tags: "标签",
  notification_channels: "通知渠道",
  alert_cooldown_minutes: "告警冷却时间",
  alert_detail_base_url: "告警详情链接前缀",
  max_queue_size: "执行队列容量",
  max_ui_concurrency: "最大 UI 并发数",
  browser_viewport: "浏览器 Viewport"
};

function formatErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map(formatValidationItem).filter(Boolean);
    return messages.length ? Array.from(new Set(messages)).join("；") : fallback;
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return fallback;
}

function formatValidationItem(item: unknown): string {
  if (!item || typeof item !== "object") return "";
  const error = item as { loc?: unknown; msg?: unknown; type?: unknown };
  const label = fieldLabel(error.loc);
  const text = validationText(error);
  if (label && text.startsWith(label)) return text;
  if (label && /^(不能为空|过长|过短|必须|不能|格式|低于|超过|选项)/.test(text)) return `${label}${text}`;
  return label ? `${label}：${text}` : text;
}

function fieldLabel(loc: unknown): string {
  if (!Array.isArray(loc)) return "";
  const keys = loc.map(String).filter((item) => !["body", "query", "path"].includes(item) && !/^\d+$/.test(item));
  const key = keys[keys.length - 1];
  return key ? FIELD_LABELS[key] || "" : "";
}

function validationText(error: { msg?: unknown; type?: unknown }): string {
  const type = String(error.type || "");
  const message = typeof error.msg === "string" ? error.msg.replace(/^Value error,\s*/, "").trim() : "";
  if (type === "missing" || type === "string_too_short" || type === "too_short") return "不能为空";
  if (type === "string_too_long" || type === "too_long") return "过长";
  if (["int_parsing", "int_type", "float_parsing", "float_type"].includes(type)) return "必须是数字";
  if (["bool_type", "bool_parsing"].includes(type)) return "必须是布尔值";
  if (["literal_error", "enum"].includes(type)) return "选项无效";
  if (["greater_than_equal", "greater_than"].includes(type)) return "低于允许范围";
  if (["less_than_equal", "less_than"].includes(type)) return "超过允许范围";
  return message || "格式不正确";
}

export const api = {
  overview: () => request<Overview>("/api/overview"),
  runtime: () => request<RuntimeStatus>("/api/runtime"),
  checks: (type: CheckType) => request<Check[]>(`/api/checks?type=${type}`),
  check: (id: number) => request<Check>(`/api/checks/${id}`),
  createCheck: (payload: CheckPayload) =>
    request<Check>("/api/checks", { method: "POST", body: JSON.stringify(payload) }),
  updateCheck: (id: number, payload: CheckPayload) =>
    request<Check>(`/api/checks/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteCheck: (id: number) => request<{ ok: boolean }>(`/api/checks/${id}`, { method: "DELETE" }),
  enableCheck: (id: number) => request<Check>(`/api/checks/${id}/enable`, { method: "POST" }),
  disableCheck: (id: number) => request<Check>(`/api/checks/${id}/disable`, { method: "POST" }),
  runCheck: (id: number) => request<Run>(`/api/checks/${id}/run`, { method: "POST" }),
  debugCheck: (payload: CheckPayload) =>
    request<Run>("/api/checks/debug", { method: "POST", body: JSON.stringify(payload) }),
  inspectApi: (payload: ApiInspectPayload) =>
    request<ApiInspectResult>("/api/checks/inspect-api", { method: "POST", body: JSON.stringify(payload) }),
  inspectUi: (payload: UiInspectPayload) =>
    request<UiInspectResult>("/api/checks/inspect-ui", { method: "POST", body: JSON.stringify(payload) }),
  runAll: (type: CheckType) => request<{ runs: Run[] }>(`/api/checks/run-all?type=${type}`, { method: "POST" }),
  runs: (params: {
    type?: CheckType | "";
    status?: RunStatus | "failed" | "";
    notification_status?: NotificationStatus | "";
    q?: string;
    check_id?: string | null;
    start?: string;
    end?: string;
  }) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value) query.set(key, value);
    });
    return request<Run[]>(`/api/runs?${query.toString()}`);
  },
  run: (id: number) => request<Run>(`/api/runs/${id}`),
  rerun: (id: number) => request<Run>(`/api/runs/${id}/rerun`, { method: "POST" }),
  settings: () => request<SettingsValues>("/api/settings"),
  updateSettings: (values: Partial<SettingsValues>) =>
    request<SettingsValues>("/api/settings", { method: "PUT", body: JSON.stringify({ values }) }),
  alertPreview: (values: Partial<SettingsValues>) =>
    request<AlertPreview>("/api/settings/alert-preview", { method: "POST", body: JSON.stringify({ values }) }),
  testAlert: (values: Partial<SettingsValues>) =>
    request<{ ok: boolean; message: string }>("/api/settings/test-alert", { method: "POST", body: JSON.stringify({ values }) })
};
