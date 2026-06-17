import { serializeApiAssertions } from "./apiAssertions";
import type { ApiAssertion, CheckPayload, CheckType, UiAssertion } from "./types";
import { serializeUiAssertions } from "./uiAssertions";

export const uiScriptTemplate = `async def check(ctx):
    page = await ctx.new_page()

    await page.goto(ctx.entry_url, wait_until="networkidle")

    await ctx.expect_text(page, "Example Domain")
    await ctx.expect_hidden(page, "text=系统异常")
`;

export const uiSetupScriptTemplate = `async def setup(ctx, page):
    ctx.log("前置脚本开始")

    # 在这里打开登录页并完成登录、Cookie 准备或其他一次性页面操作。
    # await page.goto("https://example.com/login", wait_until="domcontentloaded")
`;

export const apiScriptTemplate = `async def check(ctx):
    resp = await ctx.request()

    ctx.assert_status(resp, 200)

    data = resp.json()

    ctx.assert_json_schema(data, {
        "type": "object",
        "required": ["userId", "id", "title", "completed"],
        "properties": {
            "userId": {"type": "integer"},
            "id": {"type": "integer"},
            "title": {"type": "string"},
            "completed": {"type": "boolean"}
        }
    })

    ctx.save_response(resp)
`;

export const heartbeatScriptTemplate = `async def check(ctx):
    heartbeat = ctx.expect_heartbeat("nightly-job", max_age_seconds=900)
    ctx.log(f"最近心跳：{heartbeat['received_at']}")
`;

export const tlsScriptTemplate = `async def check(ctx):
    info = await ctx.tls_certificate(ctx.entry_url, 443, warn_days=14)
    ctx.log(f"证书到期时间：{info['expires_at']}")
`;

export const tcpScriptTemplate = `async def check(ctx):
    result = await ctx.tcp_connect(ctx.entry_url, 443)
    ctx.log(f"TCP 连接耗时：{result['duration_ms']}ms")
`;

export const dnsScriptTemplate = `async def check(ctx):
    result = await ctx.dns_resolve(ctx.entry_url)
    ctx.log(f"解析地址：{', '.join(result['addresses'])}")
`;

export const httpKeywordScriptTemplate = `async def check(ctx):
    resp = await ctx.request()
    ctx.assert_status(resp, 200)
    ctx.assert_body_contains(resp, "关键字")
`;

export const httpRedirectScriptTemplate = `async def check(ctx):
    resp = await ctx.request()
    ctx.assert_redirect_occurred(resp)
    ctx.assert_url_contains(resp, "/login")
`;

export const httpAssetScriptTemplate = `async def check(ctx):
    resp = await ctx.request()
    ctx.assert_status(resp, 200)
    if len(resp.content) == 0:
        ctx.fail("静态资源内容为空")
`;

export const defaultApiAssertions: ApiAssertion[] = [
  { id: "status-200", type: "status_code", enabled: true, expected_status: 200 },
  { id: "duration-1000", type: "response_time", enabled: true, max_ms: 1000 }
];

export interface CheckTemplate {
  id: string;
  type: CheckType;
  label: string;
  payload: Partial<CheckPayload>;
}

const healthApiAssertions: ApiAssertion[] = [
  { id: "template-health-status", type: "status_code", enabled: true, expected_status: 200 },
  { id: "template-health-duration", type: "response_time", enabled: true, max_ms: 1000 }
];

const listApiAssertions: ApiAssertion[] = [
  { id: "template-list-status", type: "status_code", enabled: true, expected_status: 200 },
  { id: "template-list-duration", type: "response_time", enabled: true, max_ms: 1500 },
  { id: "template-list-data-exists", type: "json_path_exists", enabled: true, path: "$.data" },
  { id: "template-list-data-type", type: "json_path_type", enabled: true, path: "$.data", expected_type: "array" },
  { id: "template-list-data-length", type: "json_path_length", enabled: true, path: "$.data", operator: "gte", expected_length: 0 }
];

const loginUiAssertions: UiAssertion[] = [
  { id: "template-login-not-blank", type: "page_not_blank", enabled: true },
  { id: "template-login-console", type: "console_error_absent", enabled: true },
  { id: "template-login-url", type: "url_contains", enabled: true, expected_text: "/login" }
];

const dashboardUiAssertions: UiAssertion[] = [
  { id: "template-dashboard-not-blank", type: "page_not_blank", enabled: true },
  { id: "template-dashboard-console", type: "console_error_absent", enabled: true },
  { id: "template-dashboard-error-absent", type: "text_absent", enabled: true, expected_text: "系统异常" }
];

export const checkTemplates: CheckTemplate[] = [
  {
    id: "api-health",
    type: "api",
    label: "健康接口",
    payload: {
      name: "健康接口",
      entry_url: "${BASE_URL}/health",
      method: "GET",
      tags: "health smoke",
      interval_seconds: 60,
      timeout_ms: 5000,
      assertions_json: serializeApiAssertions(healthApiAssertions)
    }
  },
  {
    id: "api-list",
    type: "api",
    label: "列表接口",
    payload: {
      name: "列表接口",
      entry_url: "${BASE_URL}/api/items",
      method: "GET",
      tags: "api list",
      interval_seconds: 300,
      timeout_ms: 10000,
      assertions_json: serializeApiAssertions(listApiAssertions)
    }
  },
  {
    id: "api-heartbeat",
    type: "api",
    label: "被动心跳",
    payload: {
      name: "被动心跳",
      entry_url: "heartbeat:nightly-job",
      method: "GET",
      tags: "heartbeat",
      interval_seconds: 300,
      timeout_ms: 5000,
      script: heartbeatScriptTemplate
    }
  },
  {
    id: "api-tls",
    type: "api",
    label: "TLS 证书",
    payload: {
      name: "TLS 证书",
      entry_url: "${BASE_HOST}:443",
      method: "GET",
      tags: "tls cert",
      interval_seconds: 86400,
      timeout_ms: 10000,
      script: tlsScriptTemplate
    }
  },
  {
    id: "api-tcp",
    type: "api",
    label: "TCP 端口",
    payload: {
      name: "TCP 端口",
      entry_url: "${BASE_HOST}:443",
      method: "GET",
      tags: "tcp port",
      interval_seconds: 300,
      timeout_ms: 5000,
      script: tcpScriptTemplate
    }
  },
  {
    id: "api-dns",
    type: "api",
    label: "DNS 解析",
    payload: {
      name: "DNS 解析",
      entry_url: "${BASE_HOST}",
      method: "GET",
      tags: "dns",
      interval_seconds: 300,
      timeout_ms: 5000,
      script: dnsScriptTemplate
    }
  },
  {
    id: "api-keyword",
    type: "api",
    label: "HTTP 关键字",
    payload: {
      name: "HTTP 关键字",
      entry_url: "${BASE_URL}",
      method: "GET",
      tags: "http keyword",
      interval_seconds: 300,
      timeout_ms: 10000,
      script: httpKeywordScriptTemplate
    }
  },
  {
    id: "api-redirect",
    type: "api",
    label: "HTTP 跳转",
    payload: {
      name: "HTTP 跳转",
      entry_url: "${BASE_URL}/login",
      method: "GET",
      tags: "http redirect",
      interval_seconds: 300,
      timeout_ms: 10000,
      script: httpRedirectScriptTemplate
    }
  },
  {
    id: "api-asset",
    type: "api",
    label: "静态资源",
    payload: {
      name: "静态资源",
      entry_url: "${BASE_URL}/assets/app.css",
      method: "GET",
      tags: "http asset",
      interval_seconds: 300,
      timeout_ms: 10000,
      script: httpAssetScriptTemplate
    }
  },
  {
    id: "ui-login",
    type: "ui",
    label: "登录页",
    payload: {
      name: "登录页",
      entry_url: "${BASE_URL}/login",
      viewport_mode: "web",
      tags: "ui login",
      interval_seconds: 300,
      timeout_ms: 15000,
      assertions_json: serializeUiAssertions(loginUiAssertions)
    }
  },
  {
    id: "ui-dashboard",
    type: "ui",
    label: "后台首页",
    payload: {
      name: "后台首页",
      entry_url: "${BASE_URL}/dashboard",
      viewport_mode: "web",
      tags: "ui dashboard",
      interval_seconds: 300,
      timeout_ms: 15000,
      setup_script: uiSetupScriptTemplate,
      assertions_json: serializeUiAssertions(dashboardUiAssertions)
    }
  }
];

export function checkTemplatesForType(type: CheckType): CheckTemplate[] {
  return checkTemplates.filter((template) => template.type === type);
}

export function checkFromTemplate(type: CheckType, templateId: string): CheckPayload | null {
  const template = checkTemplates.find((item) => item.type === type && item.id === templateId);
  if (!template) return null;
  return {
    ...blankCheck(type),
    ...template.payload,
    type
  };
}

export function blankCheck(type: CheckType): CheckPayload {
  return {
    name: "",
    type,
    enabled: true,
    interval_seconds: 300,
    timeout_ms: type === "ui" ? 15000 : 10000,
    entry_url: "",
    viewport_mode: "web",
    method: type === "api" ? "GET" : "",
    headers_json: "{}",
    body: "",
    assertions_json: "[]",
    setup_script: "",
    script: "",
    tags: "",
    alert_policy_json: "{}",
    runner_selection_mode: "selected_parallel",
    runner_ids: ["local"],
    browser_selection_mode: "selected_parallel",
    browser_types: type === "ui" ? ["chromium"] : []
  };
}
