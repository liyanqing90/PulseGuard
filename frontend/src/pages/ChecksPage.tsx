import { Alert, App, Button, Card, Empty, Input, Popconfirm, Select, Skeleton, Space, Statistic, Switch, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Copy, Edit3, FilterX, History, Play, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { checkToCopyPayload } from "../checkPayload";
import {
  BatchRunActions,
  BatchRunBreakdown,
  batchRunMessage,
  batchRunNotificationType,
  summarizeBatchRuns
} from "../components/BatchRunAlert";
import { CheckEditorDrawer } from "../components/CheckEditorDrawer";
import { RunDetailDrawer } from "../components/RunDetailDrawer";
import { TaskStatusBadge } from "../components/StatusBadge";
import type { Check, CheckType, TaskSurfaceStatus } from "../types";
import { compactUrl, formatDate, formatDuration, intervalLabel, taskStatus, taskStatusLabel } from "../utils";

type EnabledFilter = "" | "enabled" | "disabled";

export function ChecksPage({ type }: { type: CheckType }) {
  const { message } = App.useApp();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [checks, setChecks] = useState<Check[]>([]);
  const [editing, setEditing] = useState<Check | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailRunId, setDetailRunId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | "all" | null>(null);
  const [duplicatingId, setDuplicatingId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<TaskSurfaceStatus | "">("");
  const [enabledFilter, setEnabledFilter] = useState<EnabledFilter>("");
  const [isCompactList, setIsCompactList] = useState(() => window.matchMedia("(max-width: 720px)").matches);
  const navigate = useNavigate();
  const focusedCheckId = searchParams.get("check_id");

  async function load() {
    setLoading(true);
    try {
      setChecks(await api.checks(type));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [type]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 720px)");
    const sync = () => setIsCompactList(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return checks.filter((check) => {
      const matchesKeyword =
        !keyword || [check.name, check.entry_url, check.tags].some((value) => (value || "").toLowerCase().includes(keyword));
      const surfaceStatus = taskStatus(check);
      const matchesStatus = !statusFilter || surfaceStatus === statusFilter;
      const matchesEnabled =
        !enabledFilter || (enabledFilter === "enabled" ? check.enabled : !check.enabled);
      const matchesFocused = !focusedCheckId || String(check.id) === focusedCheckId;
      return matchesKeyword && matchesStatus && matchesEnabled && matchesFocused;
    });
  }, [checks, enabledFilter, focusedCheckId, query, statusFilter]);

  const summary = useMemo(() => {
    const counts: Record<TaskSurfaceStatus, number> = { ok: 0, failed: 0, never: 0, disabled: 0 };
    checks.forEach((check) => {
      counts[taskStatus(check)] += 1;
    });
    return {
      total: checks.length,
      visible: filtered.length,
      enabled: checks.filter((check) => check.enabled).length,
      ...counts
    };
  }, [checks, filtered.length]);

  const hasFilters = Boolean(query || statusFilter || enabledFilter || focusedCheckId);

  async function runCheck(check: Check) {
    setBusy(check.id);
    try {
      const run = await api.runCheck(check.id);
      setDetailRunId(run.id);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function toggle(check: Check) {
    setBusy(check.id);
    try {
      check.enabled ? await api.disableCheck(check.id) : await api.enableCheck(check.id);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function remove(check: Check) {
    setBusy(check.id);
    try {
      await api.deleteCheck(check.id);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function duplicate(check: Check) {
    setDuplicatingId(check.id);
    setError(null);
    try {
      const copied = await api.createCheck(checkToCopyPayload(check));
      await load();
      setEditing(copied);
      setDrawerOpen(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDuplicatingId(null);
    }
  }

  async function runAll() {
    setBusy("all");
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
                <Button size="small" icon={<Plus size={14} />} onClick={openCreateDrawer}>
                  新增任务
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
      setBusy(null);
    }
  }

  function openCreateDrawer() {
    setEditing(null);
    setDrawerOpen(true);
  }

  function resetFilters() {
    setQuery("");
    setStatusFilter("");
    setEnabledFilter("");
    clearTaskFocus();
  }

  function clearTaskFocus() {
    if (!focusedCheckId) return;
    const next = new URLSearchParams(searchParams);
    next.delete("check_id");
    setSearchParams(next, { replace: true });
  }

  const columns: ColumnsType<Check> = [
    {
      title: "名称",
      dataIndex: "name",
      render: (value: string, check) => (
        <div>
          <Button type="link" className="table-link strong" onClick={() => check.last_run_id && setDetailRunId(check.last_run_id)}>
            {value}
          </Button>
          {check.tags && <div className="tag-line">{check.tags}</div>}
        </div>
      ),
      fixed: "left",
      width: 230
    },
    ...(type === "api" ? [{ title: "Method", dataIndex: "method", width: 92 }] : []),
    {
      title: "URL",
      dataIndex: "entry_url",
      ellipsis: true,
      render: (value: string) => <span title={value}>{compactUrl(value)}</span>
    },
    { title: "状态", render: (_, check) => <TaskStatusBadge check={check} />, width: 105 },
    {
      title: "启用",
      render: (_, check) => (
        <Switch
          aria-label={`${check.name} 启用状态`}
          checked={check.enabled}
          loading={busy === check.id}
          onChange={() => toggle(check)}
        />
      ),
      width: 92
    },
    { title: "定时", dataIndex: "interval_seconds", render: (value: number) => intervalLabel(value), width: 105 },
    { title: "最近执行", dataIndex: "last_run_at", render: (value?: string | null) => formatDate(value), width: 180 },
    { title: "耗时", dataIndex: "last_duration_ms", render: (value?: number | null) => formatDuration(value), width: 105 },
    { title: "连续失败", dataIndex: "consecutive_failures", render: (value: number) => value || "-", width: 105 },
    {
      title: "操作",
      width: 210,
      render: (_, check) => (
        <Space>
          <Button
            size="small"
            title="执行"
            aria-label="执行"
            icon={<Play size={15} />}
            loading={busy === check.id}
            onClick={() => runCheck(check)}
          />
          <Button
            size="small"
            title="编辑"
            aria-label="编辑"
            icon={<Edit3 size={15} />}
            onClick={() => {
              setEditing(check);
              setDrawerOpen(true);
            }}
          />
          <Button
            size="small"
            title="历史"
            aria-label="历史"
            icon={<History size={15} />}
            onClick={() => navigate(`/runs?check_id=${check.id}`)}
          />
          <Button
            size="small"
            title="复制"
            aria-label="复制"
            icon={<Copy size={15} />}
            loading={duplicatingId === check.id}
            onClick={() => duplicate(check)}
          />
          <Popconfirm title="删除任务" description={`删除“${check.name}”？`} okText="删除" cancelText="取消" onConfirm={() => remove(check)}>
            <Button size="small" title="删除" aria-label="删除" danger icon={<Trash2 size={15} />} />
          </Popconfirm>
        </Space>
      )
    }
  ];

  return (
    <div className="page-content">
      {error && <Alert type="error" message={error} showIcon />}

      <section className="check-summary">
        <Card className="summary-card">
          <Statistic title="全部任务" value={summary.total} />
        </Card>
        <Card className="summary-card metric-success">
          <Statistic title="正常" value={summary.ok} />
        </Card>
        <Card className={`summary-card ${summary.failed ? "metric-danger" : ""}`}>
          <Statistic title="失败" value={summary.failed} />
        </Card>
        <Card className="summary-card metric-info">
          <Statistic title="未运行" value={summary.never} />
        </Card>
        <Card className="summary-card metric-success">
          <Statistic title="已启用" value={summary.enabled} />
        </Card>
      </section>

      <section className="checks-toolbar">
        <div className="checks-filter-row">
          <Input.Search
            className="checks-search"
            name="checks-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索名称、URL 或标签…"
            allowClear
            autoComplete="off"
          />
          <Select
            value={statusFilter}
            className="checks-filter-control"
            onChange={(value) => setStatusFilter(value)}
            options={[
              { label: "全部状态", value: "" },
              { label: "正常", value: "ok" },
              { label: "失败", value: "failed" },
              { label: "未运行", value: "never" },
              { label: "已禁用", value: "disabled" }
            ]}
          />
          <Select
            value={enabledFilter}
            className="checks-filter-control"
            onChange={(value) => setEnabledFilter(value)}
            options={[
              { label: "全部启用状态", value: "" },
              { label: "已启用", value: "enabled" },
              { label: "已禁用", value: "disabled" }
            ]}
          />
        </div>
        <Space wrap>
          <Button icon={<FilterX size={16} />} onClick={resetFilters} disabled={!hasFilters}>
            清空筛选
          </Button>
          <Button icon={<RefreshCw size={16} />} onClick={load} loading={loading}>
            刷新
          </Button>
          <Button icon={<Play size={16} />} onClick={runAll} loading={busy === "all"}>
            执行全部
          </Button>
          <Button type="primary" icon={<Plus size={16} />} onClick={openCreateDrawer}>
            新增{type === "ui" ? " UI" : "接口"}任务
          </Button>
        </Space>
      </section>

      <div className="checks-result-bar">
        <span>当前结果</span>
        <strong>{summary.visible}</strong>
        <span>条</span>
        {statusFilter && <Tag>{taskStatusLabel(statusFilter)}</Tag>}
        {enabledFilter && <Tag>{enabledFilter === "enabled" ? "已启用" : "已禁用"}</Tag>}
        {focusedCheckId && (
          <Tag
            closable
            onClose={(event) => {
              event.preventDefault();
              clearTaskFocus();
            }}
          >
            任务 #{focusedCheckId}
          </Tag>
        )}
        {query && <Tag>关键词：{query}</Tag>}
      </div>

      {isCompactList ? (
        <CompactCheckList
          busy={busy}
          checks={filtered}
          hasFilters={hasFilters}
          loading={loading}
          type={type}
          onCreate={openCreateDrawer}
          onDelete={remove}
          onDuplicate={duplicate}
          onEdit={(check) => {
            setEditing(check);
            setDrawerOpen(true);
          }}
          onHistory={(check) => navigate(`/runs?check_id=${check.id}`)}
          onOpenLastRun={(check) => check.last_run_id && setDetailRunId(check.last_run_id)}
          onRun={runCheck}
          onToggle={toggle}
          duplicatingId={duplicatingId}
        />
      ) : (
        <Table
          rowKey="id"
          columns={columns}
          dataSource={filtered}
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{
            emptyText: (
              <Empty description={hasFilters ? "没有符合筛选条件的任务" : "暂无任务"}>
                {!hasFilters && <Button type="primary" icon={<Plus size={16} />} onClick={openCreateDrawer}>新增任务</Button>}
              </Empty>
            )
          }}
          scroll={{ x: type === "api" ? 1220 : 1120 }}
        />
      )}

      <CheckEditorDrawer open={drawerOpen} type={type} check={editing} onClose={() => setDrawerOpen(false)} onSaved={load} />
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

interface CompactCheckListProps {
  busy: number | "all" | null;
  checks: Check[];
  duplicatingId: number | null;
  hasFilters: boolean;
  loading: boolean;
  type: CheckType;
  onCreate: () => void;
  onDelete: (check: Check) => void;
  onDuplicate: (check: Check) => void;
  onEdit: (check: Check) => void;
  onHistory: (check: Check) => void;
  onOpenLastRun: (check: Check) => void;
  onRun: (check: Check) => void;
  onToggle: (check: Check) => void;
}

function CompactCheckList({
  busy,
  checks,
  duplicatingId,
  hasFilters,
  loading,
  type,
  onCreate,
  onDelete,
  onDuplicate,
  onEdit,
  onHistory,
  onOpenLastRun,
  onRun,
  onToggle
}: CompactCheckListProps) {
  if (loading) {
    return (
      <section className="check-card-list" aria-label="任务列表加载中">
        {[0, 1, 2].map((item) => (
          <article className="check-card check-card-loading" key={item}>
            <Skeleton active paragraph={{ rows: 4 }} title={{ width: "72%" }} />
          </article>
        ))}
      </section>
    );
  }

  if (!checks.length) {
    return (
      <section className="check-card-empty">
        <Empty description={hasFilters ? "没有符合筛选条件的任务" : "暂无任务"}>
          {!hasFilters && (
            <Button type="primary" icon={<Plus size={16} />} onClick={onCreate}>
              新增任务
            </Button>
          )}
        </Empty>
      </section>
    );
  }

  return (
    <section className="check-card-list" aria-label="任务列表">
      {checks.map((check) => {
        const status = taskStatus(check);
        return (
          <article className={`check-card check-card-${status}`} key={check.id}>
            <header className="check-card-header">
              <div className="check-card-main">
                <div className="check-card-eyebrow">
                  <span>{type === "ui" ? "UI 任务" : "接口任务"}</span>
                  {type === "api" && check.method && <Tag>{check.method}</Tag>}
                </div>
                {check.last_run_id ? (
                  <Button type="link" className="check-card-title" onClick={() => onOpenLastRun(check)}>
                    {check.name}
                  </Button>
                ) : (
                  <strong className="check-card-title-static">{check.name}</strong>
                )}
                <div className="check-card-url" title={check.entry_url}>
                  {compactUrl(check.entry_url)}
                </div>
                {check.tags && <TagLine tags={check.tags} />}
              </div>
              <div className="check-card-state">
                <TaskStatusBadge check={check} />
                <label className="check-card-enable">
                  <span>{check.enabled ? "启用" : "禁用"}</span>
                  <Switch
                    aria-label={`${check.name} 启用状态`}
                    checked={check.enabled}
                    loading={busy === check.id}
                    onChange={() => onToggle(check)}
                  />
                </label>
              </div>
            </header>

            <div className="check-card-meta">
              <CheckMeta label="定时" value={intervalLabel(check.interval_seconds)} />
              <CheckMeta label="最近执行" value={formatDate(check.last_run_at)} />
              <CheckMeta label="耗时" value={formatDuration(check.last_duration_ms)} />
              <CheckMeta label="连续失败" value={check.consecutive_failures || "-"} />
            </div>

            <Space className="check-card-actions">
              <Button icon={<Play size={15} />} loading={busy === check.id} onClick={() => onRun(check)}>
                执行
              </Button>
              <Button icon={<Edit3 size={15} />} onClick={() => onEdit(check)}>
                编辑
              </Button>
              <Button icon={<History size={15} />} onClick={() => onHistory(check)}>
                历史
              </Button>
              <Button icon={<Copy size={15} />} loading={duplicatingId === check.id} onClick={() => onDuplicate(check)}>
                复制
              </Button>
              <Popconfirm title="删除任务" description={`删除“${check.name}”？`} okText="删除" cancelText="取消" onConfirm={() => onDelete(check)}>
                <Button danger icon={<Trash2 size={15} />}>
                  删除
                </Button>
              </Popconfirm>
            </Space>
          </article>
        );
      })}
    </section>
  );
}

function CheckMeta({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="check-card-meta-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TagLine({ tags }: { tags: string }) {
  const items = tags
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);

  if (!items.length) return null;

  return (
    <div className="check-card-tags">
      {items.map((tag) => (
        <Tag key={tag}>{tag}</Tag>
      ))}
    </div>
  );
}
