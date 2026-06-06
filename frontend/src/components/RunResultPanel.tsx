import { Alert, Descriptions, Empty, Image as AntImage, Space, Table, Tabs, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Archive, Download, ExternalLink, FileText, Image as ImageIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { Run } from "../types";
import { artifactHref, formatDate, formatDuration, parseSnapshot } from "../utils";
import { AppButton as Button } from "./common/AppButton";
import { RunStatusBadge } from "./StatusBadge";
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
  const requestSnapshot = useMemo(() => parseSnapshot(run?.request_snapshot), [run?.request_snapshot]);
  const responseSnapshot = useMemo(() => parseSnapshot(run?.response_snapshot), [run?.response_snapshot]);
  const responseBody = useMemo(() => extractResponseBody(responseSnapshot), [responseSnapshot]);
  const assertionResults = useMemo(() => extractAssertionResults(responseSnapshot), [responseSnapshot]);

  useEffect(() => {
    setActiveTab(defaultRunTab(run, mode, responseSnapshot, assertionResults.length));
  }, [assertionResults.length, mode, responseSnapshot, run]);

  if (!run) {
    return <Empty description="运行记录不存在" />;
  }

  const isDraftRun = run.check_id <= 0;
  const overviewPanel = (
    <Space direction="vertical" size={14} className="drawer-stack">
      <Descriptions bordered column={2} size="small">
        <Descriptions.Item label="状态">
          <RunStatusBadge status={run.status} />
        </Descriptions.Item>
        <Descriptions.Item label="任务 ID">{isDraftRun ? "草稿调试" : run.check_id}</Descriptions.Item>
        <Descriptions.Item label="任务名称">{run.check_name}</Descriptions.Item>
        <Descriptions.Item label="运行记录">#{run.id}</Descriptions.Item>
        <Descriptions.Item label="开始时间">{formatDate(run.started_at)}</Descriptions.Item>
        <Descriptions.Item label="结束时间">{formatDate(run.finished_at)}</Descriptions.Item>
        <Descriptions.Item label="耗时">{formatDuration(run.duration_ms)}</Descriptions.Item>
        <Descriptions.Item label="连续失败">{run.consecutive_failures || "-"}</Descriptions.Item>
      </Descriptions>
    </Space>
  );
  const errorPanel = (
    <Space direction="vertical" size={12} className="drawer-stack">
      {run.error_message ? (
        <Alert type="error" message="错误摘要" description={run.error_message} showIcon />
      ) : (
        <Alert type="success" message={mode === "debug" ? "本次调试没有错误" : "本次运行没有错误"} showIcon />
      )}
      <StructuredViewer title="错误堆栈" value={run.error_stack} defaultMode="text" />
    </Space>
  );
  const apiTabs = [
    { key: "overview", label: "概览", children: overviewPanel },
    ...(assertionResults.length ? [{ key: "assertions", label: "校验", children: <AssertionResultsPanel results={assertionResults} /> }] : []),
    { key: "request", label: "请求", children: <StructuredViewer title="请求快照" value={requestSnapshot} defaultMode="json" /> },
    {
      key: "response",
      label: "响应",
      children: (
        <Space direction="vertical" size={12} className="drawer-stack">
          <StructuredViewer title="响应快照" value={responseSnapshot} defaultMode="json" />
          <StructuredViewer title="响应体" value={responseBody} defaultMode="auto" />
        </Space>
      )
    },
    { key: "logs", label: "日志", children: <StructuredViewer title="日志" value={run.logs} defaultMode="text" /> },
    { key: "error", label: "错误", children: errorPanel }
  ];
  const uiTabs = [
    { key: "overview", label: "概览", children: overviewPanel },
    ...(assertionResults.length ? [{ key: "assertions", label: "校验", children: <AssertionResultsPanel results={assertionResults} /> }] : []),
    { key: "evidence", label: "页面证据", children: <EvidencePanel run={run} onOpenResponse={() => setActiveTab("response")} /> },
    { key: "logs", label: "日志", children: <StructuredViewer title="日志" value={run.logs} defaultMode="text" /> },
    { key: "error", label: "错误", children: errorPanel }
  ];
  const tabItems = run.check_type === "api" ? apiTabs : uiTabs;
  const content = (
    <Space direction="vertical" size={16} className="drawer-stack">
      <section className={`run-detail-summary run-detail-${run.status}`}>
        <div className="run-detail-title">
          <RunStatusBadge status={run.status} />
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

      {run.error_message && <Alert type="error" message="错误摘要" description={run.error_message} showIcon />}
      {isDraftRun && (
        <Alert
          type="info"
          message="草稿调试记录"
          description="本次运行未保存任务配置，不更新任务健康状态，也不会触发告警。"
          showIcon
        />
      )}

      <Tabs
        activeKey={activeTab}
        className={`run-detail-tabs ${mode === "debug" ? "debug-result-tabs" : ""}`}
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
          <RunStatusBadge status={run.status} />
        </div>
        {content}
      </section>
    );
  }

  return content;
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
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本次运行没有结构化校验结果" />;
  }

  const columns: ColumnsType<AssertionResult> = [
    {
      title: "结果",
      dataIndex: "status",
      width: 86,
      render: (value: AssertionResult["status"]) => <Tag color={value === "ok" ? "green" : "red"}>{value === "ok" ? "通过" : "失败"}</Tag>
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

function EvidencePanel({ run, onOpenResponse }: { run: Run; onOpenResponse: () => void }) {
  const screenshotHref = artifactHref(run.screenshot_path);
  const traceHref = artifactHref(run.trace_path);
  const responseHref = artifactHref(run.response_path);
  const hasArtifacts = Boolean(screenshotHref || traceHref || responseHref);

  return (
    <section className="run-evidence-panel">
      <div className="run-evidence-header">
        <div>
          <strong>现场留证</strong>
          <span>{hasArtifacts ? "截图、Trace 与响应体已归档，可直接用于定位" : "本次运行没有生成可查看产物"}</span>
        </div>
        {responseHref && (
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
            description={screenshotHref ? "在当前页预览或打开原图" : "UI 失败时自动保存"}
            href={screenshotHref}
            actionLabel="打开原图"
          />
          <EvidenceAction
            icon={<Archive size={16} />}
            title="Trace"
            description={traceHref ? "下载 Playwright Trace 复盘操作链路" : "失败 Trace 暂未生成"}
            href={traceHref}
            actionLabel="下载 Trace"
            download
          />
          <EvidenceAction
            icon={<FileText size={16} />}
            title="Response"
            description={responseHref ? "响应体已在“响应”标签结构化展示" : "API 响应体暂未生成"}
            href={responseHref}
            actionLabel="下载文件"
            download
          />
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

function defaultRunTab(run: Run | null, mode: RunResultMode, responseSnapshot: unknown, assertionCount: number): string {
  if (!run) return "overview";
  if (mode === "debug" && assertionCount > 0) return "assertions";
  if (mode === "debug" && run.check_type === "api" && responseSnapshot) return "response";
  if (mode === "debug" && run.error_message) return "error";
  return "overview";
}
