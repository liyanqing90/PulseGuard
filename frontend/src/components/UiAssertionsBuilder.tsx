import { App, Button, Checkbox, Empty, Input, InputNumber, Modal, Select, Space, Spin, Switch, Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  CopyPlus,
  Eye,
  EyeOff,
  Hash,
  Link2,
  MessageSquareText,
  MousePointer2,
  Plus,
  Save,
  ScanSearch,
  Search,
  Terminal,
  Trash2,
  Type
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, MouseEvent, ReactNode } from "react";
import { api } from "../api";
import type { CheckPayload, UiAssertion, UiAssertionType, UiElementCandidate, UiInspectResult, UiRuleInspectItem, UiRuleInspectResult } from "../types";
import { createUiAssertion, parseUiAssertions, serializeUiAssertions, UI_ASSERTION_LABELS } from "../uiAssertions";
import { VIEWPORT_PRESETS } from "./ViewportModeControl";

type CandidateRuleType = "element_visible" | "element_not_empty" | "element_count" | "text_present";
type CandidateRuleSelection = Partial<Record<CandidateRuleType, boolean>>;
type CandidateSelectionSource = "candidate" | "preview" | "scan";

const CANDIDATE_RULE_OPTIONS: Array<{ type: CandidateRuleType; label: string; icon: ReactNode; requiresText?: boolean }> = [
  { type: "element_visible", label: "可见", icon: <Eye size={13} /> },
  { type: "element_not_empty", label: "非空", icon: <MousePointer2 size={13} /> },
  { type: "element_count", label: "数量", icon: <Hash size={13} /> },
  { type: "text_present", label: "文本", icon: <CopyPlus size={13} />, requiresText: true }
];

const RULE_OPTIONS: Array<{ type: UiAssertionType; label: string; icon: ReactNode }> = [
  { type: "page_not_blank", label: "页面不空白", icon: <ScanSearch size={15} /> },
  { type: "element_visible", label: "元素可见", icon: <Eye size={15} /> },
  { type: "element_hidden", label: "元素隐藏", icon: <EyeOff size={15} /> },
  { type: "element_not_empty", label: "组件不为空", icon: <MousePointer2 size={15} /> },
  { type: "text_present", label: "文本出现", icon: <MessageSquareText size={15} /> },
  { type: "text_absent", label: "文本不存在", icon: <MessageSquareText size={15} /> },
  { type: "title_contains", label: "标题包含", icon: <Type size={15} /> },
  { type: "url_contains", label: "URL 包含", icon: <Link2 size={15} /> },
  { type: "element_count", label: "元素数量", icon: <Hash size={15} /> },
  { type: "console_error_absent", label: "控制台无错误", icon: <Terminal size={15} /> }
];

const OPERATOR_OPTIONS = [
  { label: "=", value: "eq" },
  { label: "!=", value: "ne" },
  { label: ">", value: "gt" },
  { label: ">=", value: "gte" },
  { label: "<", value: "lt" },
  { label: "<=", value: "lte" }
];

const CANDIDATE_KIND_LABELS = {
  interactive: "交互",
  media: "媒体",
  text: "文本",
  component: "组件",
  structure: "结构"
} satisfies Record<NonNullable<UiElementCandidate["kind"]>, string>;

interface Props {
  check: CheckPayload;
  value: string;
  onChange: (value: string) => void;
}

export function UiAssertionsBuilder({ check, value, onChange }: Props) {
  const { message } = App.useApp();
  const [modal, modalContextHolder] = Modal.useModal();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [inspectResult, setInspectResult] = useState<UiInspectResult | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<UiElementCandidate | null>(null);
  const [candidateSelectionSource, setCandidateSelectionSource] = useState<CandidateSelectionSource>("scan");
  const [pickerSelections, setPickerSelections] = useState<Record<string, CandidateRuleSelection>>({});
  const [candidateQuery, setCandidateQuery] = useState("");
  const [inspecting, setInspecting] = useState(false);
  const [inspectError, setInspectError] = useState<string | null>(null);
  const [ruleInspecting, setRuleInspecting] = useState(false);
  const [ruleInspectResult, setRuleInspectResult] = useState<UiRuleInspectResult | null>(null);
  const candidateItemRefs = useRef<Map<string, HTMLElement>>(new Map());
  const previewScrollRef = useRef<HTMLDivElement | null>(null);
  const previewStageRef = useRef<HTMLDivElement | null>(null);
  const assertions = useMemo(() => parseUiAssertions(value), [value]);
  const enabledCount = assertions.filter((item) => item.enabled).length;
  const selectorRuleCount = assertions.filter(isSelectorAssertion).length;
  const ruleInspectionById = useMemo(
    () => new Map((ruleInspectResult?.results || []).map((result) => [result.id, result])),
    [ruleInspectResult]
  );
  const filteredCandidates = useMemo(() => {
    if (!inspectResult) return [];
    const query = candidateQuery.trim().toLowerCase();
    if (!query) return inspectResult.candidates;
    return inspectResult.candidates.filter((candidate) =>
      [candidate.name || "", candidate.selector, candidate.text, candidate.tag, candidate.role, candidate.kind || "", candidate.selector_type || "", candidate.stability || ""].some(
        (value) => value.toLowerCase().includes(query)
      )
    );
  }, [candidateQuery, inspectResult]);
  const markerCandidates = useMemo(() => {
    if (!inspectResult) return [];
    const viewportArea = inspectResult.viewport.width * inspectResult.viewport.height;
    return filteredCandidates
      .filter((candidate) => candidate.box.width >= 10 && candidate.box.height >= 10 && candidate.box.width * candidate.box.height < viewportArea * 0.75)
      .sort((left, right) => candidateArea(right) - candidateArea(left))
      .slice(0, 100);
  }, [filteredCandidates, inspectResult]);
  const viewportMode = check.viewport_mode || "web";
  const currentPreset = VIEWPORT_PRESETS[viewportMode];
  const pendingRuleCount = useMemo(
    () => Object.values(pickerSelections).reduce((total, selection) => total + CANDIDATE_RULE_OPTIONS.filter((option) => selection[option.type]).length, 0),
    [pickerSelections]
  );
  const pendingElementCount = useMemo(
    () => Object.values(pickerSelections).filter((selection) => CANDIDATE_RULE_OPTIONS.some((option) => selection[option.type])).length,
    [pickerSelections]
  );

  useEffect(() => {
    if (!pickerOpen || !selectedCandidate || !inspectResult) return;
    if (candidateSelectionSource === "preview") {
      scrollCandidateIntoView(selectedCandidate);
      return;
    }
    if (candidateSelectionSource === "candidate") {
      scrollPreviewToCandidate(selectedCandidate);
    }
  }, [candidateSelectionSource, filteredCandidates, inspectResult, pickerOpen, selectedCandidate]);

  useEffect(() => {
    setInspectResult(null);
    setSelectedCandidate(null);
    setPickerSelections({});
  }, [viewportMode]);

  useEffect(() => {
    setRuleInspectResult(null);
  }, [check.entry_url, check.setup_script, check.timeout_ms, value, viewportMode]);

  function commit(next: UiAssertion[]) {
    onChange(serializeUiAssertions(next));
  }

  function addAssertion(type: UiAssertionType) {
    commit([...assertions, createUiAssertion(type)]);
  }

  function selectCandidate(candidate: UiElementCandidate, source: CandidateSelectionSource = "preview") {
    setCandidateSelectionSource(source);
    setSelectedCandidate(candidate);
  }

  function setCandidateItemRef(key: string, node: HTMLElement | null) {
    if (node) {
      candidateItemRefs.current.set(key, node);
    } else {
      candidateItemRefs.current.delete(key);
    }
  }

  function scrollCandidateIntoView(candidate: UiElementCandidate) {
    const key = candidateKey(candidate);
    window.requestAnimationFrame(() => {
      const node = candidateItemRefs.current.get(key);
      node?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
    });
  }

  function scrollPreviewToCandidate(candidate: UiElementCandidate) {
    if (!inspectResult) return;
    window.requestAnimationFrame(() => {
      const scroll = previewScrollRef.current;
      const stage = previewStageRef.current;
      if (!scroll || !stage) return;
      const pageSize = inspectResult.page_size || inspectResult.viewport;
      const scale = stage.clientWidth / pageSize.width;
      const targetLeft = stage.offsetLeft + (candidate.box.x + candidate.box.width / 2) * scale - scroll.clientWidth / 2;
      const targetTop = stage.offsetTop + (candidate.box.y + candidate.box.height / 2) * scale - scroll.clientHeight / 2;
      scroll.scrollTo({
        left: Math.max(0, targetLeft),
        top: Math.max(0, targetTop),
        behavior: "smooth"
      });
    });
  }

  function buildCandidateAssertion(
    candidate: UiElementCandidate,
    type: CandidateRuleType
  ) {
    const assertion = createUiAssertion(type);
    if (type === "text_present") {
      assertion.expected_text = candidate.text || candidate.selector;
    } else if (type === "element_count") {
      assertion.selector = candidate.selector;
      assertion.operator = "eq";
      assertion.expected_count = 1;
    } else {
      assertion.selector = candidate.selector;
    }
    if (assertion.selector) {
      applyCandidateSelectorMetadata(assertion, candidate);
    }
    return assertion;
  }

  function toggleCandidateRule(candidate: UiElementCandidate, type: CandidateRuleType, checked: boolean) {
    if (type === "text_present" && !candidate.text) return;
    selectCandidate(candidate, "candidate");
    const key = candidateKey(candidate);
    setPickerSelections((current) => {
      const nextSelection = { ...(current[key] || {}), [type]: checked };
      if (!CANDIDATE_RULE_OPTIONS.some((option) => nextSelection[option.type])) {
        const { [key]: _removed, ...rest } = current;
        return rest;
      }
      return { ...current, [key]: nextSelection };
    });
  }

  function savePickerSelections() {
    if (!inspectResult || pendingRuleCount === 0) return;
    const candidateMap = new Map(inspectResult.candidates.map((candidate) => [candidateKey(candidate), candidate]));
    const nextAssertions: UiAssertion[] = [];
    const lowStabilityCandidates = new Map<string, UiElementCandidate>();
    Object.entries(pickerSelections).forEach(([key, selection]) => {
      const candidate = candidateMap.get(key);
      if (!candidate) return;
      CANDIDATE_RULE_OPTIONS.forEach((option) => {
        if (!selection[option.type]) return;
        if (candidate.stability === "low" && option.type !== "text_present") {
          lowStabilityCandidates.set(key, candidate);
        }
        nextAssertions.push(buildCandidateAssertion(candidate, option.type));
      });
    });
    if (!nextAssertions.length) return;
    const persist = () => {
      commit([...assertions, ...nextAssertions]);
      setPickerSelections({});
      setPickerOpen(false);
    };
    if (lowStabilityCandidates.size) {
      const candidates = Array.from(lowStabilityCandidates.values()).slice(0, 4);
      modal.confirm({
        title: "低稳定性 selector",
        content: (
          <div className="ui-selector-warning">
            <p>以下 selector 页面结构变化时更容易失效，建议优先选择 testid、role 或更稳定的元素。</p>
            <ul>
              {candidates.map((candidate) => (
                <li key={candidateKey(candidate)} title={candidate.selector}>
                  {candidateDisplayName(candidate)}
                </li>
              ))}
            </ul>
          </div>
        ),
        okText: "继续保存",
        cancelText: "返回调整",
        onOk: persist
      });
      return;
    }
    persist();
  }

  function updateAssertion(id: string, patch: Partial<UiAssertion>) {
    commit(assertions.map((assertion) => (assertion.id === id ? { ...assertion, ...patch } : assertion)));
  }

  function removeAssertion(id: string) {
    commit(assertions.filter((assertion) => assertion.id !== id));
  }

  function openPicker() {
    setPickerOpen(true);
    setInspectError(null);
    setPickerSelections({});
    setCandidateQuery("");
    setInspectResult(null);
    setSelectedCandidate(null);
    void inspectPage();
  }

  async function inspectPage() {
    const entryUrl = check.entry_url.trim();
    if (!entryUrl) {
      setInspectError("请先填写页面 URL");
      message.warning("请先填写页面 URL");
      return;
    }
    setInspecting(true);
    setInspectError(null);
    try {
      const result = await api.inspectUi({
        type: "ui",
        entry_url: entryUrl,
        timeout_ms: check.timeout_ms,
        viewport_mode: viewportMode,
        viewport_width: currentPreset.width,
        viewport_height: currentPreset.height,
        setup_script: check.setup_script || ""
      });
      setInspectResult(result);
      setCandidateSelectionSource("scan");
      setSelectedCandidate(result.candidates[0] || null);
      setPickerSelections({});
      setCandidateQuery("");
    } catch (err) {
      const nextError = (err as Error).message;
      setInspectError(nextError);
      message.error(nextError);
    } finally {
      setInspecting(false);
    }
  }

  async function inspectRules() {
    const entryUrl = check.entry_url.trim();
    if (!entryUrl) {
      message.warning("请先填写页面 URL");
      return;
    }
    if (!selectorRuleCount) {
      message.warning("当前没有可检测的 selector 规则");
      return;
    }
    setRuleInspecting(true);
    try {
      const result = await api.inspectUiRules({
        type: "ui",
        entry_url: entryUrl,
        timeout_ms: check.timeout_ms,
        viewport_mode: viewportMode,
        viewport_width: currentPreset.width,
        viewport_height: currentPreset.height,
        setup_script: check.setup_script || "",
        assertions_json: serializeUiAssertions(assertions)
      });
      setRuleInspectResult(result);
      const abnormal = result.results.filter((item) => item.status !== "ok" && item.status !== "disabled");
      if (abnormal.length) {
        message.warning(`检测完成，${abnormal.length} 条 selector 需要关注`);
      } else {
        message.success("检测完成，selector 匹配正常");
      }
    } catch (err) {
      const nextError = (err as Error).message;
      message.error(nextError);
    } finally {
      setRuleInspecting(false);
    }
  }

  function handlePreviewClick(event: MouseEvent<HTMLDivElement>) {
    if (!inspectResult) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const pageSize = inspectResult.page_size || inspectResult.viewport;
    const x = ((event.clientX - rect.left) / rect.width) * pageSize.width;
    const y = ((event.clientY - rect.top) / rect.height) * pageSize.height;
    const candidate = filteredCandidates
      .filter((item) => containsPoint(item, x, y))
      .sort((left, right) => candidateArea(left) - candidateArea(right))[0];
    if (candidate) selectCandidate(candidate, "preview");
  }

  const columns: ColumnsType<UiAssertion> = [
    {
      title: "启用",
      dataIndex: "enabled",
      width: 64,
      render: (_, assertion) => (
        <Switch
          size="small"
          aria-label={`${UI_ASSERTION_LABELS[assertion.type]} 规则启用状态`}
          checked={assertion.enabled}
          onChange={(enabled) => updateAssertion(assertion.id, { enabled })}
        />
      )
    },
    {
      title: "类型",
      dataIndex: "type",
      width: 116,
      render: (_, assertion) => <Tag>{UI_ASSERTION_LABELS[assertion.type]}</Tag>
    },
    {
      title: "规则",
      dataIndex: "selector",
      render: (_, assertion) => renderRuleEditor(assertion, updateAssertion, ruleInspectionById.get(assertion.id))
    },
    {
      title: "操作",
      width: 64,
      align: "center",
      render: (_, assertion) => (
        <Tooltip title="删除规则">
          <Button size="small" danger aria-label="删除规则" icon={<Trash2 size={15} />} onClick={() => removeAssertion(assertion.id)} />
        </Tooltip>
      )
    }
  ];

  return (
    <section className="ui-assertions-panel">
      {modalContextHolder}
      <div className="section-title ui-assertions-header">
        <div>
          <h3>UI 校验</h3>
          <span>{enabledCount} 项启用</span>
        </div>
        <Space wrap>
          <Button icon={<MousePointer2 size={15} />} onClick={openPicker}>
            选择元素
          </Button>
          <Button icon={<ScanSearch size={15} />} onClick={() => void inspectRules()} loading={ruleInspecting} disabled={!selectorRuleCount}>
            检测规则
          </Button>
          <Button icon={<Plus size={15} />} onClick={() => addAssertion("title_contains")}>
            添加标题校验
          </Button>
        </Space>
      </div>

      <div className="ui-assertion-actions">
        {RULE_OPTIONS.map((option) => (
          <Button key={option.type} size="small" icon={option.icon} onClick={() => addAssertion(option.type)}>
            {option.label}
          </Button>
        ))}
      </div>

      {assertions.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={false} />
      ) : (
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          columns={columns}
          dataSource={assertions}
          className="ui-assertions-table"
          scroll={{ x: 720 }}
        />
      )}

      <Modal
        open={pickerOpen}
        title="选择页面元素"
        width="min(1420px, 96vw)"
        footer={
          <div className="ui-picker-footer">
            {pendingRuleCount ? <span>{`已选择 ${pendingElementCount} 个元素 / ${pendingRuleCount} 条规则`}</span> : <span />}
            <Space>
              <Button onClick={() => setPickerOpen(false)}>取消</Button>
              <Button icon={<Save size={15} />} disabled={!pendingRuleCount} onClick={savePickerSelections}>
                保存选择
              </Button>
            </Space>
          </div>
        }
        className="ui-picker-modal"
        onCancel={() => setPickerOpen(false)}
      >
        <div className="ui-picker-shell">
          <div className="ui-picker-toolbar">
            <div className="ui-picker-url">
              <small>页面 URL</small>
              <strong title={check.entry_url}>{check.entry_url || "未填写"}</strong>
            </div>
            <Tag>
              <span className="ui-picker-viewport-label">
                {currentPreset.icon}
                {currentPreset.label}
              </span>
            </Tag>
            <Tag>
              {currentPreset.width} × {currentPreset.height}
            </Tag>
            <Button icon={<ScanSearch size={15} />} onClick={() => void inspectPage()} loading={inspecting}>
              {inspecting ? "正在扫描" : inspectResult ? "重新扫描" : "扫描页面"}
            </Button>
          </div>

          <div className="ui-picker-layout">
            <section className="ui-picker-preview-card">
              <div className="ui-picker-card-title">
                <div>
                  <strong>页面预览</strong>
                </div>
                {inspectResult ? (
                  <Tag color="blue">{filteredCandidates.length} 个候选</Tag>
                ) : inspecting ? (
                  <Tag color="processing">扫描中</Tag>
                ) : inspectError ? (
                  <Tag color="error">扫描失败</Tag>
                ) : (
                  <Tag>未扫描</Tag>
                )}
              </div>
              {inspectResult ? (
                <div className="ui-picker-preview-scroll" ref={previewScrollRef}>
                  <div
                    ref={previewStageRef}
                    className={["ui-inspect-stage", viewportMode === "h5" ? "h5" : ""].filter(Boolean).join(" ")}
                    role="button"
                    tabIndex={0}
                    onClick={handlePreviewClick}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && selectedCandidate) selectCandidate(selectedCandidate, "preview");
                    }}
                  >
                    <img src={inspectResult.screenshot} alt={inspectResult.title || inspectResult.url} draggable={false} />
                    {markerCandidates.map((candidate, index) => (
                      <Button
                        key={`${candidate.selector}-${candidate.box.x}-${candidate.box.y}`}
                        className={["ui-inspect-marker", selectedCandidate === candidate ? "selected" : ""].filter(Boolean).join(" ")}
                        title={candidateLabel(candidate)}
                        aria-label={`选择元素 ${candidateLabel(candidate)}`}
                        style={markerStyle(candidate, inspectResult, index)}
                        onClick={(event) => {
                          event.stopPropagation();
                          selectCandidate(candidate, "preview");
                        }}
                      />
                    ))}
                  </div>
                </div>
              ) : inspecting ? (
                <div className="ui-picker-loading" aria-live="polite">
                  <Spin />
                </div>
              ) : inspectError ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={false}>
                  <Button icon={<ScanSearch size={15} />} onClick={() => void inspectPage()} loading={inspecting}>
                    重新扫描
                  </Button>
                </Empty>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={false}>
                  <Button icon={<ScanSearch size={15} />} onClick={() => void inspectPage()} loading={inspecting}>
                    扫描页面
                  </Button>
                </Empty>
              )}
            </section>

            <aside className="ui-picker-side">
              <section className="ui-candidate-card">
                <div className="ui-picker-card-title">
                  <div>
                    <strong>候选元素</strong>
                    <span>{filteredCandidates.length} / {inspectResult?.candidates.length || 0} 个候选</span>
                  </div>
                  <Input
                    className="ui-candidate-search"
                    size="small"
                    value={candidateQuery}
                    prefix={<Search size={15} />}
                    placeholder="搜索名称 / selector…"
                    allowClear
                    onChange={(event) => setCandidateQuery(event.target.value)}
                  />
                </div>
                {filteredCandidates.length ? (
                  <div className="ui-candidate-list">
                    {filteredCandidates.slice(0, 120).map((candidate) => {
                      const key = candidateKey(candidate);
                      const selection = pickerSelections[key] || {};
                      const checkedCount = CANDIDATE_RULE_OPTIONS.filter((option) => selection[option.type]).length;
                      return (
                      <article
                        key={key}
                        ref={(node) => setCandidateItemRef(key, node)}
                        className={[
                          "ui-candidate-item",
                          selectedCandidate === candidate ? "selected" : "",
                          checkedCount ? "checked" : ""
                        ]
                          .filter(Boolean)
                          .join(" ")}
                      >
                        <div
                          className="ui-candidate-main"
                          role="button"
                          tabIndex={0}
                          onClick={() => selectCandidate(candidate, "candidate")}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") selectCandidate(candidate, "candidate");
                          }}
                        >
                          <span className="ui-candidate-meta">
                            <Tag>{candidateKindLabel(candidate)}</Tag>
                            <Tag>{candidate.role || candidate.tag}</Tag>
                            {candidate.selector_type && <Tag>{candidate.selector_type}</Tag>}
                            {candidate.stability && <Tag color={candidateStabilityColor(candidate.stability)}>{stabilityLabel(candidate.stability)}</Tag>}
                          </span>
                          <strong className="ui-candidate-name" title={candidateDisplayName(candidate)}>
                            {candidateDisplayName(candidate)}
                          </strong>
                          <small title={candidate.selector}>{candidate.selector}</small>
                          {candidate.text && <em title={candidate.text}>{candidate.text}</em>}
                        </div>
                        <div className="ui-candidate-rule-grid">
                          {CANDIDATE_RULE_OPTIONS.map((option) => (
                            <Checkbox
                              key={option.type}
                              checked={Boolean(selection[option.type])}
                              disabled={Boolean(option.requiresText && !candidate.text)}
                              onChange={(event) => toggleCandidateRule(candidate, option.type, event.target.checked)}
                            >
                              <span className="ui-candidate-rule-label">
                                {option.icon}
                                {option.label}
                              </span>
                            </Checkbox>
                          ))}
                        </div>
                      </article>
                      );
                    })}
                  </div>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={false} />
                )}
              </section>
            </aside>
          </div>
        </div>
      </Modal>
    </section>
  );
}

function renderRuleEditor(assertion: UiAssertion, update: (id: string, patch: Partial<UiAssertion>) => void, ruleInspection?: UiRuleInspectItem) {
  if (["element_visible", "element_hidden", "element_not_empty"].includes(assertion.type)) {
    return (
      <Space className="ui-assertion-rule" wrap>
        <Input
          value={assertion.selector}
          placeholder="CSS / text= / role= Playwright 选择器…"
          onChange={(event) => update(assertion.id, { selector: event.target.value })}
        />
        {renderSelectorMetadata(assertion)}
        {renderRuleInspection(ruleInspection)}
      </Space>
    );
  }
  if (["text_present", "text_absent", "title_contains", "url_contains"].includes(assertion.type)) {
    return (
      <Space className="ui-assertion-rule" wrap>
        <Input
          value={assertion.expected_text}
          placeholder={assertion.type.includes("text") ? "输入要匹配的文本" : "输入要包含的片段"}
          onChange={(event) => update(assertion.id, { expected_text: event.target.value })}
        />
      </Space>
    );
  }
  if (assertion.type === "element_count") {
    return (
      <Space className="ui-assertion-rule" wrap>
        <Input
          value={assertion.selector}
          placeholder="CSS / text= / role= Playwright 选择器…"
          onChange={(event) => update(assertion.id, { selector: event.target.value })}
        />
        {renderSelectorMetadata(assertion)}
        {renderRuleInspection(ruleInspection)}
        <Select
          value={assertion.operator || "eq"}
          className="ui-assertion-operator"
          options={OPERATOR_OPTIONS}
          onChange={(operator) => update(assertion.id, { operator })}
        />
        <InputNumber
          min={0}
          value={assertion.expected_count}
          onChange={(expected_count) => update(assertion.id, { expected_count: Number(expected_count || 0) })}
        />
      </Space>
    );
  }
  return <Tag color="success">无需配置</Tag>;
}

function renderRuleInspection(result?: UiRuleInspectItem) {
  if (!result) return null;
  const meta = ruleInspectionMeta(result);
  return (
    <Tooltip title={result.message || meta.tooltip}>
      <Tag color={meta.color}>{meta.label}</Tag>
    </Tooltip>
  );
}

function ruleInspectionMeta(result: UiRuleInspectItem): { label: string; color: string; tooltip: string } {
  if (result.status === "ok") {
    return { label: typeof result.count === "number" ? `匹配 ${result.count}` : "匹配正常", color: "success", tooltip: "selector 当前匹配正常" };
  }
  if (result.status === "missing") return { label: "未匹配", color: "warning", tooltip: "selector 当前未匹配到元素" };
  if (result.status === "multiple") return { label: `匹配 ${result.count ?? "多"} 个`, color: "warning", tooltip: "selector 当前匹配多个元素" };
  if (result.status === "invalid_selector") return { label: "选择器无效", color: "error", tooltip: "selector 无法解析" };
  if (result.status === "disabled") return { label: "未检测", color: "default", tooltip: "规则已停用" };
  return { label: "检测失败", color: "error", tooltip: "规则检测失败" };
}

function renderSelectorMetadata(assertion: UiAssertion) {
  if (!assertion.selector_type && !assertion.selector_stability && typeof assertion.selector_score !== "number") return null;
  const stability = assertion.selector_stability;
  const label = stability ? `稳定性${stabilityLabel(stability)}` : "扫描来源";
  const score = typeof assertion.selector_score === "number" ? `，评分 ${Math.round(assertion.selector_score)}` : "";
  return (
    <Tooltip title={`来源 ${assertion.selector_type || "未知"}${score}`}>
      <Tag color={candidateStabilityColor(stability)}>{label}</Tag>
    </Tooltip>
  );
}

function isSelectorAssertion(assertion: UiAssertion): boolean {
  return ["element_visible", "element_hidden", "element_not_empty", "element_count"].includes(assertion.type);
}

function applyCandidateSelectorMetadata(assertion: UiAssertion, candidate: UiElementCandidate) {
  if (candidate.selector_type) assertion.selector_type = candidate.selector_type;
  if (candidate.stability) assertion.selector_stability = candidate.stability;
  if (typeof candidate.score === "number") assertion.selector_score = candidate.score;
}

function candidateStabilityColor(stability: UiElementCandidate["stability"]) {
  if (stability === "high") return "success";
  if (stability === "medium") return "warning";
  return "default";
}

function containsPoint(candidate: UiElementCandidate, x: number, y: number): boolean {
  return (
    x >= candidate.box.x &&
    x <= candidate.box.x + candidate.box.width &&
    y >= candidate.box.y &&
    y <= candidate.box.y + candidate.box.height
  );
}

function candidateArea(candidate: UiElementCandidate): number {
  return candidate.box.width * candidate.box.height;
}

function candidateLabel(candidate: UiElementCandidate): string {
  return candidateDisplayName(candidate) || candidate.text || candidate.selector || candidate.role || candidate.tag;
}

function candidateDisplayName(candidate: UiElementCandidate): string {
  return candidate.name || candidate.text || candidate.selector || candidate.role || candidate.tag;
}

function candidateKey(candidate: UiElementCandidate): string {
  return [
    candidate.selector,
    Math.round(candidate.box.x),
    Math.round(candidate.box.y),
    Math.round(candidate.box.width),
    Math.round(candidate.box.height)
  ].join("|");
}

function stabilityLabel(stability: NonNullable<UiElementCandidate["stability"]>): string {
  if (stability === "high") return "高";
  if (stability === "medium") return "中";
  return "低";
}

function candidateKindLabel(candidate: UiElementCandidate): string {
  return candidate.kind ? CANDIDATE_KIND_LABELS[candidate.kind] : candidate.role || candidate.tag;
}

function markerStyle(candidate: UiElementCandidate, result: UiInspectResult, index: number): CSSProperties {
  const pageSize = result.page_size || result.viewport;
  return {
    left: `${(candidate.box.x / pageSize.width) * 100}%`,
    top: `${(candidate.box.y / pageSize.height) * 100}%`,
    width: `${(candidate.box.width / pageSize.width) * 100}%`,
    height: `${(candidate.box.height / pageSize.height) * 100}%`,
    zIndex: 10 + index
  };
}
