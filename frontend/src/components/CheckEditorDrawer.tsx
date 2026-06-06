import { Alert, Collapse, Drawer, Form, Input, InputNumber, Modal, Segmented, Select, Space, Switch, Tag } from "antd";
import { Play, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { checkToPayload, detectBodyMode, normalizeCheckPayload, prepareCheckPayload, sameCheckPayload, type BodyEditorMode } from "../checkPayload";
import { apiScriptTemplate, blankCheck } from "../defaults";
import type { Check, CheckPayload, CheckType, Run } from "../types";
import { ApiAssertionsBuilder } from "./ApiAssertionsBuilder";
import { AppButton as Button } from "./common/AppButton";
import { CodeEditorPanel } from "./CodeEditorPanel";
import { RunResultPanel } from "./RunResultPanel";
import { UiAssertionsBuilder } from "./UiAssertionsBuilder";
import { UiScriptSections } from "./UiScriptSections";
import { ViewportModeControl } from "./ViewportModeControl";

interface Props {
  open: boolean;
  type: CheckType;
  check: Check | null;
  onClose: () => void;
  onSaved: () => void;
}

export function CheckEditorDrawer({ open, type, check, onClose, onSaved }: Props) {
  const [form, setForm] = useState<CheckPayload>(() => blankCheck(type));
  const [activeCheck, setActiveCheck] = useState<Check | null>(check);
  const [baseline, setBaseline] = useState<CheckPayload>(() => normalizeCheckPayload(blankCheck(type)));
  const [saving, setSaving] = useState(false);
  const [runningMode, setRunningMode] = useState<"saved" | "draft" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [debugRun, setDebugRun] = useState<Run | null>(null);
  const [debugSnapshot, setDebugSnapshot] = useState<CheckPayload | null>(null);
  const [bodyMode, setBodyMode] = useState<BodyEditorMode>("json");

  const isDirty = useMemo(() => !sameCheckPayload(form, baseline), [baseline, form]);
  const debugStale = useMemo(() => Boolean(debugRun && debugSnapshot && !sameCheckPayload(form, debugSnapshot)), [debugRun, debugSnapshot, form]);
  const running = Boolean(runningMode);

  useEffect(() => {
    if (!open) return;
    const next = check ? checkToPayload(check) : blankCheck(type);
    setError(null);
    setDebugRun(null);
    setDebugSnapshot(null);
    setActiveCheck(check);
    setForm(next);
    setBaseline(normalizeCheckPayload(next));
    setBodyMode(detectBodyMode(next.body));
  }, [check, open, type]);

  async function save(): Promise<Check> {
    setSaving(true);
    setError(null);
    try {
      const payload = prepareCheckPayload(form, { bodyMode });
      const saved = activeCheck ? await api.updateCheck(activeCheck.id, payload) : await api.createCheck(payload);
      const savedPayload = checkToPayload(saved);
      setActiveCheck(saved);
      setForm(savedPayload);
      setBaseline(normalizeCheckPayload(savedPayload));
      onSaved();
      return saved;
    } catch (err) {
      setError((err as Error).message);
      throw err;
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveOnly() {
    try {
      await save();
      onClose();
    } catch {
      // save() has already surfaced the validation or request error in the drawer.
    }
  }

  async function handleRunSaved() {
    setRunningMode("saved");
    setError(null);
    try {
      if (!activeCheck) {
        throw new Error("新任务需要先保存后才能运行已保存版本");
      }
      const run = await api.runCheck(activeCheck.id);
      setDebugRun(run);
      setDebugSnapshot(normalizeCheckPayload(checkToPayload(activeCheck)));
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunningMode(null);
    }
  }

  async function handleRunDraft() {
    setRunningMode("draft");
    setError(null);
    try {
      const payload = prepareCheckPayload(form, { bodyMode });
      const run = await api.debugCheck(payload);
      setDebugRun(run);
      setDebugSnapshot(normalizeCheckPayload(payload));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunningMode(null);
    }
  }

  function patchForm(values: Partial<CheckPayload>) {
    setForm((current) => ({ ...current, ...values }));
  }

  function requestClose() {
    if (!isDirty) {
      onClose();
      return;
    }
    Modal.confirm({
      title: "有未保存变更",
      content: "关闭后将丢失当前编辑内容。",
      okText: "放弃更改",
      okButtonProps: { danger: true },
      cancelText: "继续编辑",
      onOk: onClose
    });
  }

  function formatJsonField(field: "headers_json" | "body", label: string) {
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

  return (
    <Drawer
      title={activeCheck ? "编辑任务" : "新增任务"}
      open={open}
      width={920}
      onClose={requestClose}
      destroyOnClose
      extra={<Tag color={isDirty ? "orange" : activeCheck ? "green" : "blue"}>{isDirty ? "未保存变更" : activeCheck ? "已保存" : "新任务草稿"}</Tag>}
      footer={
        <Space className="drawer-footer-actions">
          <Button onClick={requestClose}>取消</Button>
          <Button
            icon={<Play size={16} />}
            onClick={handleRunSaved}
            loading={runningMode === "saved"}
            disabled={saving || running || !activeCheck}
          >
            运行已保存版本
          </Button>
          <Button icon={<Play size={16} />} onClick={handleRunDraft} loading={runningMode === "draft"} disabled={saving || running}>
            运行草稿
          </Button>
          <Button intent="primary" icon={<Save size={16} />} onClick={handleSaveOnly} loading={saving} disabled={running}>
            保存
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size={16} className="drawer-stack">
        {isDirty && (
          <Alert
            type="warning"
            message="存在未保存变更"
            description="运行草稿可验证当前编辑内容，不会保存配置、改变任务状态或触发告警；运行已保存版本仍使用已保存配置。"
            showIcon
          />
        )}
        {debugStale && <Alert type="info" message="调试结果来自上一次运行，当前草稿已有新改动" showIcon />}

        <Form layout="vertical">
          <div className="field-grid two">
            <Form.Item label="名称" required>
              <Input value={form.name} onChange={(event) => patchForm({ name: event.target.value })} />
            </Form.Item>
            <Form.Item label="标签">
              <Input value={form.tags} onChange={(event) => patchForm({ tags: event.target.value })} />
            </Form.Item>
          </div>

          <Form.Item label={type === "ui" ? "页面 URL" : "接口 URL"} required>
            <Input value={form.entry_url} onChange={(event) => patchForm({ entry_url: event.target.value })} />
          </Form.Item>

          <div className="field-grid four">
            {type === "api" && (
              <Form.Item label="Method" required>
                <Select
                  value={form.method}
                  onChange={(value) => patchForm({ method: value })}
                  options={["GET", "POST", "PUT", "DELETE", "PATCH"].map((method) => ({ label: method, value: method }))}
                />
              </Form.Item>
            )}
            {type === "ui" && (
              <Form.Item label="页面模式" required>
                <ViewportModeControl value={form.viewport_mode} onChange={(viewport_mode) => patchForm({ viewport_mode })} />
              </Form.Item>
            )}
            <Form.Item label="执行频率" required>
              <InputNumber
                min={5}
                value={form.interval_seconds}
                addonAfter="秒"
                onChange={(value) => patchForm({ interval_seconds: Number(value || 5) })}
              />
            </Form.Item>
            <Form.Item label="超时时间" required>
              <InputNumber
                min={500}
                value={form.timeout_ms}
                addonAfter="ms"
                onChange={(value) => patchForm({ timeout_ms: Number(value || 500) })}
              />
            </Form.Item>
            <Form.Item label="启用">
              <Space className="switch-line">
                <span>{form.enabled ? "已启用" : "已禁用"}</span>
                <Switch checked={form.enabled} onChange={(checked) => patchForm({ enabled: checked })} />
              </Space>
            </Form.Item>
          </div>
        </Form>

        {type === "api" && (
          <>
            <div className="api-request-editors">
              <CodeEditorPanel
                title="Headers"
                language="json"
                value={form.headers_json}
                height="210px"
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
                height="210px"
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

        {type === "ui" ? (
          <>
            <UiAssertionsBuilder check={form} value={form.assertions_json} onChange={(assertions_json) => patchForm({ assertions_json })} />
            <UiScriptSections
              setupScript={form.setup_script}
              script={form.script}
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
                    height="320px"
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

        {error && <Alert type="error" message={error} showIcon />}
        {debugRun && <RunResultPanel run={debugRun} mode="debug" />}
      </Space>
    </Drawer>
  );
}
