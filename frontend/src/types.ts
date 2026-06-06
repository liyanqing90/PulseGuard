export type CheckType = "ui" | "api";
export type ViewportMode = "web" | "h5";
export type RunStatus = "pending" | "running" | "ok" | "failed" | "timeout" | "skipped";
export type NotificationStatus = "disabled" | "not_required" | "suppressed" | "sent" | "failed";
export type TaskSurfaceStatus = "ok" | "failed" | "never" | "disabled";
export type WebhookType = "feishu" | "wecom" | "dingtalk";
export type ApiAssertionType =
  | "status_code"
  | "response_time"
  | "json_path_exists"
  | "json_path_equals"
  | "json_path_not_empty"
  | "json_path_contains"
  | "json_path_type"
  | "json_path_length";
export type ApiJsonValueType = "string" | "number" | "boolean" | "object" | "array" | "null";
export type ApiLengthOperator = "eq" | "ne" | "gt" | "gte" | "lt" | "lte";
export type UiAssertionType =
  | "element_visible"
  | "element_hidden"
  | "element_not_empty"
  | "page_not_blank"
  | "text_present"
  | "text_absent"
  | "title_contains"
  | "url_contains"
  | "console_error_absent"
  | "element_count";
export type UiCountOperator = ApiLengthOperator;

export interface ApiAssertion {
  id: string;
  type: ApiAssertionType;
  enabled: boolean;
  expected_status?: number;
  max_ms?: number;
  path?: string;
  expected_value?: string;
  expected_type?: ApiJsonValueType;
  operator?: ApiLengthOperator;
  expected_length?: number;
}

export interface UiAssertion {
  id: string;
  type: UiAssertionType;
  enabled: boolean;
  selector?: string;
  expected_text?: string;
  operator?: UiCountOperator;
  expected_count?: number;
}

export interface ApiJsonPathOption {
  path: string;
  type: string;
  preview: string;
  length?: number | null;
}

export interface ApiInspectPayload {
  type: "api";
  entry_url: string;
  method: string;
  headers_json: string;
  body: string;
  timeout_ms: number;
}

export interface ApiInspectResult {
  status_code: number;
  duration_ms: number;
  headers: Record<string, string>;
  body: string;
  json_valid: boolean;
  json_paths: ApiJsonPathOption[];
}

export interface UiInspectPayload {
  type: "ui";
  entry_url: string;
  timeout_ms: number;
  viewport_mode: "web" | "h5";
  viewport_width: number;
  viewport_height: number;
}

export interface UiElementCandidate {
  name?: string;
  selector: string;
  selector_type?: string;
  stability?: "high" | "medium" | "low";
  score?: number;
  text: string;
  tag: string;
  role: string;
  kind?: "interactive" | "media" | "text" | "component" | "structure";
  box: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
}

export interface UiInspectResult {
  title: string;
  url: string;
  viewport: {
    width: number;
    height: number;
  };
  page_size?: {
    width: number;
    height: number;
  };
  candidates: UiElementCandidate[];
  screenshot: string;
}

export interface Check {
  id: number;
  name: string;
  type: CheckType;
  enabled: boolean;
  interval_seconds: number;
  timeout_ms: number;
  entry_url: string;
  viewport_mode: ViewportMode;
  method: string;
  headers_json: string;
  body: string;
  assertions_json: string;
  setup_script: string;
  script: string;
  tags: string;
  created_at: string;
  updated_at: string;
  current_status?: "ok" | "failed" | null;
  consecutive_failures: number;
  last_success_at?: string | null;
  last_failed_at?: string | null;
  last_run_at?: string | null;
  last_run_id?: number | null;
  last_error?: string | null;
  last_duration_ms?: number | null;
}

export interface Run {
  id: number;
  check_id: number;
  check_name: string;
  check_type: CheckType;
  status: RunStatus;
  started_at: string;
  finished_at?: string | null;
  duration_ms?: number | null;
  error_message?: string | null;
  error_stack?: string | null;
  logs?: string | null;
  screenshot_path?: string | null;
  trace_path?: string | null;
  response_path?: string | null;
  request_snapshot?: string | null;
  response_snapshot?: string | null;
  notification_status?: NotificationStatus | null;
  notification_channel?: "feishu" | "wecom" | "dingtalk" | string | null;
  notification_error?: string | null;
  notification_sent_at?: string | null;
  created_at: string;
  consecutive_failures?: number;
}

export interface Overview {
  ui_count: number;
  api_count: number;
  failing_count: number;
  today_runs: number;
  latest_run: Run | null;
  latest_recovered: { name: string; type: CheckType; last_success_at: string } | null;
  recent_failures: Run[];
}

export interface SettingsValues {
  default_interval_seconds: number;
  default_ui_timeout_ms: number;
  default_api_timeout_ms: number;
  max_concurrency: number;
  max_task_runtime_seconds: number;
  alerts_enabled: boolean;
  alert_detail_base_url: string;
  notification_channels: NotificationChannel[];
  alert_cooldown_minutes: number;
  recovery_notification: boolean;
  browser_headless: boolean;
  browser_type: "chromium" | "firefox" | "webkit";
  browser_proxy: string;
  browser_viewport: string;
  run_retention_days: number;
  screenshot_retention_days: number;
  trace_retention_days: number;
  response_retention_days: number;
}

export interface NotificationChannel {
  id: string;
  name: string;
  type: WebhookType;
  enabled: boolean;
  webhook_url: string;
  dingtalk_secret?: string;
  dingtalk_secret_set?: boolean;
  dingtalk_secret_clear?: boolean;
}

export interface AlertPreview {
  channels: AlertPreviewChannel[];
  message_text: string;
}

export interface AlertPreviewChannel {
  id: string;
  name: string;
  type: WebhookType;
  enabled: boolean;
  target: {
    valid: boolean;
    origin: string;
    path: string;
    query_keys: string[];
    issues: string[];
  };
  signing_enabled: boolean;
  payload: unknown;
}

export type CheckPayload = Omit<
  Check,
  | "id"
  | "created_at"
  | "updated_at"
  | "current_status"
  | "consecutive_failures"
  | "last_success_at"
  | "last_failed_at"
  | "last_run_at"
  | "last_run_id"
  | "last_error"
>;
