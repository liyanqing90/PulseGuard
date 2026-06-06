import { Alert, Card, Collapse, Form, Input, InputNumber, Segmented, Select, Space, Switch, Tag } from "antd";
import { ArrowLeft, Play, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import {
  checkToPayload,
  detectBodyMode,
  normalizeCheckPayload,
  prepareCheckPayload,
  sameCheckPayload,
  type BodyEditorMode
} from "../checkPayload";
import { apiScriptTemplate } from "../defaults";
import { ApiAssertionsBuilder } from "../components/ApiAssertionsBuilder";
import { CodeEditorPanel } from "../components/CodeEditorPanel";
import { AppButton as Button } from "../components/common/AppButton";
import { RunResultPanel } from "../components/RunResultPanel";
import { UiAssertionsBuilder } from "../components/UiAssertionsBuilder";
import { UiScriptSections } from "../components/UiScriptSections";
import { ViewportModeControl } from "../components/ViewportModeControl";
import type { Check, CheckPayload, Run } from "../types";

export function DebugPage() {
  const { type, checkId } = useParams();
  const checkType = type === "api" ? "api" : "ui";
  const id = Number(checkId);
  const [check, setCheck] = useState<Check | null>(null);
  const [form, setForm] = useState<CheckPayload | null>(null);
  const [baseline, setBaseline] = useState<CheckPayload | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"saved-run" | "draft-run" | "save" | null>(null);
  const [bodyMode, setBodyMode] = useState<BodyEditorMode>("json");

  const isDirty = useMemo(() => Boolean(form && baseline && !sameCheckPayload(form, baseline)), [baseline, form]);

  useEffect(() => {
    api
      .check(id)
      .then((data) => {
        const payload = checkToPayload(data);
        setCheck(data);
        setForm(payload);
        setBaseline(normalizeCheckPayload(payload));
        setBodyMode(detectBodyMode(payload.body));
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, [id]);

  async function save(): Promise<Check | null> {
    if (!form) return null;
    try {
      const payload = prepareCheckPayload(form, { bodyMode });
      const saved = await api.updateCheck(id, payload);
      const savedPayload = checkToPayload(saved);
      setCheck(saved);
      setForm(savedPayload);
      setBaseline(normalizeCheckPayload(savedPayload));
      setError(null);
      return saved;
    } catch (err) {
      setError((err as Error).message);
      return null;
    }
  }

  async function saveOnly() {
    setBusy("save");
    try {
      await save();
    } finally {
      setBusy(null);
    }
  }

  async function runSaved() {
    setBusy("saved-run");
    try {
      setRun(await api.runCheck(id));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function runDraft() {
    if (!form) return;
    setBusy("draft-run");
    try {
      const payload = prepareCheckPayload(form, { bodyMode });
      setRun(await api.debugCheck(payload));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function patchForm(values: Partial<CheckPayload>) {
    setForm((current) => (current ? { ...current, ...values } : current));
  }

  function formatJsonField(field: "headers_json" | "body", label: string) {
    if (!form) return;
    try {
      const text = field === "headers_json" ? form.headers_json : form.body;
      if (field === "body" && !text.trim()) {
        patchForm({ body: "" });
        setError(null);
        return;
      }
      const parsed = JSON.parse(text || "{}");
      if (field === "headers_json" && (!parsed || typeof parsed !== "object" || Array.isArray(parsed))) {
        throw new Error("Headers 必须是 JSON Object");
      }
      patchForm({ [field]: JSON.stringify(parsed, null, 2) } as Partial<CheckPayload>);
      setError(null);
    } catch (err) {
      setError(`${label} 不是合法 JSON：${(err as Error).message}`);
    }
  }

  if (!form || !check) {
    return (
      <div className="page-content">
        <Card loading />
      </div>
    );
  }

  return (
    <div className="debug-page">
      <Card>
        <div className="debug-header">
          <Link to={checkType === "ui" ? "/ui-checks" : "/api-checks"}>
            <Button icon={<ArrowLeft size={16} />}>返回</Button>
          </Link>
          <div>
            <p className="eyebrow">{checkType === "ui" ? "UI 全屏调试" : "接口全屏调试"}</p>
            <h2>{check.name}</h2>
          </div>
          <Space wrap>
            <Tag color={isDirty ? "orange" : "green"}>{isDirty ? "未保存变更" : "已保存"}</Tag>
            <Button icon={<Play size={16} />} onClick={runSaved} loading={busy === "saved-run"} disabled={Boolean(busy)}>
              运行已保存版本
            </Button>
            <Button icon={<Play size={16} />} onClick={runDraft} loading={busy === "draft-run"} disabled={Boolean(busy)}>
              运行草稿
            </Button>
            <Button intent="primary" icon={<Save size={16} />} onClick={saveOnly} loading={busy === "save"} disabled={Boolean(busy)}>
              保存
            </Button>
          </Space>
        </div>
      </Card>

      {isDirty && (
        <Alert
          type="warning"
          message="存在未保存变更"
          description="运行草稿可验证当前编辑内容，不会保存配置、改变任务状态或触发告警；运行已保存版本仍使用已保存配置。"
          showIcon
        />
      )}
      {error && <Alert type="error" message={error} showIcon />}

      <div className="debug-layout">
        <Card className="debug-form" title="任务配置">
          <Form layout="vertical">
            <Form.Item label="名称" required>
              <Input value={form.name} onChange={(event) => patchForm({ name: event.target.value })} />
            </Form.Item>
            <Form.Item label={checkType === "ui" ? "页面 URL" : "接口 URL"} required>
              <Input value={form.entry_url} onChange={(event) => patchForm({ entry_url: event.target.value })} />
            </Form.Item>
            {checkType === "api" && (
              <Form.Item label="Method" required>
                <Select
                  value={form.method}
                  onChange={(value) => patchForm({ method: value })}
                  options={["GET", "POST", "PUT", "DELETE", "PATCH"].map((method) => ({ label: method, value: method }))}
                />
              </Form.Item>
            )}
            {checkType === "ui" && (
              <Form.Item label="页面模式" required>
                <ViewportModeControl value={form.viewport_mode} onChange={(viewport_mode) => patchForm({ viewport_mode })} />
              </Form.Item>
            )}
            <div className="field-grid two">
              <Form.Item label="执行频率">
                <InputNumber min={5} value={form.interval_seconds} addonAfter="秒" onChange={(value) => patchForm({ interval_seconds: Number(value || 5) })} />
              </Form.Item>
              <Form.Item label="超时时间">
                <InputNumber min={500} value={form.timeout_ms} addonAfter="ms" onChange={(value) => patchForm({ timeout_ms: Number(value || 500) })} />
              </Form.Item>
            </div>
            <Form.Item label="启用">
              <Space className="switch-line">
                <span>{form.enabled ? "已启用" : "已禁用"}</span>
                <Switch checked={form.enabled} onChange={(value) => patchForm({ enabled: value })} />
              </Space>
            </Form.Item>
          </Form>
        </Card>

        <Card className="debug-editor">
          <Space direction="vertical" size={14} className="drawer-stack">
            {checkType === "api" && (
              <>
                <div className="api-request-editors">
                  <CodeEditorPanel
                    title="Headers"
                    language="json"
                    value={form.headers_json}
                    height="220px"
                    compact
                    onChange={(value) => patchForm({ headers_json: value })}
                    extra={
                      <Button size="small" onClick={() => formatJsonField("headers_json", "Headers")}>
                        格式化
                      </Button>
                    }
                  />
                  <CodeEditorPanel
                    title="Body"
                    language={bodyMode === "json" ? "json" : "plaintext"}
                    value={form.body}
                    height="220px"
                    compact
                    onChange={(value) => patchForm({ body: value })}
                    extra={
                      <Space size={8} wrap>
                        <Segmented
                          size="small"
                          value={bodyMode}
                          onChange={(value) => setBodyMode(value as BodyEditorMode)}
                          options={[
                            { label: "JSON", value: "json" },
                            { label: "文本", value: "text" }
                          ]}
                        />
                        {bodyMode === "json" && (
                          <Button size="small" onClick={() => formatJsonField("body", "Body")}>
                            格式化
                          </Button>
                        )}
                      </Space>
                    }
                  />
                </div>
                <ApiAssertionsBuilder
                  bodyMode={bodyMode}
                  check={form}
                  value={form.assertions_json}
                  onChange={(assertions_json) => patchForm({ assertions_json })}
                />
              </>
            )}
            {checkType === "ui" ? (
              <>
                <UiAssertionsBuilder check={form} value={form.assertions_json} onChange={(assertions_json) => patchForm({ assertions_json })} />
                <UiScriptSections
                  setupScript={form.setup_script}
                  script={form.script}
                  setupHeight="320px"
                  scriptHeight="360px"
                  onSetupScriptChange={(value) => patchForm({ setup_script: value })}
                  onScriptChange={(value) => patchForm({ script: value })}
                />
              </>
            ) : (
              <Collapse
                className="advanced-script-collapse"
                items={[
                  {
                    key: "script",
                    label: "高级脚本",
                    children: (
                      <CodeEditorPanel
                        title="Python 脚本"
                        language="python"
                        value={form.script}
                        height="360px"
                        onChange={(value) => patchForm({ script: value })}
                        extra={
                          !form.script.trim() && (
                            <Button size="small" onClick={() => patchForm({ script: apiScriptTemplate })}>
                              使用模板
                            </Button>
                          )
                        }
                      />
                    )
                  }
                ]}
              />
            )}
          </Space>
        </Card>

        <div className="debug-result">
          {!run ? (
            <Card>
              <Alert type="info" message="暂无本页运行结果" showIcon />
            </Card>
          ) : (
            <RunResultPanel run={run} mode="debug" />
          )}
        </div>
      </div>
    </div>
  );
}
