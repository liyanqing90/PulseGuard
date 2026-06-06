import type { CheckPayload, CheckType } from "./types";

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

export const defaultApiAssertions = [
  { id: "status-200", type: "status_code", enabled: true, expected_status: 200 },
  { id: "duration-1000", type: "response_time", enabled: true, max_ms: 1000 }
];

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
    tags: ""
  };
}
