import {
  Alert,
  Empty,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Tree
} from "antd";
import type { TreeProps } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Braces, Clock3, CopyPlus, FileJson2, ListChecks, MousePointer2, Plus, Send, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api";
import {
  API_ASSERTION_LABELS,
  API_JSON_VALUE_TYPE_LABELS,
  API_LENGTH_OPERATOR_LABELS,
  createApiAssertion,
  JSON_FIELD_ASSERTION_TYPES,
  parseApiAssertions,
  serializeApiAssertions
} from "../apiAssertions";
import { prepareApiInspectPayload, type BodyEditorMode } from "../checkPayload";
import {
  buildJsonPathTree,
  flattenJsonPathTree,
  jsonLength,
  jsonLiteral,
  jsonPreview,
  jsonValueType,
  parseJsonValue,
  readJsonPath,
  type JsonPathNode
} from "../jsonPath";
import type { ApiAssertion, ApiAssertionType, ApiInspectResult, CheckPayload } from "../types";
import { formatDuration } from "../utils";
import { AppButton as Button } from "./common/AppButton";
import { StructuredViewer } from "./StructuredViewer";

interface Props {
  bodyMode: BodyEditorMode;
  check: CheckPayload;
  value: string;
  onChange: (value: string) => void;
}

const BASIC_ASSERTION_ADD_OPTIONS: Array<{ type: ApiAssertionType; label: string }> = [
  { type: "status_code", label: "状态码" },
  { type: "response_time", label: "耗时" }
];

const SELECTED_FIELD_ACTIONS: Array<{ type: ApiAssertionType; label: string; needsLength?: boolean }> = [
  { type: "json_path_exists", label: "存在" },
  { type: "json_path_equals", label: "等于" },
  { type: "json_path_not_empty", label: "非空" },
  { type: "json_path_contains", label: "包含" },
  { type: "json_path_type", label: "类型" },
  { type: "json_path_length", label: "长度", needsLength: true }
];

export function ApiAssertionsBuilder({ bodyMode, check, value, onChange }: Props) {
  const [inspectResult, setInspectResult] = useState<ApiInspectResult | null>(null);
  const [selectedPath, setSelectedPath] = useState<string>("");
  const [inspecting, setInspecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const assertions = useMemo(() => parseApiAssertions(value), [value]);
  const parsedBody = useMemo(() => (inspectResult?.json_valid ? parseJsonValue(inspectResult.body) : { valid: false as const, value: null }), [inspectResult]);
  const tree = useMemo(() => (parsedBody.valid ? buildJsonPathTree(parsedBody.value) : []), [parsedBody]);
  const flatNodes = useMemo(() => flattenJsonPathTree(tree), [tree]);
  const selectedNode = useMemo(() => {
    if (!parsedBody.valid || !selectedPath) return null;
    const knownNode = flatNodes.find((node) => node.path === selectedPath);
    if (knownNode) return knownNode;
    const resolved = readJsonPath(parsedBody.value, selectedPath);
    if (!resolved.exists) return null;
    return {
      key: selectedPath,
      path: selectedPath,
      type: jsonValueType(resolved.value),
      preview: jsonPreview(resolved.value),
      length: jsonLength(resolved.value),
      value: resolved.value
    } satisfies JsonPathNode;
  }, [flatNodes, parsedBody, selectedPath]);
  const pathOptions = useMemo(
    () =>
      flatNodes.map((item) => ({
        value: item.path,
        label: `${item.path} · ${API_JSON_VALUE_TYPE_LABELS[item.type]}`
      })),
    [flatNodes]
  );
  const treeData = useMemo<TreeProps["treeData"]>(() => tree.map(toTreeNode), [tree]);

  function commit(next: ApiAssertion[]) {
    onChange(serializeApiAssertions(next));
  }

  function updateAssertion(id: string, patch: Partial<ApiAssertion>) {
    commit(assertions.map((assertion) => (assertion.id === id ? { ...assertion, ...patch } : assertion)));
  }

  function removeAssertion(id: string) {
    commit(assertions.filter((assertion) => assertion.id !== id));
  }

  function addAssertion(type: ApiAssertionType, path = selectedPath) {
    const seed = seedFromSelectedNode(type, selectedNode);
    commit([...assertions, createApiAssertion(type, path || firstSelectablePath(flatNodes), seed)]);
  }

  async function inspect() {
    setInspecting(true);
    setError(null);
    try {
      const payload = prepareApiInspectPayload(check, { bodyMode });
      const result = await api.inspectApi(payload);
      setInspectResult(result);
      if (result.json_valid) {
        const parsed = parseJsonValue(result.body);
        if (parsed.valid) {
          const nodes = flattenJsonPathTree(buildJsonPathTree(parsed.value));
          setSelectedPath(firstSelectablePath(nodes));
        }
      } else {
        setSelectedPath("");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setInspecting(false);
    }
  }

  const columns: ColumnsType<ApiAssertion> = [
    {
      title: "启用",
      width: 70,
      render: (_, assertion) => (
        <Switch size="small" checked={assertion.enabled} onChange={(enabled) => updateAssertion(assertion.id, { enabled })} />
      )
    },
    {
      title: "类型",
      width: 108,
      render: (_, assertion) => <Tag>{API_ASSERTION_LABELS[assertion.type]}</Tag>
    },
    {
      title: "规则",
      render: (_, assertion) => renderRuleEditor(assertion, pathOptions, updateAssertion)
    },
    {
      title: "操作",
      width: 70,
      align: "center",
      render: (_, assertion) => (
        <Button
          size="small"
          title="删除"
          aria-label="删除校验项"
          danger
          icon={<Trash2 size={14} />}
          onClick={() => removeAssertion(assertion.id)}
        />
      )
    }
  ];

  return (
    <section className="api-assertions-panel">
      <div className="section-title api-assertions-header">
        <div>
          <h3>接口校验</h3>
          <span>{assertions.filter((item) => item.enabled).length} 项启用</span>
        </div>
        <Space wrap>
          <Button icon={<Send size={15} />} onClick={inspect} loading={inspecting}>
            执行请求
          </Button>
          {BASIC_ASSERTION_ADD_OPTIONS.map((item) => (
            <Button key={item.type} size="small" icon={<Plus size={14} />} onClick={() => addAssertion(item.type)}>
              {item.label}
            </Button>
          ))}
        </Space>
      </div>

      {error && <Alert type="error" message={error} showIcon />}

      {inspectResult && (
        <div className="api-inspect-summary">
          <span>
            <ListChecks size={15} />
            HTTP {inspectResult.status_code}
          </span>
          <span>
            <Clock3 size={15} />
            {formatDuration(inspectResult.duration_ms)}
          </span>
          <span>
            <FileJson2 size={15} />
            {inspectResult.json_valid ? `${flatNodes.length} 个 JSON 节点` : "非 JSON 响应"}
          </span>
        </div>
      )}

      <div className="api-assertion-workbench">
        <section className="api-json-tree-card">
          <div className="api-json-tree-header">
            <strong>响应字段</strong>
            {selectedPath ? <Tag color="blue">{selectedPath}</Tag> : <Tag>先执行请求</Tag>}
          </div>
          {inspectResult ? (
            inspectResult.json_valid && treeData?.length ? (
              <Tree
                key={`${inspectResult.status_code}-${inspectResult.duration_ms}-${flatNodes.length}`}
                blockNode
                defaultExpandAll
                selectedKeys={selectedPath ? [selectedPath] : []}
                treeData={treeData}
                onSelect={(keys) => setSelectedPath(String(keys[0] || ""))}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="响应不是 JSON，字段校验不可选" />
            )
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="执行请求后可从返回 JSON 选择字段" />
          )}
        </section>

        <section className="api-selected-field-card">
          <div className="api-json-tree-header">
            <strong>添加字段校验</strong>
            <MousePointer2 size={15} />
          </div>
          {selectedNode ? (
            <>
              <div className="api-selected-field">
                <div>
                  <small>路径</small>
                  <strong>{selectedNode.path}</strong>
                </div>
                <div>
                  <small>类型</small>
                  <strong>{API_JSON_VALUE_TYPE_LABELS[selectedNode.type]}</strong>
                </div>
                <div>
                  <small>值预览</small>
                  <strong title={selectedNode.preview || "-"}>{selectedNode.preview || "-"}</strong>
                </div>
              </div>
              <Space wrap className="api-selected-actions">
                {SELECTED_FIELD_ACTIONS.map((item) => (
                  <Tooltip
                    key={item.type}
                    title={item.needsLength && selectedNode.length === null ? "字符串、数组和对象支持长度校验" : API_ASSERTION_LABELS[item.type]}
                  >
                    <Button
                      size="small"
                      icon={<CopyPlus size={14} />}
                      disabled={item.needsLength && selectedNode.length === null}
                      onClick={() => addAssertion(item.type, selectedNode.path)}
                    >
                      {item.label}
                    </Button>
                  </Tooltip>
                ))}
              </Space>
            </>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="在左侧选择一个 JSON 字段" />
          )}
        </section>
      </div>

      <Table
        rowKey="id"
        size="small"
        pagination={false}
        columns={columns}
        dataSource={assertions}
        className="api-assertions-table"
        scroll={{ x: 820 }}
        locale={{
          emptyText: (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无校验项">
              <Button intent="primary" size="small" icon={<Plus size={14} />} onClick={() => addAssertion("status_code")}>
                添加状态码
              </Button>
            </Empty>
          )
        }}
      />

      {inspectResult && (
        <StructuredViewer title="最近响应" value={inspectResult.body} defaultMode={inspectResult.json_valid ? "json" : "text"} />
      )}
    </section>
  );
}

function renderRuleEditor(
  assertion: ApiAssertion,
  pathOptions: Array<{ value: string; label: string }>,
  updateAssertion: (id: string, patch: Partial<ApiAssertion>) => void
) {
  if (assertion.type === "status_code") {
    return (
      <InputNumber
        min={100}
        max={599}
        value={assertion.expected_status}
        addonBefore="等于"
        onChange={(expected_status) => updateAssertion(assertion.id, { expected_status: Number(expected_status || 200) })}
      />
    );
  }

  if (assertion.type === "response_time") {
    return (
      <InputNumber
        min={1}
        value={assertion.max_ms}
        addonBefore="小于等于"
        addonAfter="ms"
        onChange={(max_ms) => updateAssertion(assertion.id, { max_ms: Number(max_ms || 1) })}
      />
    );
  }

  return (
    <Space className="api-assertion-rule" wrap>
      <Select
        showSearch
        value={assertion.path}
        options={pathOptions}
        onChange={(path) => updateAssertion(assertion.id, { path })}
        placeholder="先执行请求并选择字段"
        popupMatchSelectWidth={false}
        filterOption={(input, option) => String(option?.label || "").toLowerCase().includes(input.toLowerCase())}
      />
      {assertion.type === "json_path_equals" && (
        <Input
          value={assertion.expected_value}
          placeholder="期望值，支持 JSON 字面量"
          onChange={(event) => updateAssertion(assertion.id, { expected_value: event.target.value })}
        />
      )}
      {assertion.type === "json_path_contains" && (
        <Input
          value={assertion.expected_value}
          placeholder="包含的文本、数组元素或对象键"
          onChange={(event) => updateAssertion(assertion.id, { expected_value: event.target.value })}
        />
      )}
      {assertion.type === "json_path_type" && (
        <Select
          value={assertion.expected_type}
          className="api-assertion-mini-select"
          options={Object.entries(API_JSON_VALUE_TYPE_LABELS).map(([type, label]) => ({ value: type, label }))}
          onChange={(expected_type) => updateAssertion(assertion.id, { expected_type })}
        />
      )}
      {assertion.type === "json_path_length" && (
        <>
          <Select
            value={assertion.operator}
            className="api-assertion-operator"
            options={Object.entries(API_LENGTH_OPERATOR_LABELS).map(([operator, label]) => ({ value: operator, label }))}
            onChange={(operator) => updateAssertion(assertion.id, { operator })}
          />
          <InputNumber
            min={0}
            value={assertion.expected_length}
            addonAfter="长度"
            onChange={(expected_length) => updateAssertion(assertion.id, { expected_length: Number(expected_length || 0) })}
          />
        </>
      )}
    </Space>
  );
}

function toTreeNode(node: JsonPathNode): NonNullable<TreeProps["treeData"]>[number] {
  return {
    key: node.path,
    title: (
      <span className="api-json-tree-node">
        <Braces size={13} />
        <strong>{node.path === "$" ? "$ 根节点" : node.path.split(".").pop() || node.path}</strong>
        <Tag>{API_JSON_VALUE_TYPE_LABELS[node.type]}</Tag>
        {node.length !== null && <small>{node.length}</small>}
        {node.preview && <em title={node.preview}>{node.preview}</em>}
      </span>
    ),
    children: node.children?.map(toTreeNode)
  };
}

function firstSelectablePath(nodes: JsonPathNode[]): string {
  return nodes.find((node) => node.path !== "$")?.path || nodes[0]?.path || "";
}

function seedFromSelectedNode(type: ApiAssertionType, node: JsonPathNode | null): Partial<ApiAssertion> {
  if (!node || !JSON_FIELD_ASSERTION_TYPES.includes(type)) return {};
  if (type === "json_path_equals") return { path: node.path, expected_value: jsonLiteral(node.value) };
  if (type === "json_path_contains") {
    return { path: node.path, expected_value: typeof node.value === "string" ? node.value : node.type === "object" ? "" : jsonLiteral(node.value) };
  }
  if (type === "json_path_type") return { path: node.path, expected_type: node.type };
  if (type === "json_path_length") return { path: node.path, operator: "gte", expected_length: node.length ?? 1 };
  return { path: node.path };
}
