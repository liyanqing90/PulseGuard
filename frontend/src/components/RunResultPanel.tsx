import { Alert, Button, Descriptions, Empty, Image as AntImage, Skeleton, Space, Table, Tabs, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Archive, Download, ExternalLink, FileText, Image as ImageIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import type { Run, RunComparison, RunComparisonAssertion, RunComparisonField, RunFailureSummary } from "../types";
import { artifactHref, formatDate, formatDuration, parseSnapshot, runStatusLabel, runStatusTagColor } from "../utils";
import { StructuredViewer } from "./StructuredViewer";

type RunResultMode = "detail" | "debug";

interface AssertionResult {
  rule?: string;
  path?: string;
  status?: "ok" | "failed" | string;
  actual?: unknown;
  operator?: string;
  expected?: unknown;
  message?: string;
}

interface Props {
  run: Run | null;
  mode?: RunResultMode;
}

export function RunResultPanel({ run, mode = "detail" }: Props) {
  const [activeTab, setActiveTab] = useState("overview");
  const [comparison, setComparison] = useState<RunComparison | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [failureSummary, setFailureSummary] = useState<RunFailureSummary | null>(null);
  const [failureSummaryLoading, setFailureSummaryLoading] = useState(false);
  const [failureSummaryError, setFailureSummaryError] = useState<string | null>(null);
  const requestSnapshot = useMemo(() => parseSnapshot(run?.request_snapshot), [run?.request_snapshot]);
  const responseSnapshot = useMemo(() => parseSnapshot(run?.response_snapshot), [run?.response_snapshot]);
  const responseBody = useMemo(() => extractResponseBody(responseSnapshot), [responseSnapshot]);
  const assertionResults = useMemo(() => extractAssertionResults(responseSnapshot), [responseSnapshot]);
  const showComparison = Boolean(run && mode === "detail" && run.check_id > 0 && ["failed", "timeout"].includes(run.status));
  const showFailureSummary = Boolean(run && mode === "detail" && run.check_id > 0 && ["failed", "timeout", "skipped"].includes(run.status));
  const showDiagnostics = mode === "debug";

  useEffect(() => {
    setActiveTab(defaultRunTab(run, mode, responseSnapshot, assertionResults.length));
  }, [assertionResults.length, mode, responseSnapshot, run]);

  useEffect(() => {
    if (!run || !showComparison) {
      setComparison(null);
      setComparisonError(null);
      setComparisonLoading(false);
      return;
    }
    let cancelled = false;
    setComparisonLoading(true);
    setComparisonError(null);
    api
      .runComparison(run.id)
      .then((value) => {
        if (!cancelled) setComparison(value);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setComparison(null);
          setComparisonError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setComparisonLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [run?.id, showComparison]);

  useEffect(() => {
    if (!run || !showFailureSummary) {
      setFailureSummary(null);
      setFailureSummaryError(null);
      setFailureSummaryLoading(false);
      return;
    }
    let cancelled = false;
    setFailureSummaryLoading(true);
    setFailureSummaryError(null);
    api
      .runFailureSummary(run.id)
      .then((value) => {
        if (!cancelled) setFailureSummary(value);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setFailureSummary(null);
          setFailureSummaryError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setFailureSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [run?.id, showFailureSummary]);

  if (!run) {
    return <Empty description={false} />;
  }

  const isDraftRun = run.check_id <= 0;
  const overviewPanel = (
    <Space orientation="vertical" size={14} className="drawer-stack">
      <Descriptions bordered column={2} size="small">
        <Descriptions.Item label="状态">
          <RunStatusTag status={run.status} />
        </Descriptions.Item>
        <Descriptions.Item label="任务 ID">{isDraftRun ? "草稿调试" : run.check_id}</Descriptions.Item>
        <Descriptions.Item label="任务名称">{run.check_name}</Descriptions.Item>
        <Descriptions.Item label="运行记录">#{run.id}</Descriptions.Item>
        <Descriptions.Item label="开始时间">{formatDate(run.started_at)}</Descriptions.Item>
        <Descriptions.Item label="结束时间">{formatDate(run.finished_at)}</Descriptions.Item>
        <Descriptions.Item label="耗时">{formatDuration(run.duration_ms)}</Descriptions.Item>
        <Descriptions.Item label="连续失败">{run.consecutive_failures || "-"}</Descriptions.Item>
        <Descriptions.Item label="失败归因">{failureKindTag(run.failure_kind)}</Descriptions.Item>
        <Descriptions.Item label="Runner">{runnerSummary(run)}</Descriptions.Item>
        <Descriptions.Item label="Runner 地址">{run.runner_address || "-"}</Descriptions.Item>
        <Descriptions.Item label="网络区域">{run.runner_region || "-"}</Descriptions.Item>
        <Descriptions.Item label="浏览器版本">{run.runner_browser_version || "-"}</Descriptions.Item>
      </Descriptions>
    </Space>
  );
  const errorPanel = (
    <Space orientation="vertical" size={12} className="drawer-stack">
      {run.error_message ? (
        <Alert type="error" message="错误摘要" description={detailErrorText(run, mode)} showIcon />
      ) : (
        <Tag color="success">{mode === "debug" ? "调试无错误" : "运行无错误"}</Tag>
      )}
      {showDiagnostics && <StructuredViewer title="错误堆栈" value={run.error_stack} defaultMode="text" />}
    </Space>
  );
  const comparisonTab = showComparison
    ? [
        {
          key: "compare",
          label: "对比",
          children: <RunComparisonPanel comparison={comparison} error={comparisonError} loading={comparisonLoading} />
        }
      ]
    : [];
  const summaryTab = showFailureSummary
    ? [
        {
          key: "summary",
          label: "摘要",
          children: <FailureSummaryPanel summary={failureSummary} error={failureSummaryError} loading={failureSummaryLoading} />
        }
      ]
    : [];
  const apiTabs = [
    ...summaryTab,
    ...comparisonTab,
    { key: "overview", label: "概览", children: overviewPanel },
    ...(assertionResults.length ? [{ key: "assertions", label: "校验", children: <AssertionResultsPanel results={assertionResults} /> }] : []),
    ...(showDiagnostics
      ? [
          { key: "request", label: "请求", children: <StructuredViewer title="请求快照" value={requestSnapshot} defaultMode="json" /> },
          {
            key: "response",
            label: "响应",
            children: (
              <Space orientation="vertical" size={12} className="drawer-stack">
                <StructuredViewer title="响应快照" value={responseSnapshot} defaultMode="json" />
                <StructuredViewer title="响应体" value={responseBody} defaultMode="auto" />
              </Space>
            )
          },
          { key: "logs", label: "日志", children: <StructuredViewer title="日志" value={run.logs} defaultMode="text" /> }
        ]
      : []),
    { key: "error", label: "错误", children: errorPanel }
  ];
  const uiTabs = [
    ...summaryTab,
    ...comparisonTab,
    { key: "overview", label: "概览", children: overviewPanel },
    ...(assertionResults.length ? [{ key: "assertions", label: "校验", children: <AssertionResultsPanel results={assertionResults} /> }] : []),
    { key: "evidence", label: "页面证据", children: <EvidencePanel run={run} diagnosticsEnabled={showDiagnostics} onOpenResponse={() => setActiveTab("response")} /> },
    ...(showDiagnostics ? [{ key: "logs", label: "日志", children: <StructuredViewer title="日志" value={run.logs} defaultMode="text" /> }] : []),
    { key: "error", label: "错误", children: errorPanel }
  ];
  const tabItems = run.check_type === "api" ? apiTabs : uiTabs;
  const content = (
    <Space orientation="vertical" size={16} className="drawer-stack">
      <section className={`run-detail-summary run-detail-${run.status}`}>
        <div className="run-detail-title">
          <RunStatusTag status={run.status} />
          {isDraftRun && <Tag color="blue">草稿调试</Tag>}
          <div>
            <strong>{run.check_name}</strong>
            <span>运行记录 #{run.id}</span>
          </div>
        </div>
        <div className="run-detail-meta">
          <MetaItem label="类型" value={run.check_type === "ui" ? "UI" : "API"} />
          <MetaItem label="耗时" value={formatDuration(run.duration_ms)} />
          <MetaItem label="开始" value={formatDate(run.started_at)} />
          <MetaItem label="结束" value={formatDate(run.finished_at)} />
        </div>
      </section>

      {run.error_message && <Alert type="error" message="错误摘要" description={detailErrorText(run, mode)} showIcon />}

      <Tabs
        activeKey={activeTab}
        className={`run-detail-tabs ${mode === "debug" ? "debug-result-tabs" : ""}`}
        moreIcon={<span className="tabs-more-label">更多</span>}
        onChange={setActiveTab}
        items={tabItems}
      />
    </Space>
  );

  if (mode === "debug") {
    return (
      <section className="run-result-panel">
        <div className="section-title">
          <h3>调试结果</h3>
          <RunStatusTag status={run.status} />
        </div>
        {content}
      </section>
    );
  }

  return content;
}

function FailureSummaryPanel({
  error,
  loading,
  summary
}: {
  error: string | null;
  loading: boolean;
  summary: RunFailureSummary | null;
}) {
  if (loading) return <Skeleton active paragraph={{ rows: 4 }} />;
  if (error) return <Alert type="error" message={error} showIcon />;
  if (!summary) return <Empty description="暂无失败摘要" />;
  return (
    <Space orientation="vertical" size={12} className="drawer-stack">
      <Alert type={summary.failure_kind === "runner" ? "warning" : "error"} message={summary.summary} showIcon />
      <Descriptions bordered column={2} size="small">
        {summary.signals.map((signal) => (
          <Descriptions.Item label={signal.label} key={signal.label}>
            {formatAssertionValue(signal.value)}
          </Descriptions.Item>
        ))}
      </Descriptions>
      <div className="failure-summary-steps">
        {summary.next_steps.map((step) => (
          <Tag key={step}>{step}</Tag>
        ))}
      </div>
    </Space>
  );
}

function RunComparisonPanel({
  comparison,
  error,
  loading
}: {
  comparison: RunComparison | null;
  error: string | null;
  loading: boolean;
}) {
  if (loading) {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }
  if (error) {
    return <Alert type="error" message="对比加载失败" description={error} showIcon />;
  }
  if (!comparison) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对比数据" />;
  }
  if (!comparison.available) {
    return <Alert type="info" message="暂无成功基线" description={comparison.message || "同一任务暂无可对比的成功运行记录"} showIcon />;
  }

  return (
    <Space orientation="vertical" size={14} className="drawer-stack">
      <Descriptions bordered column={2} size="small">
        <Descriptions.Item label="当前运行">#{comparison.current_run?.id || "-"}</Descriptions.Item>
        <Descriptions.Item label="成功基线">#{comparison.baseline_run?.id || "-"}</Descriptions.Item>
        <Descriptions.Item label="当前时间">{formatDate(comparison.current_run?.finished_at || comparison.current_run?.started_at)}</Descriptions.Item>
        <Descriptions.Item label="基线时间">{formatDate(comparison.baseline_run?.finished_at || comparison.baseline_run?.started_at)}</Descriptions.Item>
        <Descriptions.Item label="当前耗时">{formatDuration(comparison.current_run?.duration_ms)}</Descriptions.Item>
        <Descriptions.Item label="基线耗时">{formatDuration(comparison.baseline_run?.duration_ms)}</Descriptions.Item>
      </Descriptions>
      <ComparisonFieldsTable fields={comparison.fields || []} />
      <ComparisonAssertionsTable assertions={comparison.assertions || []} />
    </Space>
  );
}

function ComparisonFieldsTable({ fields }: { fields: RunComparisonField[] }) {
  if (!fields.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无字段差异" />;
  }
  const columns: ColumnsType<RunComparisonField> = [
    {
      title: "字段",
      dataIndex: "label",
      width: 110,
      render: (value: string, item) => (
        <Space size={6}>
          <span>{value}</span>
          {item.changed && <Tag color="warning">变化</Tag>}
        </Space>
      )
    },
    {
      title: "失败运行",
      dataIndex: "current",
      render: (value: unknown) => <code className="comparison-value">{formatAssertionValue(value)}</code>
    },
    {
      title: "最近成功",
      dataIndex: "baseline",
      render: (value: unknown) => <code className="comparison-value">{formatAssertionValue(value)}</code>
    }
  ];
  return <Table rowKey="key" size="small" pagination={false} columns={columns} dataSource={fields} scroll={{ x: 720 }} />;
}

function ComparisonAssertionsTable({ assertions }: { assertions: RunComparisonAssertion[] }) {
  if (!assertions.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="关键断言无差异" />;
  }
  const columns: ColumnsType<RunComparisonAssertion> = [
    {
      title: "断言",
      dataIndex: "rule",
      width: 190,
      render: (value: string, item) => (
        <div className="assertion-result-rule">
          <strong>{value || "-"}</strong>
          {item.path && <span>{item.path}</span>}
        </div>
      )
    },
    {
      title: "失败运行",
      dataIndex: "current_status",
      render: (value: string | null | undefined, item) => (
        <ComparisonAssertionCell
          status={value}
          actual={item.current_actual}
          operator={item.current_operator}
          expected={item.current_expected}
          message={item.current_message}
        />
      )
    },
    {
      title: "最近成功",
      dataIndex: "baseline_status",
      render: (value: string | null | undefined, item) => (
        <ComparisonAssertionCell
          status={value}
          actual={item.baseline_actual}
          operator={item.baseline_operator}
          expected={item.baseline_expected}
          message={item.baseline_message}
        />
      )
    }
  ];
  return <Table rowKey="key" size="small" pagination={false} columns={columns} dataSource={assertions} scroll={{ x: 860 }} />;
}

function ComparisonAssertionCell({
  status,
  actual,
  operator,
  expected,
  message
}: {
  status?: string | null;
  actual?: unknown;
  operator?: string | null;
  expected?: unknown;
  message?: string | null;
}) {
  return (
    <div className="comparison-assertion-cell">
      <Tag color={assertionStatusColor(status)}>{assertionStatusLabel(status)}</Tag>
      <div className="comparison-assertion-values">
        <span className="comparison-assertion-field">
          <span className="comparison-assertion-label">实际</span>
          <code>{formatAssertionValue(actual)}</code>
        </span>
        <span className="comparison-assertion-field">
          <span className="comparison-assertion-label">关系</span>
          <code>{formatOperatorValue(operator)}</code>
        </span>
        <span className="comparison-assertion-field">
          <span className="comparison-assertion-label">预期</span>
          <code>{formatAssertionValue(expected)}</code>
        </span>
      </div>
      {message && <span className="comparison-assertion-message">{message}</span>}
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AssertionResultsPanel({ results }: { results: AssertionResult[] }) {
  if (!results.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={false} />;
  }

  const columns: ColumnsType<AssertionResult> = [
    {
      title: "结果",
      dataIndex: "status",
      width: 86,
      render: (value: AssertionResult["status"]) => <Tag color={value === "ok" ? "success" : "error"}>{value === "ok" ? "通过" : "失败"}</Tag>
    },
    {
      title: "校验项",
      dataIndex: "rule",
      width: 180,
      render: (value: string | undefined, item) => (
        <div className="assertion-result-rule">
          <strong>{value || "-"}</strong>
          {item.path && <span>{item.path}</span>}
        </div>
      )
    },
    {
      title: "实际值",
      dataIndex: "actual",
      render: (value: unknown) => <code className="assertion-result-value">{formatAssertionValue(value)}</code>
    },
    {
      title: "关系",
      dataIndex: "operator",
      width: 76,
      align: "center"
    },
    {
      title: "预期值",
      dataIndex: "expected",
      render: (value: unknown) => <code className="assertion-result-value">{formatAssertionValue(value)}</code>
    },
    {
      title: "说明",
      dataIndex: "message",
      render: (value: string | undefined) => value || "-"
    }
  ];

  return (
    <Table
      rowKey={(_, index) => String(index)}
      size="small"
      pagination={false}
      columns={columns}
      dataSource={results}
      className="assertion-results-table"
      scroll={{ x: 880 }}
    />
  );
}

function EvidencePanel({
  diagnosticsEnabled,
  onOpenResponse,
  run
}: {
  diagnosticsEnabled: boolean;
  onOpenResponse: () => void;
  run: Run;
}) {
  const screenshotHref = artifactHref(run.screenshot_path);
  const traceHref = diagnosticsEnabled ? artifactHref(run.trace_path) : null;
  const responseHref = diagnosticsEnabled ? artifactHref(run.response_path) : null;
  const hasArtifacts = Boolean(screenshotHref || traceHref || responseHref);

  return (
    <section className="run-evidence-panel">
      <div className="run-evidence-header">
        <div>
          <strong>现场留证</strong>
          <span>{hasArtifacts ? "已归档" : "无产物"}</span>
        </div>
        {diagnosticsEnabled && responseHref && (
          <Button size="small" icon={<FileText size={15} />} onClick={onOpenResponse}>
            查看响应
          </Button>
        )}
      </div>

      <div className={`run-evidence-grid ${screenshotHref ? "" : "run-evidence-grid-empty"}`}>
        <div className="run-screenshot-preview">
          {screenshotHref ? (
            <>
              <AntImage
                alt={`${run.check_name} 失败截图`}
                className="run-screenshot-image"
                preview={{ mask: "查看大图" }}
                src={screenshotHref}
              />
              <div className="run-screenshot-caption">
                <ImageIcon size={15} />
                <span>失败截图</span>
              </div>
            </>
          ) : (
            <div className="run-evidence-empty">
              <ImageIcon size={18} />
              <span>暂无截图</span>
            </div>
          )}
        </div>

        <div className="run-evidence-actions">
          <EvidenceAction
            icon={<ImageIcon size={16} />}
            title="截图"
            description={screenshotHref ? "可预览" : "未生成"}
            href={screenshotHref}
            actionLabel="打开原图"
          />
          {diagnosticsEnabled && (
            <>
              <EvidenceAction
                icon={<Archive size={16} />}
                title="Trace"
                description={traceHref ? "可下载" : "未生成"}
                href={traceHref}
                actionLabel="下载 Trace"
                download
              />
              <EvidenceAction
                icon={<FileText size={16} />}
                title="Response"
                description={responseHref ? "已归档" : "未生成"}
                href={responseHref}
                actionLabel="下载文件"
                download
              />
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function EvidenceAction({
  actionLabel,
  description,
  download,
  href,
  icon,
  title
}: {
  actionLabel: string;
  description: string;
  download?: boolean;
  href: string | null;
  icon: ReactNode;
  title: string;
}) {
  return (
    <div className={`run-evidence-action ${href ? "" : "run-evidence-action-disabled"}`}>
      <span className="run-evidence-action-icon">{icon}</span>
      <div>
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      {href ? (
        <Button size="small" href={href} target="_blank" download={download || undefined} icon={download ? <Download size={14} /> : <ExternalLink size={14} />}>
          {actionLabel}
        </Button>
      ) : (
        <Tag>未生成</Tag>
      )}
    </div>
  );
}

function extractResponseBody(value: unknown): unknown {
  if (value && typeof value === "object" && "body" in value) {
    return (value as { body?: unknown }).body;
  }
  return null;
}

function extractAssertionResults(value: unknown): AssertionResult[] {
  if (value && typeof value === "object" && "assertions" in value) {
    const assertions = (value as { assertions?: unknown }).assertions;
    return Array.isArray(assertions) ? (assertions.filter((item) => item && typeof item === "object") as AssertionResult[]) : [];
  }
  return [];
}

function formatAssertionValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function RunStatusTag({ status }: { status: Run["status"] }) {
  return <Tag color={runStatusTagColor(status)}>{runStatusLabel(status)}</Tag>;
}

function detailErrorText(run: Run, mode: RunResultMode): string {
  if (mode === "debug") return run.error_message || "-";
  if (run.failure_kind === "runner") return "Runner 执行异常，请查看失败摘要中的建议动作。";
  if (run.status === "timeout") return "运行超时，请查看失败摘要和最近成功对比。";
  if (run.status === "skipped") return "本次运行已跳过，请查看失败摘要中的跳过原因。";
  return "运行失败，请查看失败摘要、断言结果和最近成功对比。";
}

function formatOperatorValue(value?: string | null): string {
  if (!value) return "-";
  const labels: Record<string, string> = {
    eq: "=",
    ne: "!=",
    gt: ">",
    gte: ">=",
    lt: "<",
    lte: "<=",
    contains: "包含",
    exists: "存在"
  };
  if (labels[value]) return labels[value];
  if (/^[=!<>]+$/.test(value) || /[\u4e00-\u9fa5]/.test(value)) return value;
  return "自定义";
}

function assertionStatusLabel(value?: string | null): string {
  if (!value) return "缺失";
  const labels: Record<string, string> = {
    ok: "通过",
    failed: "失败",
    timeout: "超时",
    skipped: "跳过"
  };
  return labels[value] || "异常";
}

function assertionStatusColor(value?: string | null): string {
  if (!value) return "default";
  if (value === "ok") return "success";
  if (value === "skipped") return "default";
  return "error";
}

function runnerSummary(run: Run): string {
  const name = (run.runner_name || "local").trim();
  const region = (run.runner_region || "").trim();
  return region && region !== name ? `${name} · ${region}` : name;
}

function failureKindTag(value?: string | null) {
  if (value === "target") return <Tag color="red">目标</Tag>;
  if (value === "runner") return <Tag color="orange">Runner</Tag>;
  return <Tag>无</Tag>;
}

function defaultRunTab(run: Run | null, mode: RunResultMode, responseSnapshot: unknown, assertionCount: number): string {
  if (!run) return "overview";
  if (mode === "detail" && run.check_id > 0 && ["failed", "timeout", "skipped"].includes(run.status)) return "summary";
  if (mode === "detail" && run.check_id > 0 && ["failed", "timeout"].includes(run.status)) return "compare";
  if (mode === "debug" && assertionCount > 0) return "assertions";
  if (mode === "debug" && run.check_type === "api" && responseSnapshot) return "response";
  if (mode === "debug" && run.error_message) return "error";
  return "overview";
}
