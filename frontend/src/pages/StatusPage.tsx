import { App, Button, Card, Empty, Skeleton, Space, Statistic, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { StatusPageCheck, StatusPageIncident, StatusPageSnapshot } from "../types";
import { formatDate, formatDuration, runStatusLabel, runStatusTagColor } from "../utils";

export function StatusPage() {
  const { message } = App.useApp();
  const [snapshot, setSnapshot] = useState<StatusPageSnapshot | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      setSnapshot(await api.statusPage());
    } catch (err) {
      message.error((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const checkColumns: ColumnsType<StatusPageCheck> = [
    {
      title: "任务",
      dataIndex: "name",
      render: (value: string, check) => (
        <Space orientation="vertical" size={2}>
          <span>{value}</span>
          <Space size={6} wrap>
            <Tag>{check.type === "ui" ? "UI" : "API"}</Tag>
            {check.tags
              .split(",")
              .map((tag) => tag.trim())
              .filter(Boolean)
              .slice(0, 3)
              .map((tag) => (
                <Tag key={tag}>{tag}</Tag>
              ))}
          </Space>
        </Space>
      )
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 120,
      render: (_, check) => <Tag color={checkStatusColor(check)}>{checkStatusLabel(check)}</Tag>
    },
    {
      title: "最近运行",
      dataIndex: "last_run_at",
      width: 180,
      render: (value?: string | null) => formatDate(value)
    },
    {
      title: "状态摘要",
      dataIndex: "last_error",
      ellipsis: true,
      render: (value?: string | null) => value || "-"
    }
  ];

  const incidentColumns: ColumnsType<StatusPageIncident> = [
    {
      title: "时间",
      dataIndex: "started_at",
      width: 180,
      render: (value: string) => formatDate(value)
    },
    {
      title: "任务",
      dataIndex: "check_name",
      render: (value: string, incident) => (
        <Space size={6} wrap>
          <span>{value}</span>
          <Tag>{incident.check_type === "ui" ? "UI" : "API"}</Tag>
        </Space>
      )
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 120,
      render: (value: StatusPageIncident["status"]) => <Tag color={runStatusTagColor(value)}>{runStatusLabel(value)}</Tag>
    },
    {
      title: "失败来源",
      dataIndex: "failure_kind",
      width: 110,
      render: (value?: string | null) => failureKindTag(value)
    },
    {
      title: "耗时",
      dataIndex: "duration_ms",
      width: 100,
      render: (value?: number | null) => formatDuration(value)
    },
    {
      title: "摘要",
      dataIndex: "error_message",
      ellipsis: true,
      render: (value?: string | null) => value || "-"
    }
  ];

  if (loading || !snapshot) {
    return (
      <div className="page-content status-page">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }

  return (
    <div className="page-content status-page">
      <section className="status-command-bar">
        <div>
          <h2>内网状态</h2>
          <p>更新时间 {formatDate(snapshot.generated_at)}</p>
        </div>
        <Button icon={<RefreshCw size={16} />} onClick={load}>
          刷新
        </Button>
      </section>

      <section className="status-summary-grid">
        <Card className="summary-card">
          <Statistic title="任务总数" value={snapshot.summary.checks_total} />
        </Card>
        <Card className="summary-card">
          <Statistic title="启用任务" value={snapshot.summary.checks_enabled} />
        </Card>
        <Card className={snapshot.summary.checks_failing > 0 ? "summary-card metric-danger" : "summary-card metric-success"}>
          <Statistic title="失败任务" value={snapshot.summary.checks_failing} />
        </Card>
        <Card className="summary-card">
          <Statistic title="今日运行" value={snapshot.summary.runs_today} />
        </Card>
      </section>

      <section className="status-section">
        <div className="section-heading">
          <h3>任务状态</h3>
        </div>
        {snapshot.checks.length === 0 ? (
          <Empty description="暂无任务" />
        ) : (
          <Table rowKey="id" columns={checkColumns} dataSource={snapshot.checks} pagination={{ pageSize: 12 }} />
        )}
      </section>

      <section className="status-section">
        <div className="section-heading">
          <h3>最近异常</h3>
        </div>
        {snapshot.recent_incidents.length === 0 ? (
          <Empty description="暂无异常" />
        ) : (
          <Table rowKey="id" columns={incidentColumns} dataSource={snapshot.recent_incidents} pagination={{ pageSize: 8 }} />
        )}
      </section>
    </div>
  );
}

function checkStatusLabel(check: StatusPageCheck): string {
  if (!check.enabled) return "已停用";
  if (check.status === "healthy" || check.status === "ok") return "健康";
  if (check.status === "failing" || check.status === "failed") return "故障";
  if (check.status === "suspected_failing") return "疑似故障";
  if (check.status === "suspected_recovery") return "疑似恢复";
  if (check.status === "unknown") return "无有效观测";
  if (check.status === "stale") return "观测过期";
  if (check.status === "timeout") return "超时";
  if (check.status === "never") return "未运行";
  return "未知状态";
}

function checkStatusColor(check: StatusPageCheck): string {
  if (!check.enabled) return "default";
  if (check.status === "healthy" || check.status === "ok") return "success";
  if (check.status === "failing" || check.status === "failed" || check.status === "timeout") return "error";
  if (check.status === "suspected_failing" || check.status === "suspected_recovery" || check.status === "stale") return "warning";
  if (check.status === "unknown") return "processing";
  return "default";
}

function failureKindTag(value?: string | null) {
  if (value === "target") return <Tag color="red">目标页面/API</Tag>;
  if (value === "runner") return <Tag color="orange">执行环境</Tag>;
  return <Tag>未记录</Tag>;
}
