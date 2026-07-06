import { Alert, Button, Card, Empty, Space, Statistic, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  AlertTriangle,
  BellRing,
  Clock3,
  History,
  Play,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Zap
} from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { CheckType, Overview, OverviewTrend, OverviewTrendSeries, Run, RuntimeStatus, SettingsValues } from "../types";
import { checkListPath, formatDate, formatDuration, runStatusLabel, runStatusTagColor } from "../utils";

const RunDetailDrawer = lazy(() => import("../components/RunDetailDrawer").then((module) => ({ default: module.RunDetailDrawer })));

export function OverviewPage() {
  const location = useLocation();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [settings, setSettings] = useState<SettingsValues | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [detailRunId, setDetailRunId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<number | null>(null);
  const navigate = useNavigate();

  async function load() {
    try {
      const [nextOverview, nextSettings, nextRuntime] = await Promise.all([api.overview(), api.settings(), api.runtime()]);
      setOverview(nextOverview);
      setSettings(nextSettings);
      setRuntime(nextRuntime);
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

  const confirmingCount = (overview?.suspected_failing_count || 0) + (overview?.suspected_recovery_count || 0);
  const staleOrUnknownCount = (overview?.unknown_count || 0) + (overview?.stale_count || 0);
  const abnormalCount = (overview?.failing_count || 0) + confirmingCount + staleOrUnknownCount;
  const hasIncident = abnormalCount > 0;
  const trends = overview?.trends || [];

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
    { title: "状态", dataIndex: "status", render: (_, run) => <Tag color={runStatusTagColor(run.status)}>{runStatusLabel(run.status)}</Tag>, width: 100 },
    { title: "耗时", dataIndex: "duration_ms", render: (value: number | null) => formatDuration(value), width: 110 },
    {
      title: "错误摘要",
      dataIndex: "error_message",
      width: 220,
      render: (_, run) => <OverviewRunIssueSummary run={run} />
    },
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
      {error && <Alert type="error" title={error} showIcon />}

      <section className={`overview-command ${hasIncident ? "overview-command-danger" : ""}`}>
        <div>
          <h2>{hasIncident ? "存在需要处理的监控异常" : "当前监控面健康"}</h2>
          <p>
            {hasIncident
              ? `故障 ${overview?.failing_count || 0}，疑似故障 ${overview?.suspected_failing_count || 0}，疑似恢复 ${overview?.suspected_recovery_count || 0}，无有效观测或过期 ${staleOrUnknownCount}。`
              : `页面和接口监控正常，今日完成 ${overview?.today_runs ?? 0} 次定时观测。`}
          </p>
        </div>
        <Button icon={<Settings2 size={16} />} onClick={() => navigate("/settings")}>
          告警设置
        </Button>
      </section>

      <section className="overview-status-grid">
        <Card className={`metric-card metric-compact ${settings ? alertChannelMetricClass(settings) : ""}`}>
          <span className="metric-icon"><BellRing size={17} /></span>
          <Statistic title="告警通道" value={settings ? alertChannel(settings) : "-"} />
          <div className="metric-detail">{settings ? alertChannelDetail(settings) : "-"}</div>
        </Card>
        <Card className="metric-card metric-compact metric-info">
          <span className="metric-icon"><Zap size={17} /></span>
          <Statistic title="调度器" value={runtime?.scheduler.running ? "运行中" : "未运行"} />
          <div className="metric-detail">
            {runtime ? `${runtime.scheduler.scheduled_checks} 个定时任务，逾期 ${runtime.scheduler.overdue_jobs}` : "-"}
          </div>
        </Card>
        <Card className="metric-card metric-compact">
          <span className="metric-icon"><Zap size={17} /></span>
          <Statistic title="执行器" value={runtime ? `${runtime.workers.running}/${runtime.workers.limit}` : "-"} />
          <div className="metric-detail">{runtime ? `排队 ${runtime.queue.queued}，浏览器 ${runtime.browser.running}/${runtime.browser.limit}` : "-"}</div>
        </Card>
        <Card className="metric-card metric-compact">
          <span className="metric-icon"><AlertTriangle size={17} /></span>
          <Statistic title="无有效观测/过期" value={staleOrUnknownCount} />
          <div className="metric-detail">无有效观测：尚未形成健康结论；过期：超过设定周期未更新</div>
        </Card>
      </section>

      <section className="metric-grid">
        <Card className="metric-card metric-info">
          <span className="metric-icon"><ShieldCheck size={19} /></span>
          <Statistic title="页面监控" value={overview?.ui_count ?? 0} />
        </Card>
        <Card className="metric-card metric-info">
          <span className="metric-icon"><ShieldCheck size={19} /></span>
          <Statistic title="接口监控" value={overview?.api_count ?? 0} />
        </Card>
        <Card className={`metric-card ${hasIncident ? "metric-danger" : "metric-success"}`}>
          <span className="metric-icon"><AlertTriangle size={19} /></span>
          <Statistic title="当前故障" value={overview?.failing_count ?? 0} />
        </Card>
        <Card className="metric-card">
          <span className="metric-icon"><History size={19} /></span>
          <Statistic title="今日定时观测" value={overview?.today_runs ?? 0} />
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

      {trends.length > 0 && (
        <section className="trend-grid">
          {trends.map((trend) => (
            <TrendCard key={trend.key} trend={trend} />
          ))}
        </section>
      )}

      <Card
        title="当前故障现场"
        extra={
          <Button icon={<History size={16} />} onClick={() => navigate("/runs")}>
            运行记录
          </Button>
        }
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={overview?.recent_failures || []}
          pagination={false}
          locale={{
            emptyText: <Empty description="暂无失败记录" />
          }}
          scroll={{ x: 980 }}
        />
      </Card>

      {detailRunId && (
        <Suspense fallback={null}>
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
        </Suspense>
      )}
    </div>
  );
}

function TrendCard({ trend }: { trend: OverviewTrend }) {
  const totalRuns = trend.series.reduce((sum, item) => sum + item.runs, 0);
  return (
    <Card className="trend-card">
      <div className="trend-card-header">
        <strong>{trend.label}</strong>
        <span>{totalRuns} 次运行</span>
      </div>
      <div className="trend-card-body">
        <div className="trend-series-table">
          <div className="trend-series-header">
            <span>类型</span>
            <span>运行</span>
            <span>成功率</span>
            <span>失败</span>
            <span>P50</span>
            <span>P95</span>
          </div>
          {trend.series.map((item) => (
            <TrendSeriesRow key={item.check_type} item={item} />
          ))}
        </div>
      </div>
    </Card>
  );
}

function TrendSeriesRow({ item }: { item: OverviewTrendSeries }) {
  return (
    <div className="trend-series-row">
      <span className="trend-series-label">{checkTypeLabel(item.check_type)}</span>
      <TrendValue label="运行" value={`${item.runs} 次`} />
      <TrendValue label="成功率" value={formatSuccessRate(item.success_rate)} />
      <TrendValue label="失败" value={`${item.failure_count} 次`} />
      <TrendValue label="P50" value={formatDuration(item.duration_p50_ms)} />
      <TrendValue label="P95" value={formatDuration(item.duration_p95_ms)} />
    </div>
  );
}

function TrendValue({ label, value }: { label: string; value: string }) {
  return (
    <span className="trend-value">
      <span className="trend-value-label">{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

function checkTypeLabel(type: CheckType): string {
  return type === "ui" ? "UI" : "API";
}

function formatSuccessRate(value: number | null | undefined): string {
  if (value == null) return "-";
  return `${value.toLocaleString("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

function OverviewRunIssueSummary({ run }: { run: Run }) {
  if (!run.error_message) return <span className="history-empty-cell">-</span>;
  return (
    <div className="history-issue-summary">
      <span>{run.error_message}</span>
      {Boolean(run.deduplicated_count) && <Tag>已压缩 {run.deduplicated_count} 条同错</Tag>}
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
