import { Alert, Button, DatePicker, Empty, Input, Pagination, Select, Skeleton, Space, Table, Tag, Tooltip } from "antd";
import type { PaginationProps } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { Eye, FilterX, RefreshCw, RotateCcw } from "lucide-react";
import { cloneElement, isValidElement, lazy, Suspense, useEffect, useState } from "react";
import type { ReactElement } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { CheckType, NotificationStatus, ObservationKind, ProbeRunner, Run, RunStatus } from "../types";
import {
  formatDate,
  formatDuration,
  notificationChannelLabel,
  notificationStatusMeta,
  notificationStatusTagColor,
  runnerExecutionMeta,
  runStatusLabel,
  runStatusTagColor
} from "../utils";

const { RangePicker } = DatePicker;
const HISTORY_PAGE_SIZE = 12;
const NOTIFICATION_STATUS_VALUES = ["sent", "failed", "suppressed", "disabled", "not_required"] as const;
const OBSERVATION_KIND_OPTIONS: Array<{ label: string; value: ObservationKind | "" }> = [
  { label: "全部来源", value: "" },
  { label: "正式运行", value: "observation" },
  { label: "历史人工验证", value: "verification" },
  { label: "配置试运行", value: "draft" }
];
const RunDetailDrawer = lazy(() => import("../components/RunDetailDrawer").then((module) => ({ default: module.RunDetailDrawer })));

const runPaginationItemRender: PaginationProps["itemRender"] = (_, itemType, originalElement) => {
  const label = itemType === "prev" ? "上一页运行记录" : itemType === "next" ? "下一页运行记录" : "";
  if (!label || !isValidElement(originalElement)) return originalElement;
  return cloneElement(originalElement as ReactElement<Record<string, unknown>>, { "aria-label": label, title: label });
};

const NOTIFICATION_FILTER_OPTIONS: Array<{ label: string; value: NotificationStatus | "" }> = [
  { label: "全部告警", value: "" },
  ...NOTIFICATION_STATUS_VALUES.map((value) => ({
    label: notificationStatusMeta(value).label,
    value
  }))
];

const RUN_STATUS_FILTER_OPTIONS: Array<{ label: string; value: RunStatus | "" }> = [
  { label: "全部状态", value: "" },
  { label: runStatusFilterLabel("ok"), value: "ok" },
  { label: runStatusFilterLabel("failed"), value: "failed" },
  { label: runStatusFilterLabel("running"), value: "running" },
  { label: runStatusFilterLabel("skipped"), value: "skipped" }
];

function parseCheckTypeParam(value: string | null): CheckType | "" {
  return value === "ui" || value === "api" ? value : "";
}

function parseRunStatusParam(value: string | null): RunStatus | "" {
  if (value === "timeout") return "failed";
  return value === "ok" || value === "failed" || value === "running" || value === "skipped" ? value : "";
}

function parseNotificationStatusParam(value: string | null): NotificationStatus | "" {
  return NOTIFICATION_STATUS_VALUES.includes(value as NotificationStatus) ? (value as NotificationStatus) : "";
}

function parseDateParam(value: string | null): Dayjs | null {
  if (!value) return null;
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed : null;
}

function parseDateRangeParams(searchParams: URLSearchParams): [Dayjs | null, Dayjs | null] | null {
  const start = parseDateParam(searchParams.get("start"));
  const end = parseDateParam(searchParams.get("end"));
  return start || end ? [start, end] : null;
}

function sameDateRange(a: [Dayjs | null, Dayjs | null] | null, b: [Dayjs | null, Dayjs | null] | null): boolean {
  const aStart = a?.[0]?.format("YYYY-MM-DD") || "";
  const aEnd = a?.[1]?.format("YYYY-MM-DD") || "";
  const bStart = b?.[0]?.format("YYYY-MM-DD") || "";
  const bEnd = b?.[1]?.format("YYYY-MM-DD") || "";
  return aStart === bStart && aEnd === bEnd;
}

export function RunsPage() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [runs, setRuns] = useState<Run[]>([]);
  const [type, setType] = useState<CheckType | "">(() => parseCheckTypeParam(searchParams.get("type")));
  const [status, setStatus] = useState<RunStatus | "">(() => parseRunStatusParam(searchParams.get("status")));
  const [notificationStatus, setNotificationStatus] = useState<NotificationStatus | "">(() =>
    parseNotificationStatusParam(searchParams.get("notification_status"))
  );
  const [observationKind, setObservationKind] = useState<ObservationKind | "">(
    () => (searchParams.get("observation_kind") as ObservationKind | null) || ""
  );
  const [runnerId, setRunnerId] = useState(() => searchParams.get("runner_id") || "");
  const [runners, setRunners] = useState<ProbeRunner[]>([]);
  const [q, setQ] = useState(() => searchParams.get("q") || "");
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(() => parseDateRangeParams(searchParams));
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [rerunningId, setRerunningId] = useState<number | null>(null);
  const [detailRunId, setDetailRunId] = useState<number | null>(null);
  const [isNarrowTable, setIsNarrowTable] = useState(false);
  const [isCompactList, setIsCompactList] = useState(() => window.matchMedia("(max-width: 720px)").matches);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const checkId = searchParams.get("check_id");
  const normalizedQ = q.trim();
  const hasFilters = Boolean(type || status || notificationStatus || observationKind || runnerId || normalizedQ || dateRange?.[0] || dateRange?.[1] || checkId);
  const scopedCheckName = checkId ? runs.find((run) => String(run.check_id) === checkId)?.check_name : null;

  async function load() {
    setLoading(true);
    try {
      const result = await api.runsPage({
          type,
          status,
          notification_status: notificationStatus,
          observation_kind: observationKind,
          q: normalizedQ,
          check_id: checkId,
          runner_id: runnerId,
          start: dateRange?.[0]?.startOf("day").toISOString(),
          end: dateRange?.[1]?.endOf("day").toISOString(),
          page,
          page_size: HISTORY_PAGE_SIZE
        });
      setRuns(result.items);
      setTotal(result.total);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const nextType = parseCheckTypeParam(searchParams.get("type"));
    const nextStatus = parseRunStatusParam(searchParams.get("status"));
    const nextNotificationStatus = parseNotificationStatusParam(searchParams.get("notification_status"));
    const nextObservationKind = (searchParams.get("observation_kind") as ObservationKind | null) || "";
    const nextRunnerId = searchParams.get("runner_id") || "";
    const nextQ = searchParams.get("q") || "";
    const nextDateRange = parseDateRangeParams(searchParams);

    if (type !== nextType) setType(nextType);
    if (status !== nextStatus) setStatus(nextStatus);
    if (notificationStatus !== nextNotificationStatus) setNotificationStatus(nextNotificationStatus);
    if (observationKind !== nextObservationKind) setObservationKind(nextObservationKind);
    if (runnerId !== nextRunnerId) setRunnerId(nextRunnerId);
    if (q !== nextQ) setQ(nextQ);
    if (!sameDateRange(dateRange, nextDateRange)) setDateRange(nextDateRange);
  }, [searchParams]);

  useEffect(() => {
    const next = new URLSearchParams();
    if (type) next.set("type", type);
    if (status) next.set("status", status);
    if (notificationStatus) next.set("notification_status", notificationStatus);
    if (observationKind) next.set("observation_kind", observationKind);
    if (runnerId) next.set("runner_id", runnerId);
    if (normalizedQ) next.set("q", normalizedQ);
    if (dateRange?.[0]) next.set("start", dateRange[0].format("YYYY-MM-DD"));
    if (dateRange?.[1]) next.set("end", dateRange[1].format("YYYY-MM-DD"));
    if (checkId) next.set("check_id", checkId);

    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [checkId, dateRange, normalizedQ, notificationStatus, observationKind, runnerId, searchParams, setSearchParams, status, type]);

  useEffect(() => {
    load();
  }, [type, status, notificationStatus, observationKind, runnerId, normalizedQ, dateRange, checkId, page]);

  useEffect(() => {
    setPage(1);
  }, [type, status, notificationStatus, observationKind, runnerId, normalizedQ, dateRange, checkId]);

  useEffect(() => {
    api.runners().then(setRunners).catch(() => setRunners([]));
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 820px)");
    const sync = () => setIsNarrowTable(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 720px)");
    const sync = () => setIsCompactList(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  async function rerun(run: Run) {
    if (run.check_id <= 0) {
      setError("草稿调试记录不能重新执行；请回到对应任务重新运行草稿或保存后执行。");
      return;
    }
    setRerunningId(run.id);
    try {
      const latest = await api.rerun(run.id);
      setDetailRunId(latest.id);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRerunningId(null);
    }
  }

  function resetFilters() {
    setType("");
    setStatus("");
    setNotificationStatus("");
    setObservationKind("");
    setRunnerId("");
    setQ("");
    setDateRange(null);
    setSearchParams(new URLSearchParams(), { replace: true });
  }

  function clearTaskScope() {
    if (!checkId) return;
    const next = new URLSearchParams(searchParams);
    next.delete("check_id");
    setSearchParams(next, { replace: true });
  }

  const columns: ColumnsType<Run> = [
    { title: "执行时间", dataIndex: "started_at", render: (value: string) => formatDate(value), width: 156 },
    { title: "类型", dataIndex: "check_type", render: (value: string) => (value === "ui" ? "UI" : "API"), width: 64, align: "center" },
    {
      title: "任务",
      dataIndex: "check_name",
      ellipsis: true,
      width: 210,
      render: (value: string, run) => (
        <Space orientation="vertical" size={2}>
          <Button
            type="link"
            className="table-link strong"
            onClick={(event) => {
              event.stopPropagation();
              setDetailRunId(run.id);
            }}
          >
            {value}
          </Button>
          {run.check_id <= 0 && <Tag>草稿调试</Tag>}
          <Tooltip title={runnerTooltip(run)}>
            <span className="history-runner-meta">{runnerSummary(run)}</span>
          </Tooltip>
        </Space>
      )
    },
    {
      title: "执行节点",
      dataIndex: "runner_id",
      width: 150,
      render: (_, run) => (
        <Tooltip title={runnerTooltip(run)}>
          <Space orientation="vertical" size={2}>
            <Tag>{run.runner_name || run.runner_id || "local"}</Tag>
            <RunnerExecutionTag run={run} />
          </Space>
        </Tooltip>
      )
    },
    { title: "运行状态", dataIndex: "status", render: (_, run) => <Tag color={runStatusTagColor(run.status)}>{runStatusLabel(run.status)}</Tag>, width: 92, align: "center" },
    {
      title: "节点结果",
      dataIndex: "failure_kind",
      render: (_, run) => <RunnerExecutionTag run={run} />,
      width: 104,
      align: "center"
    },
    {
      title: "来源",
      dataIndex: "observation_kind",
      render: (_, run) => <Tag color={run.affects_health ? "blue" : "default"}>{observationKindLabel(run.observation_kind)}</Tag>,
      width: 96,
      align: "center"
    },
    {
      title: "失败来源",
      dataIndex: "failure_kind",
      render: (_, run) => failureKindTag(run),
      width: 92,
      align: "center"
    },
    {
      title: "告警",
      dataIndex: "notification_status",
      width: 104,
      align: "center",
      render: (_, run) => {
        const notification = notificationStatusMeta(run.notification_status);
        return <Tag color={notificationStatusTagColor(run.notification_status)}>{notification.label}</Tag>;
      }
    },
    { title: "耗时", dataIndex: "duration_ms", render: (value?: number | null) => formatDuration(value), width: 88, align: "right" },
    { title: "错误摘要", dataIndex: "error_message", ellipsis: true, width: 144 },
    {
      title: "操作",
      width: 92,
      fixed: isNarrowTable ? undefined : "right",
      align: "center",
      render: (_, run) => (
        <Space className="history-row-actions" size={6}>
          <Button
            size="small"
            title="查看详情"
            aria-label="查看详情"
            icon={<Eye size={15} />}
            onClick={(event) => {
              event.stopPropagation();
              setDetailRunId(run.id);
            }}
          />
          <Button
            size="small"
            title={run.check_id > 0 ? "重新执行" : "草稿调试记录不能重新执行"}
            aria-label="重新执行"
            icon={<RotateCcw size={15} />}
            loading={rerunningId === run.id}
            disabled={run.check_id <= 0}
            onClick={(event) => {
              event.stopPropagation();
              rerun(run);
            }}
          />
        </Space>
      )
    }
  ];

  return (
    <div className="page-content">
      {error && <Alert type="error" message={error} showIcon />}

      <section className="history-toolbar">
        <div className="history-filter-row">
          <Select
            value={type}
            className="history-filter-control"
            onChange={(value) => setType(value)}
            options={[
              { label: "全部类型", value: "" },
              { label: "UI", value: "ui" },
              { label: "API", value: "api" }
            ]}
          />
          <Select
            value={status}
            className="history-filter-control"
            onChange={(value) => setStatus(value)}
            options={RUN_STATUS_FILTER_OPTIONS}
          />
          <Select
            value={notificationStatus}
            className="history-filter-control history-notification-filter"
            onChange={(value) => setNotificationStatus(value)}
            options={NOTIFICATION_FILTER_OPTIONS}
          />
          <Select
            value={observationKind}
            className="history-filter-control"
            onChange={(value) => setObservationKind(value)}
            options={OBSERVATION_KIND_OPTIONS}
          />
          <Select
            value={runnerId}
            className="history-filter-control"
            onChange={(value) => setRunnerId(value)}
            options={[
              { label: "全部节点", value: "" },
              ...runners.map((runner) => ({ label: runner.name || runner.runner_id, value: runner.runner_id }))
            ]}
          />
          <RangePicker
            value={dateRange}
            onChange={(value) => setDateRange(value)}
            className="history-date-range"
            aria-label="按执行日期筛选"
          />
          <Input
            name="runs-search"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="任务名称…"
            allowClear
            autoComplete="off"
            className="history-search"
          />
        </div>
        <Space wrap>
          <Button icon={<FilterX size={16} />} onClick={resetFilters} disabled={!hasFilters}>
            清空筛选
          </Button>
          <Button icon={<RefreshCw size={16} />} onClick={load} loading={loading}>
            刷新
          </Button>
        </Space>
      </section>

      <div className="history-result-bar">
        <span>当前结果</span>
        <strong>{total}</strong>
        <span>条</span>
        {type && <Tag>{type === "ui" ? "UI" : "API"}</Tag>}
        {status && <Tag>{runStatusFilterLabel(status)}</Tag>}
        {notificationStatus && <Tag>告警：{notificationStatusMeta(notificationStatus).label}</Tag>}
        {observationKind && <Tag>来源：{observationKindLabel(observationKind)}</Tag>}
        {runnerId && <Tag>执行节点：{runnerLabel(runnerId, runners)}</Tag>}
        {checkId && (
          <Tag
            closable
            onClose={(event) => {
              event.preventDefault();
              clearTaskScope();
            }}
          >
            任务 #{checkId}
          </Tag>
        )}
        {dateRange?.[0] && <Tag>开始：{dateRange[0].format("YYYY-MM-DD")}</Tag>}
        {dateRange?.[1] && <Tag>结束：{dateRange[1].format("YYYY-MM-DD")}</Tag>}
        {normalizedQ && <Tag>关键词：{normalizedQ}</Tag>}
      </div>

      {isCompactList ? (
        <CompactRunList
          hasFilters={hasFilters}
          loading={loading}
          page={page}
          total={total}
          rerunningId={rerunningId}
          runs={runs}
          onOpen={(run) => setDetailRunId(run.id)}
          onPageChange={setPage}
          onRerun={rerun}
        />
      ) : (
        <Table
          rowKey="id"
          columns={columns}
          dataSource={runs}
          loading={loading}
          className="history-table"
          locale={{ emptyText: <Empty description={hasFilters ? "没有符合筛选条件的运行记录" : "暂无运行记录"} /> }}
          pagination={{
            current: page,
            pageSize: HISTORY_PAGE_SIZE,
            total,
            showSizeChanger: false,
            itemRender: runPaginationItemRender,
            onChange: setPage
          }}
          scroll={{ x: 1060 }}
        />
      )}
      {detailRunId && (
        <Suspense fallback={null}>
          <RunDetailDrawer runId={detailRunId} onClose={() => setDetailRunId(null)} onRerun={rerun} returnTo={`${location.pathname}${location.search}`} />
        </Suspense>
      )}
    </div>
  );
}

interface CompactRunListProps {
  hasFilters: boolean;
  loading: boolean;
  page: number;
  total: number;
  rerunningId: number | null;
  runs: Run[];
  onOpen: (run: Run) => void;
  onPageChange: (page: number) => void;
  onRerun: (run: Run) => void;
}

function CompactRunList({ hasFilters, loading, page, total, rerunningId, runs, onOpen, onPageChange, onRerun }: CompactRunListProps) {
  if (loading) {
    return (
      <section className="history-card-list" aria-label="运行记录加载中">
        {[0, 1, 2].map((item) => (
          <article className="history-card history-card-loading" key={item}>
            <Skeleton active paragraph={{ rows: 4 }} title={{ width: "76%" }} />
          </article>
        ))}
      </section>
    );
  }

  if (!runs.length) {
    return (
      <section className="history-card-empty">
        <Empty description={hasFilters ? "没有符合筛选条件的运行记录" : "暂无运行记录"} />
      </section>
    );
  }

  return (
    <section className="history-card-list" aria-label="运行记录列表">
      {runs.map((run) => {
        const notification = notificationStatusMeta(run.notification_status);
        return (
          <article className={`history-card history-card-${run.status}`} key={run.id}>
            <header className="history-card-header">
              <div className="history-card-main">
                <div className="history-card-context">
                  <span>{run.check_type === "ui" ? "UI" : "API"}</span>
                  <span>运行记录 #{run.id}</span>
                  {run.check_id <= 0 && <Tag>草稿调试</Tag>}
                </div>
                <Button type="link" className="history-card-title" onClick={() => onOpen(run)}>
                  {run.check_name}
                </Button>
                {run.error_message && <div className="history-card-error">{run.error_message}</div>}
              </div>
              <div className="history-card-state">
                <Tag color={runStatusTagColor(run.status)}>{runStatusLabel(run.status)}</Tag>
                <RunnerExecutionTag run={run} />
                {failureKindTag(run)}
                <Tag color={notificationStatusTagColor(run.notification_status)}>{notification.label}</Tag>
              </div>
            </header>

            <div className="history-card-meta">
              <HistoryMeta label="执行时间" value={formatDate(run.started_at)} />
              <HistoryMeta label="记录来源" value={observationKindLabel(run.observation_kind)} />
              <HistoryMeta label="耗时" value={formatDuration(run.duration_ms)} />
              <HistoryMeta label="执行节点" value={runnerSummary(run)} />
              <HistoryMeta label="告警渠道" value={notificationChannelLabel(run.notification_channel, run.notification_status)} />
              <HistoryMeta label="连续失败" value={run.consecutive_failures || "-"} />
            </div>

            <Space className="history-card-actions">
              <Button icon={<Eye size={15} />} onClick={() => onOpen(run)}>
                详情
              </Button>
              <Button
                icon={<RotateCcw size={15} />}
                loading={rerunningId === run.id}
                disabled={run.check_id <= 0}
                title={run.check_id > 0 ? "重新执行" : "草稿调试记录不能重新执行"}
                onClick={() => onRerun(run)}
              >
                重跑
              </Button>
            </Space>
          </article>
        );
      })}
      {total > HISTORY_PAGE_SIZE && (
        <Pagination
          className="history-card-pagination"
          current={page}
          pageSize={HISTORY_PAGE_SIZE}
          simple
          showSizeChanger={false}
          total={total}
          itemRender={runPaginationItemRender}
          onChange={onPageChange}
        />
      )}
    </section>
  );
}

function HistoryMeta({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="history-card-meta-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RunnerExecutionTag({ run }: { run: Run }) {
  const meta = runnerExecutionMeta(run.status, run.failure_kind);
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

function runnerSummary(run: Run): string {
  const name = (run.runner_name || "local").trim();
  const region = (run.runner_region || "").trim();
  return region && region !== name ? `${name} · ${region}` : name;
}

function runnerLabel(runnerId: string, runners: ProbeRunner[]): string {
  return runners.find((runner) => runner.runner_id === runnerId)?.name || runnerId;
}

function runnerTooltip(run: Run): string {
  const details = [
    `执行节点: ${runnerSummary(run)}`,
    run.runner_address ? `地址: ${run.runner_address}` : "",
    run.runner_browser_version ? `浏览器: ${run.runner_browser_version}` : ""
  ].filter(Boolean);
  return details.join("\n");
}

function failureKindTag(run: Run) {
  const kind = run.failure_kind || "none";
  if (kind === "target") return <Tag color="red">目标页面/API</Tag>;
  if (kind === "runner") return <Tag color="orange">执行环境</Tag>;
  return <span className="history-empty-cell">-</span>;
}

function runStatusFilterLabel(status: RunStatus): string {
  return status === "failed" ? "失败/超时" : runStatusLabel(status);
}

function observationKindLabel(kind: ObservationKind): string {
  return {
    observation: "正式运行",
    verification: "历史人工验证",
    draft: "配置试运行"
  }[kind];
}
