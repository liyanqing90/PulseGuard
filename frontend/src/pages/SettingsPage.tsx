import { Alert, Empty, Form, Input, InputNumber, Popconfirm, Select, Skeleton, Space, Switch, Tabs, Tag, Tooltip } from "antd";
import {
  BellRing,
  CheckCircle2,
  Database,
  KeyRound,
  Monitor,
  Plus,
  RotateCcw,
  Save,
  Send,
  ShieldCheck,
  Trash2,
  Zap
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { AppButton as Button } from "../components/common/AppButton";
import { StructuredViewer } from "../components/StructuredViewer";
import type { AlertPreview, AlertPreviewChannel, NotificationChannel, SettingsValues, WebhookType } from "../types";

type Notice = { type: "success" | "error"; message: string } | null;
type SettingsTab = "alerts" | "runtime" | "browser" | "retention";

const CHANNEL_OPTIONS: Array<{ label: string; value: WebhookType }> = [
  { label: "飞书", value: "feishu" },
  { label: "企业微信", value: "wecom" },
  { label: "钉钉", value: "dingtalk" }
];

const CHANNEL_GUIDES: Record<WebhookType, { label: string; expectedHost: string; webhookHint: string; secretHint: string }> = {
  feishu: {
    label: "飞书",
    expectedHost: "open.feishu.cn",
    webhookHint: "粘贴飞书群机器人 Webhook 地址",
    secretHint: "飞书文本机器人无需额外密钥"
  },
  wecom: {
    label: "企业微信",
    expectedHost: "qyapi.weixin.qq.com",
    webhookHint: "粘贴企业微信群机器人 Webhook 地址",
    secretHint: "企业微信群机器人无需额外密钥"
  },
  dingtalk: {
    label: "钉钉",
    expectedHost: "oapi.dingtalk.com",
    webhookHint: "粘贴钉钉自定义机器人 Webhook 地址",
    secretHint: "启用加签时填写 SEC 开头的密钥"
  }
};

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsValues | null>(null);
  const [savedSettings, setSavedSettings] = useState<SettingsValues | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [alertPreview, setAlertPreview] = useState<AlertPreview | null>(null);
  const [newChannelType, setNewChannelType] = useState<WebhookType>("feishu");
  const [activeTab, setActiveTab] = useState<SettingsTab>("alerts");

  useEffect(() => {
    api
      .settings()
      .then((values) => {
        setSettings(cloneSettings(values));
        setSavedSettings(cloneSettings(values));
      })
      .catch((err: Error) => setNotice({ type: "error", message: err.message }))
      .finally(() => setLoading(false));
  }, []);

  function update<K extends keyof SettingsValues>(key: K, value: SettingsValues[K]) {
    setAlertPreview(null);
    setSettings((current) => (current ? { ...current, [key]: value } : current));
  }

  function updateChannel(channelId: string, patch: Partial<NotificationChannel>) {
    setAlertPreview(null);
    setSettings((current) => {
      if (!current) return current;
      return {
        ...current,
        notification_channels: current.notification_channels.map((channel) =>
          channel.id === channelId ? { ...channel, ...patch } : channel
        )
      };
    });
  }

  function addChannel() {
    setAlertPreview(null);
    setSettings((current) => {
      if (!current) return current;
      return {
        ...current,
        notification_channels: [...current.notification_channels, createChannel(newChannelType)]
      };
    });
  }

  function removeChannel(channelId: string) {
    setAlertPreview(null);
    setSettings((current) => {
      if (!current) return current;
      return {
        ...current,
        notification_channels: current.notification_channels.filter((channel) => channel.id !== channelId)
      };
    });
  }

  function buildPayload(scope: SettingsTab = activeTab): Partial<SettingsValues> {
    if (!settings) return {};
    if (scope === "alerts") {
      return {
        alerts_enabled: settings.alerts_enabled,
        alert_detail_base_url: settings.alert_detail_base_url.trim(),
        alert_cooldown_minutes: settings.alert_cooldown_minutes,
        recovery_notification: settings.recovery_notification,
        notification_channels: settings.notification_channels.map(toPayloadChannel)
      };
    }
    if (scope === "runtime") {
      return {
        default_interval_seconds: settings.default_interval_seconds,
        default_ui_timeout_ms: settings.default_ui_timeout_ms,
        default_api_timeout_ms: settings.default_api_timeout_ms,
        max_concurrency: settings.max_concurrency,
        max_task_runtime_seconds: settings.max_task_runtime_seconds
      };
    }
    if (scope === "browser") {
      return {
        browser_headless: settings.browser_headless,
        browser_type: settings.browser_type,
        browser_proxy: settings.browser_proxy,
        browser_viewport: settings.browser_viewport
      };
    }
    return {
      run_retention_days: settings.run_retention_days,
      screenshot_retention_days: settings.screenshot_retention_days,
      trace_retention_days: settings.trace_retention_days,
      response_retention_days: settings.response_retention_days
    };
  }

  async function save(scope: SettingsTab = activeTab) {
    if (!settings) return;
    setSaving(true);
    setNotice(null);
    try {
      const values = await api.updateSettings(buildPayload(scope));
      setSettings(cloneSettings(values));
      setSavedSettings(cloneSettings(values));
      setAlertPreview(null);
      setNotice({ type: "success", message: "当前页设置已保存" });
    } catch (err) {
      setNotice({ type: "error", message: (err as Error).message });
    } finally {
      setSaving(false);
    }
  }

  async function testAlert() {
    if (!settings) return;
    setTesting(true);
    setNotice(null);
    try {
      const result = await api.testAlert(buildPayload("alerts"));
      setNotice({ type: "success", message: result.message });
    } catch (err) {
      setNotice({ type: "error", message: (err as Error).message });
    } finally {
      setTesting(false);
    }
  }

  async function previewAlert() {
    if (!settings) return;
    setPreviewing(true);
    setNotice(null);
    try {
      setAlertPreview(await api.alertPreview(buildPayload("alerts")));
    } catch (err) {
      setAlertPreview(null);
      setNotice({ type: "error", message: (err as Error).message });
    } finally {
      setPreviewing(false);
    }
  }

  function resetDraft() {
    if (!savedSettings) return;
    setSettings(cloneSettings(savedSettings));
    setAlertPreview(null);
    setNotice({ type: "success", message: "已撤销未保存更改" });
  }

  if (loading || !settings) {
    return (
      <div className="page-content settings-page">
        <Skeleton active paragraph={{ rows: 10 }} />
      </div>
    );
  }

  const blockingError = firstBlockingError(settings.notification_channels);
  const readyChannels = readyNotificationChannels(settings.notification_channels);
  const hasUnsavedChanges = Boolean(savedSettings && settingsChanged(settings, savedSettings));
  const activeTabChanged = Boolean(savedSettings && settingsTabChanged(settings, savedSettings, activeTab));
  const alertSettingsChanged = Boolean(savedSettings && settingsTabChanged(settings, savedSettings, "alerts"));
  const activeTabBlockingError = activeTab === "alerts" ? blockingError : "";
  const saveDisabledReason = activeTabBlockingError || (!activeTabChanged ? "当前页没有需要保存的更改" : "");
  const testDisabledReason =
    blockingError || (readyChannels.length === 0 ? "至少配置一个启用且填写 URL 的通知渠道后再发送测试" : "");
  const previewDisabledReason = settings.notification_channels.length === 0 ? "先添加通知渠道后再预检" : blockingError;
  const enabledChannelCount = settings.notification_channels.filter((channel) => channel.enabled).length;

  return (
    <div className="page-content settings-page">
      <section className="settings-hero">
        <div>
          <p className="eyebrow">系统设置</p>
          <div className="settings-title-row">
            <h2>运行与告警控制台</h2>
            <Tag color={hasUnsavedChanges ? "orange" : "green"}>{hasUnsavedChanges ? "未保存更改" : "已保存"}</Tag>
          </div>
        </div>
        <Space wrap>
          <Button icon={<RotateCcw size={16} />} onClick={resetDraft} disabled={!hasUnsavedChanges}>
            撤销更改
          </Button>
          {activeTab === "alerts" && (
            <TestAlertButton loading={testing} disabledReason={testDisabledReason} usesDraft={alertSettingsChanged} onClick={testAlert} />
          )}
          <SaveSettingsButton loading={saving} disabledReason={saveDisabledReason} onClick={() => save()} />
        </Space>
      </section>

      {notice && <Alert type={notice.type} message={notice.message} showIcon />}
      {settings.alerts_enabled && readyChannels.length === 0 && (
        <Alert type="warning" message="告警已启用，但当前没有可发送的通知渠道" showIcon />
      )}

      <section className="settings-summary">
        <SummaryTile icon={<BellRing size={17} />} label="告警状态" value={settings.alerts_enabled ? "已启用" : "未启用"} active={settings.alerts_enabled} />
        <SummaryTile icon={<ShieldCheck size={17} />} label="可发送渠道" value={`${readyChannels.length}/${settings.notification_channels.length}`} active={readyChannels.length > 0} />
        <SummaryTile icon={<CheckCircle2 size={17} />} label="恢复通知" value={settings.recovery_notification ? "发送" : "关闭"} active={settings.recovery_notification} />
        <SummaryTile icon={<Database size={17} />} label="历史保留" value={`${settings.run_retention_days} 天`} />
      </section>

      <Tabs
        activeKey={activeTab}
        className="settings-tabs"
        onChange={(key) => setActiveTab(key as SettingsTab)}
        items={[
          { key: "alerts", label: "告警通知" },
          { key: "runtime", label: "执行参数" },
          { key: "browser", label: "浏览器" },
          { key: "retention", label: "数据保留" }
        ]}
      />

      <section className={`settings-layout settings-layout-${activeTab}`}>
        {activeTab === "alerts" && (
          <>
        <SettingsPanel title="公共告警策略" icon={<BellRing size={18} />} accent className="settings-panel-wide">
          <Form layout="vertical" className="settings-form-grid" autoComplete="off">
            <Form.Item label="启用告警">
              <Switch checked={settings.alerts_enabled} onChange={(value) => update("alerts_enabled", value)} />
            </Form.Item>
            <Form.Item label="恢复通知">
              <Switch checked={settings.recovery_notification} onChange={(value) => update("recovery_notification", value)} />
            </Form.Item>
            <NumberItem
              label="失败冷却时间"
              value={settings.alert_cooldown_minutes}
              min={1}
              max={1440}
              addonAfter="分钟"
              onChange={(value) => update("alert_cooldown_minutes", value)}
            />
            <Form.Item label="告警详情链接前缀" className="span-2">
              <Input
                value={settings.alert_detail_base_url}
                onChange={(event) => update("alert_detail_base_url", event.target.value)}
                placeholder="http://10.168.78.49:8787"
              />
            </Form.Item>
            <Form.Item label="启用渠道">
              <div className="setting-inline-metric">
                <strong>{enabledChannelCount}</strong>
                <span>个渠道参与告警发送</span>
              </div>
            </Form.Item>
          </Form>
        </SettingsPanel>

        <SettingsPanel title="通知渠道" icon={<ShieldCheck size={18} />} className="settings-panel-wide">
          <AlertPreviewTool
            preview={alertPreview}
            loading={previewing}
            disabledReason={previewDisabledReason}
            usesDraft={alertSettingsChanged}
            onPreview={previewAlert}
          />
          <div className="channel-toolbar">
            <Space.Compact>
              <Select
                value={newChannelType}
                onChange={(value) => setNewChannelType(value)}
                options={CHANNEL_OPTIONS}
                className="channel-type-picker"
              />
              <Button icon={<Plus size={16} />} onClick={addChannel}>
                添加渠道
              </Button>
            </Space.Compact>
          </div>
          {settings.notification_channels.length === 0 ? (
            <Empty description="暂无通知渠道" />
          ) : (
            <div className="notification-channel-list">
              {settings.notification_channels.map((channel, index) => (
                <NotificationChannelEditor
                  key={channel.id}
                  channel={channel}
                  index={index}
                  onPatch={(patch) => updateChannel(channel.id, patch)}
                  onRemove={() => removeChannel(channel.id)}
                />
              ))}
            </div>
          )}
        </SettingsPanel>

          </>
        )}

        {activeTab === "runtime" && (
        <SettingsPanel title="执行设置" icon={<Zap size={18} />}>
          <Form layout="vertical" className="settings-form-grid" autoComplete="off">
            <NumberItem label="默认执行频率" value={settings.default_interval_seconds} min={5} max={86400} addonAfter="秒" onChange={(value) => update("default_interval_seconds", value)} />
            <NumberItem label="最大并发任务数" value={settings.max_concurrency} min={1} max={20} onChange={(value) => update("max_concurrency", value)} />
            <NumberItem label="默认 UI 超时" value={settings.default_ui_timeout_ms} min={500} max={300000} addonAfter="ms" onChange={(value) => update("default_ui_timeout_ms", value)} />
            <NumberItem label="默认 API 超时" value={settings.default_api_timeout_ms} min={500} max={300000} addonAfter="ms" onChange={(value) => update("default_api_timeout_ms", value)} />
            <NumberItem label="单任务最大运行时长" value={settings.max_task_runtime_seconds} min={1} max={600} addonAfter="秒" onChange={(value) => update("max_task_runtime_seconds", value)} />
          </Form>
        </SettingsPanel>
        )}

        {activeTab === "browser" && (
        <SettingsPanel title="浏览器设置" icon={<Monitor size={18} />}>
          <Form layout="vertical" className="settings-form-grid" autoComplete="off">
            <Form.Item label="Headless">
              <Switch checked={settings.browser_headless} onChange={(value) => update("browser_headless", value)} />
            </Form.Item>
            <Form.Item label="浏览器类型">
              <Select
                value={settings.browser_type}
                onChange={(value) => update("browser_type", value)}
                options={[
                  { label: "chromium", value: "chromium" },
                  { label: "firefox", value: "firefox" },
                  { label: "webkit", value: "webkit" }
                ]}
              />
            </Form.Item>
            <Form.Item label="代理" className="span-2">
              <Input value={settings.browser_proxy} onChange={(event) => update("browser_proxy", event.target.value)} placeholder="http://127.0.0.1:7890" />
            </Form.Item>
            <Form.Item label="Viewport" className="span-2">
              <Input value={settings.browser_viewport} onChange={(event) => update("browser_viewport", event.target.value)} placeholder="1440x900" />
            </Form.Item>
          </Form>
        </SettingsPanel>
        )}

        {activeTab === "retention" && (
        <SettingsPanel title="数据保留" icon={<Database size={18} />}>
          <Form layout="vertical" className="settings-form-grid" autoComplete="off">
            <NumberItem label="执行历史保留" value={settings.run_retention_days} min={1} max={365} addonAfter="天" onChange={(value) => update("run_retention_days", value)} />
            <NumberItem label="截图保留" value={settings.screenshot_retention_days} min={1} max={365} addonAfter="天" onChange={(value) => update("screenshot_retention_days", value)} />
            <NumberItem label="Trace 保留" value={settings.trace_retention_days} min={1} max={365} addonAfter="天" onChange={(value) => update("trace_retention_days", value)} />
            <NumberItem label="Response Body 保留" value={settings.response_retention_days} min={1} max={365} addonAfter="天" onChange={(value) => update("response_retention_days", value)} />
          </Form>
        </SettingsPanel>
        )}
      </section>
    </div>
  );
}

function NotificationChannelEditor({
  channel,
  index,
  onPatch,
  onRemove
}: {
  channel: NotificationChannel;
  index: number;
  onPatch: (patch: Partial<NotificationChannel>) => void;
  onRemove: () => void;
}) {
  const guide = CHANNEL_GUIDES[channel.type];
  const urlError = channelUrlError(channel);
  const hostHint = channelHostHint(channel);
  const secretError = channelSecretError(channel);
  const ready = isReadyForSend(channel);

  function changeType(type: WebhookType) {
    onPatch({
      type,
      dingtalk_secret: "",
      dingtalk_secret_set: type === "dingtalk" ? channel.dingtalk_secret_set : false,
      dingtalk_secret_clear: type === "dingtalk" ? channel.dingtalk_secret_clear : false
    });
  }

  return (
    <section className={`notification-channel-card ${ready ? "notification-channel-ready" : ""}`}>
      <div className="notification-channel-header">
        <div className="notification-channel-title">
          <Switch checked={channel.enabled} onChange={(value) => onPatch({ enabled: value })} />
          <div>
            <strong>{channel.name.trim() || `${guide.label}渠道 ${index + 1}`}</strong>
            <span>{channel.enabled ? channelStatusText(channel, ready) : "已停用"}</span>
          </div>
        </div>
        <Space size={8} wrap>
          <Tag color={ready ? "green" : channel.enabled ? "orange" : "default"}>{ready ? "可发送" : channel.enabled ? "待配置" : "停用"}</Tag>
          <Popconfirm title="删除通知渠道" description="删除后保存设置才会生效。" okText="删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={onRemove}>
            <Tooltip title="删除渠道">
              <Button danger icon={<Trash2 size={15} />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      </div>

      <Form layout="vertical" className="notification-channel-grid" autoComplete="off">
        <Form.Item label="渠道名称">
          <Input value={channel.name} onChange={(event) => onPatch({ name: event.target.value })} placeholder="如：值班群" />
        </Form.Item>
        <Form.Item label="渠道类型">
          <Select value={channel.type} onChange={(value) => changeType(value)} options={CHANNEL_OPTIONS} />
        </Form.Item>
        <Form.Item label="Webhook URL" className="span-2" validateStatus={urlError ? "error" : hostHint ? "warning" : undefined} help={urlError || hostHint || guide.webhookHint}>
          <Input
            value={channel.webhook_url}
            onChange={(event) => onPatch({ webhook_url: event.target.value })}
            placeholder="https://..."
            status={urlError ? "error" : hostHint ? "warning" : undefined}
          />
        </Form.Item>
        {channel.type === "dingtalk" && (
          <Form.Item
            label={
              <Space size={8}>
                <span>钉钉加签密钥</span>
                {channel.dingtalk_secret_set && !channel.dingtalk_secret_clear && !channel.dingtalk_secret && <Tag color="green">已配置</Tag>}
                {channel.dingtalk_secret_clear && <Tag color="orange">待清除</Tag>}
              </Space>
            }
            className="span-2"
            validateStatus={secretError ? "warning" : undefined}
            help={secretError || guide.secretHint}
          >
            <Space.Compact className="secret-input-row">
              <Input.Password
                value={channel.dingtalk_secret || ""}
                onChange={(event) => onPatch({ dingtalk_secret: event.target.value, dingtalk_secret_clear: false })}
                autoComplete="new-password"
                placeholder={channel.dingtalk_secret_set ? "输入新密钥可替换现有密钥" : "SEC 开头的加签密钥"}
                prefix={<KeyRound size={15} />}
              />
              {channel.dingtalk_secret_set && !channel.dingtalk_secret_clear && (
                <Popconfirm
                  title="清除钉钉加签密钥"
                  description="保存设置后，该渠道将不再携带钉钉签名参数。"
                  okText="清除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => onPatch({ dingtalk_secret: "", dingtalk_secret_set: false, dingtalk_secret_clear: true })}
                >
                  <Tooltip title="清除已保存密钥">
                    <Button danger icon={<Trash2 size={15} />} />
                  </Tooltip>
                </Popconfirm>
              )}
              {channel.dingtalk_secret_clear && (
                <Tooltip title="撤销清除密钥">
                  <Button icon={<RotateCcw size={15} />} onClick={() => onPatch({ dingtalk_secret_clear: false, dingtalk_secret_set: true })} />
                </Tooltip>
              )}
            </Space.Compact>
          </Form.Item>
        )}
      </Form>
    </section>
  );
}

function AlertPreviewTool({
  preview,
  loading,
  disabledReason,
  usesDraft,
  onPreview
}: {
  preview: AlertPreview | null;
  loading: boolean;
  disabledReason: string;
  usesDraft: boolean;
  onPreview: () => void;
}) {
  const disabled = Boolean(disabledReason);
  return (
    <section className="alert-preview-tool">
      <div className="alert-preview-header">
        <div>
          <strong>本地预检</strong>
          <span>{usesDraft ? "使用当前页面草稿生成，不保存也不发送" : "基于已保存配置生成，不发送网络请求"}</span>
        </div>
        <Tooltip title={disabledReason || "生成脱敏目标、消息正文和 Webhook Payload"}>
          <span className="tooltip-button-wrapper">
            <Button icon={<ShieldCheck size={16} />} loading={loading} disabled={disabled} onClick={onPreview}>
              预检配置
            </Button>
          </span>
        </Tooltip>
      </div>

      {preview && (
        <div className="alert-preview-body">
          {preview.channels.length === 0 ? (
            <Empty description="暂无可预检渠道" />
          ) : (
            <div className="alert-preview-channel-list">
              {preview.channels.map((channel) => (
                <PreviewChannel key={channel.id || `${channel.type}-${channel.name}`} channel={channel} />
              ))}
            </div>
          )}
          <StructuredViewer title="消息正文" value={preview.message_text} defaultMode="markdown" />
        </div>
      )}
    </section>
  );
}

function PreviewChannel({ channel }: { channel: AlertPreviewChannel }) {
  return (
    <section className="alert-preview-channel">
      <div className="alert-preview-channel-header">
        <strong>{channel.name || channelTypeLabel(channel.type)}</strong>
        <Space size={6} wrap>
          <Tag>{channelTypeLabel(channel.type)}</Tag>
          <Tag color={channel.enabled ? "green" : "default"}>{channel.enabled ? "启用" : "停用"}</Tag>
        </Space>
      </div>
      <div className="alert-preview-facts">
        <PreviewFact label="目标 Origin" value={channel.target.origin || "-"} />
        <PreviewFact label="路径" value={channel.target.path || "-"} />
        <PreviewFact label="查询参数" value={channel.target.query_keys.length ? channel.target.query_keys.join(", ") : "-"} />
        <PreviewFact label="钉钉加签" value={channel.signing_enabled ? "发送时追加 timestamp/sign" : "不追加签名"} tone={channel.signing_enabled ? "ok" : "muted"} />
      </div>
      {channel.target.issues.length > 0 && <Alert className="compact-alert" type="warning" message={channel.target.issues.join("；")} showIcon />}
      <StructuredViewer title="Webhook Payload" value={channel.payload} defaultMode="json" />
    </section>
  );
}

function PreviewFact({ label, value, tone = "muted" }: { label: string; value: string; tone?: "ok" | "muted" }) {
  return (
    <div className={`alert-preview-fact alert-preview-fact-${tone}`}>
      <small>{label}</small>
      <span>{value}</span>
    </div>
  );
}

function SettingsPanel({
  title,
  icon,
  children,
  accent,
  className
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
  accent?: boolean;
  className?: string;
}) {
  return (
    <section className={["settings-panel", accent ? "settings-panel-accent" : "", className].filter(Boolean).join(" ")}>
      <div className="settings-panel-header">
        <span className="settings-panel-icon">{icon}</span>
        <h3>{title}</h3>
      </div>
      {children}
    </section>
  );
}

function SummaryTile({ icon, label, value, active }: { icon: ReactNode; label: string; value: string; active?: boolean }) {
  return (
    <div className={`settings-summary-tile ${active ? "active" : ""}`}>
      <span>{icon}</span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function TestAlertButton({
  loading,
  disabledReason,
  usesDraft,
  onClick
}: {
  loading: boolean;
  disabledReason: string;
  usesDraft: boolean;
  onClick: () => void;
}) {
  const disabled = Boolean(disabledReason);
  return (
    <Tooltip title={disabledReason || (usesDraft ? "发送测试会使用当前页面草稿，不会自动保存设置" : "发送一条测试告警，校验当前通知渠道")}>
      <span className="tooltip-button-wrapper">
        <Button icon={<Send size={16} />} onClick={onClick} loading={loading} disabled={disabled}>
          发送测试
        </Button>
      </span>
    </Tooltip>
  );
}

function SaveSettingsButton({
  loading,
  disabledReason,
  onClick
}: {
  loading: boolean;
  disabledReason: string;
  onClick: () => void;
}) {
  const disabled = Boolean(disabledReason);
  return (
    <Tooltip title={disabledReason || "保存当前页设置"}>
      <span className="tooltip-button-wrapper">
        <Button intent="primary" icon={<Save size={16} />} onClick={onClick} loading={loading} disabled={disabled}>
          保存当前页
        </Button>
      </span>
    </Tooltip>
  );
}

function NumberItem({
  label,
  value,
  onChange,
  addonAfter,
  min,
  max
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  addonAfter?: string;
  min?: number;
  max?: number;
}) {
  return (
    <Form.Item label={label}>
      <InputNumber min={min} max={max} value={value} addonAfter={addonAfter} onChange={(next) => onChange(Number(next || 0))} />
    </Form.Item>
  );
}

function createChannel(type: WebhookType): NotificationChannel {
  return {
    id: `channel-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: "",
    type,
    enabled: true,
    webhook_url: "",
    dingtalk_secret: ""
  };
}

function toPayloadChannel(channel: NotificationChannel): NotificationChannel {
  const payload: NotificationChannel = {
    id: channel.id,
    name: channel.name.trim(),
    type: channel.type,
    enabled: channel.enabled,
    webhook_url: channel.webhook_url.trim()
  };
  if (channel.type === "dingtalk") {
    payload.dingtalk_secret = (channel.dingtalk_secret || "").trim();
    if (channel.dingtalk_secret_clear) {
      payload.dingtalk_secret_clear = true;
    }
  }
  return payload;
}

function firstBlockingError(channels: NotificationChannel[]): string {
  for (const channel of channels) {
    const error = channelUrlError(channel) || channelSecretError(channel);
    if (error) return error;
  }
  return "";
}

function readyNotificationChannels(channels: NotificationChannel[]) {
  return channels.filter(isReadyForSend);
}

function isReadyForSend(channel: NotificationChannel): boolean {
  return channel.enabled && Boolean(channel.webhook_url.trim()) && !channelUrlError(channel) && !channelSecretError(channel);
}

function channelStatusText(channel: NotificationChannel, ready: boolean): string {
  if (ready) return "Webhook 格式正常";
  if (!channel.webhook_url.trim()) return "等待填写 Webhook URL";
  return channelUrlError(channel) || channelSecretError(channel) || "建议核对渠道地址";
}

function channelUrlError(channel: NotificationChannel): string {
  const value = channel.webhook_url.trim();
  if (!value) return "";
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return "Webhook URL 需要是完整的 http:// 或 https:// 地址";
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    return "Webhook URL 仅支持 http:// 或 https://";
  }
  return "";
}

function channelHostHint(channel: NotificationChannel): string {
  const value = channel.webhook_url.trim();
  if (!value || channelUrlError(channel)) return "";
  const parsed = new URL(value);
  if (isLocalWebhookHost(parsed.hostname)) return "";
  const guide = CHANNEL_GUIDES[channel.type];
  if (!parsed.hostname.endsWith(guide.expectedHost)) {
    return `当前 URL 不像${guide.label}官方机器人地址；如果通过内部网关转发，可以忽略此提示`;
  }
  return "";
}

function channelSecretError(channel: NotificationChannel): string {
  if (channel.type !== "dingtalk") return "";
  const secret = (channel.dingtalk_secret || "").trim();
  if (secret && !secret.startsWith("SEC")) {
    return "钉钉加签密钥应以 SEC 开头";
  }
  return "";
}

function isLocalWebhookHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function channelTypeLabel(type: WebhookType): string {
  return CHANNEL_GUIDES[type]?.label || type;
}

function settingsChanged(current: SettingsValues, saved: SettingsValues): boolean {
  return JSON.stringify(comparableSettings(current)) !== JSON.stringify(comparableSettings(saved));
}

function settingsTabChanged(current: SettingsValues, saved: SettingsValues, tab: SettingsTab): boolean {
  return JSON.stringify(comparableSettings(current, tab)) !== JSON.stringify(comparableSettings(saved, tab));
}

function comparableSettings(values: SettingsValues, tab?: SettingsTab) {
  const alerts = {
    alerts_enabled: values.alerts_enabled,
    alert_detail_base_url: values.alert_detail_base_url,
    alert_cooldown_minutes: values.alert_cooldown_minutes,
    recovery_notification: values.recovery_notification,
    notification_channels: values.notification_channels.map((channel) => ({
      id: channel.id,
      name: channel.name,
      type: channel.type,
      enabled: channel.enabled,
      webhook_url: channel.webhook_url,
      dingtalk_secret: channel.dingtalk_secret || "",
      dingtalk_secret_set: Boolean(channel.dingtalk_secret_set),
      dingtalk_secret_clear: Boolean(channel.dingtalk_secret_clear)
    }))
  };
  const runtime = {
    default_interval_seconds: values.default_interval_seconds,
    default_ui_timeout_ms: values.default_ui_timeout_ms,
    default_api_timeout_ms: values.default_api_timeout_ms,
    max_concurrency: values.max_concurrency,
    max_task_runtime_seconds: values.max_task_runtime_seconds
  };
  const browser = {
    browser_headless: values.browser_headless,
    browser_type: values.browser_type,
    browser_proxy: values.browser_proxy,
    browser_viewport: values.browser_viewport
  };
  const retention = {
    run_retention_days: values.run_retention_days,
    screenshot_retention_days: values.screenshot_retention_days,
    trace_retention_days: values.trace_retention_days,
    response_retention_days: values.response_retention_days
  };
  if (tab === "alerts") return alerts;
  if (tab === "runtime") return runtime;
  if (tab === "browser") return browser;
  if (tab === "retention") return retention;
  return { alerts, runtime, browser, retention };
}

function cloneSettings(values: SettingsValues): SettingsValues {
  return JSON.parse(JSON.stringify(values)) as SettingsValues;
}
