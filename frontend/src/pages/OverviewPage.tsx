import { Alert, App, Button, Card, Empty, Space, Statistic, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  AlertTriangle,
  BellRing,
  Clock3,
  Database,
  History,
  Monitor,
  Play,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Zap
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import {
  BatchRunActions,
  BatchRunBreakdown,
  batchRunMessage,
  batchRunNotificationType,
  summarizeBatchRuns
} from "../components/BatchRunAlert";
import { RunDetailDrawer } from "../components/RunDetailDrawer";
import { RunStatusBadge } from "../components/StatusBadge";
import type { CheckType, Overview, Run, SettingsValues } from "../types";
import { checkListPath, formatDate, formatDuration, intervalLabel } from "../utils";

export function OverviewPage() {
  const { message } = App.useApp();
  const location = useLocation();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [settings, setSettings] = useState<SettingsValues | null>(null);
  const [detailRunId, setDetailRunId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<number | null>(null);
  const [batchRunning, setBatchRunning] = useState<CheckType | null>(null);
  const navigate = useNavigate();

  async function load() {
    try {
      const [nextOverview, nextSettings] = await Promise.all([api.overview(), api.settings()]);
      setOverview(nextOverview);
      setSettings(nextSettings);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 15000);
    return () => window.clearInterval(timer);
  }, []);

  async function runNow(run: Run) {
    setRunningId(run.check_id);
    try {
      const latest = await api.runCheck(run.check_id);
      setDetailRunId(latest.id);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunningId(null);
    }
  }

  async function runAll(type: CheckType) {
    setBatchRunning(type);
    setError(null);
    try {
      const result = await api.runAll(type);
      const notice = summarizeBatchRuns(type, result.runs);
      message.open({
        key: `batch-run-${type}`,
        type: batchRunNotificationType(notice),
        duration: 8,
        content: (
          <div className="batch-run-toast">
            <strong>{batchRunMessage(notice)}</strong>
            <BatchRunBreakdown notice={notice} />
            <BatchRunActions
              notice={notice}
              onOpenHistory={(path) => navigate(path)}
              onOpenRun={setDetailRunId}
              emptyAction={
                <Button size="small" onClick={() => navigate(checkListPath(notice.type))}>
                  查看任务列表
                </Button>
              }
            />
          </div>
        )
      });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBatchRunning(null);
    }
  }

  const hasIncident = Boolean((overview?.failing_count || 0) > 0);

  const columns: ColumnsType<Run> = [
    { title: "时间", dataIndex: "started_at", render: (value: string) => formatDate(value), width: 180 },
    { title: "类型", dataIndex: "check_type", render: (value: string) => (value === "ui" ? "UI" : "API"), width: 80 },
    {
      title: "任务",
      dataIndex: "check_name",
      render: (value: string, run) => (
        <Button type="link" className="table-link" onClick={() => navigate(checkListPath(run.check_type, run.check_id))}>
          {value}
        </Button>
      )
    },
    { title: "状态", dataIndex: "status", render: (_, run) => <RunStatusBadge status={run.status} />, width: 100 },
    { title: "耗时", dataIndex: "duration_ms", render: (value: number | null) => formatDuration(value), width: 110 },
    { title: "错误摘要", dataIndex: "error_message", ellipsis: true },
    { title: "连续失败", dataIndex: "consecutive_failures", render: (value?: number) => value || "-", width: 110 },
    {
      title: "操作",
      width: 132,
      render: (_, run) => (
        <Space>
          <Button size="small" title="查看详情" aria-label="查看详情" icon={<History size={15} />} onClick={() => setDetailRunId(run.id)} />
          <Button size="small" title="立即执行" aria-label="立即执行" icon={<Play size={15} />} loading={runningId === run.check_id} onClick={() => runNow(run)} />
        </Space>
      )
    }
  ];

  return (
    <div className="page-content">
      {error && <Alert type="error" message={error} showIcon />}

      <section className={`overview-command ${hasIncident ? "overview-command-danger" : ""}`}>
        <div>
          <h2>{hasIncident ? "存在失败任务，需要处理" : "当前监控面正常"}</h2>
          <p>
            {hasIncident
              ? `${overview?.failing_count || 0} 个启用任务处于失败态，建议优先查看失败现场。`
              : `UI/API 探活已接入，今日已执行 ${overview?.today_runs ?? 0} 次。`}
          </p>
        </div>
        <Space wrap>
          <Button icon={<Play size={16} />} loading={batchRunning === "ui"} onClick={() => runAll("ui")}>
            执行全部 UI
          </Button>
          <Button icon={<Play size={16} />} loading={batchRunning === "api"} onClick={() => runAll("api")}>
            执行全部 API
          </Button>
          <Link to="/settings">
            <Button icon={<Settings2 size={16} />}>告警设置</Button>
          </Link>
        </Space>
      </section>

      <section className="overview-status-grid">
        <Card className={`metric-card metric-compact ${settings ? alertChannelMetricClass(settings) : ""}`}>
          <span className="metric-icon"><BellRing size={17} /></span>
          <Statistic title="告警通道" value={settings ? alertChannel(settings) : "-"} />
          <div className="metric-detail">{settings ? alertChannelDetail(settings) : "-"}</div>
        </Card>
        <Card className="metric-card metric-compact metric-info">
          <span className="metric-icon"><Zap size={17} /></span>
          <Statistic title="默认调度" value={settings ? intervalLabel(settings.default_interval_seconds) : "-"} />
          <div className="metric-detail">
            {settings ? `并发 ${settings.max_concurrency}，UI ${settings.max_ui_concurrency}，队列 ${settings.max_queue_size}` : "-"}
          </div>
        </Card>
        <Card className="metric-card metric-compact">
          <span className="metric-icon"><Monitor size={17} /></span>
          <Statistic title="浏览器运行" value={settings?.browser_type || "-"} />
          <div className="metric-detail">{settings ? `${settings.browser_headless ? "Headless" : "可视化"}，${settings.browser_viewport}` : "-"}</div>
        </Card>
        <Card className="metric-card metric-compact">
          <span className="metric-icon"><Database size={17} /></span>
          <Statistic title="数据保留" value={settings ? `${settings.run_retention_days} 天` : "-"} />
          <div className="metric-detail">{settings ? `Trace ${settings.trace_retention_days} 天，响应 ${settings.response_retention_days} 天` : "-"}</div>
        </Card>
      </section>

      <section className="metric-grid">
        <Card className="metric-card metric-info">
          <span className="metric-icon"><ShieldCheck size={19} /></span>
          <Statistic title="UI 任务" value={overview?.ui_count ?? 0} />
        </Card>
        <Card className="metric-card metric-info">
          <span className="metric-icon"><ShieldCheck size={19} /></span>
          <Statistic title="API 任务" value={overview?.api_count ?? 0} />
        </Card>
        <Card className={`metric-card ${hasIncident ? "metric-danger" : "metric-success"}`}>
          <span className="metric-icon"><AlertTriangle size={19} /></span>
          <Statistic title="当前失败" value={overview?.failing_count ?? 0} />
        </Card>
        <Card className="metric-card">
          <span className="metric-icon"><History size={19} /></span>
          <Statistic title="今日执行" value={overview?.today_runs ?? 0} />
        </Card>
        <Card className="metric-card metric-wide">
          <span className="metric-icon"><Clock3 size={19} /></span>
          <Statistic title="最近执行" value={overview?.latest_run ? formatDate(overview.latest_run.started_at) : "未执行"} />
        </Card>
        <Card className="metric-card metric-wide">
          <span className="metric-icon"><RotateCcw size={19} /></span>
          <Statistic title="最近恢复" value={overview?.latest_recovered?.name || "暂无恢复"} />
          {overview?.latest_recovered && <div className="metric-detail">{formatDate(overview.latest_recovered.last_success_at)}</div>}
        </Card>
      </section>

      <Card
        title="失败现场"
        extra={
          <Link to="/runs">
            <Button icon={<History size={16} />}>执行历史</Button>
          </Link>
        }
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={overview?.recent_failures || []}
          pagination={false}
          locale={{
            emptyText: (
              <Empty description="暂无失败记录">
                <Space wrap>
                  <Button icon={<Play size={16} />} loading={batchRunning === "ui"} onClick={() => runAll("ui")}>
                    执行全部 UI
                  </Button>
                  <Button icon={<Play size={16} />} loading={batchRunning === "api"} onClick={() => runAll("api")}>
                    执行全部 API
                  </Button>
                </Space>
              </Empty>
            )
          }}
          scroll={{ x: 980 }}
        />
      </Card>

      <RunDetailDrawer
        runId={detailRunId}
        onClose={() => setDetailRunId(null)}
        returnTo={`${location.pathname}${location.search}`}
        onRerun={async (run) => {
          const latest = await api.rerun(run.id);
          setDetailRunId(latest.id);
          await load();
        }}
      />
    </div>
  );
}

function alertChannel(settings: SettingsValues): string {
  if (!settings.alerts_enabled) return "未启用";
  const readyChannels = readyNotificationChannels(settings);
  if (readyChannels.length === 0) return "未配置";
  const names = readyChannels.map((channel) => channel.name || channelTypeLabel(channel.type));
  return names.length > 2 ? `${names.slice(0, 2).join("、")} 等 ${names.length} 个` : names.join("、");
}

function alertChannelDetail(settings: SettingsValues): string {
  if (!settings.alerts_enabled) return "未启用";
  const total = settings.notification_channels.length;
  const ready = readyNotificationChannels(settings).length;
  if (total === 0) return "暂无通知渠道";
  if (ready === 0) return "缺少启用且填写 URL 的渠道";
  return `${ready}/${total} 个渠道可发送`;
}

function alertChannelMetricClass(settings: SettingsValues): string {
  if (!settings.alerts_enabled) return "";
  return readyNotificationChannels(settings).length > 0 ? "metric-success" : "metric-warning";
}

function readyNotificationChannels(settings: SettingsValues) {
  return settings.notification_channels.filter((channel) => channel.enabled && channel.webhook_url.trim());
}

function channelTypeLabel(type: string): string {
  return (
    {
      feishu: "飞书",
      wecom: "企业微信",
      dingtalk: "钉钉"
    }[type] || type
  );
}
