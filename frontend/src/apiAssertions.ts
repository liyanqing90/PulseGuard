import type { ApiAssertion, ApiAssertionType, ApiJsonValueType, ApiLengthOperator } from "./types";

export const API_ASSERTION_LABELS: Record<ApiAssertionType, string> = {
  status_code: "状态码",
  response_time: "响应耗时",
  json_path_exists: "字段存在",
  json_path_equals: "字段等于",
  json_path_not_empty: "字段非空",
  json_path_contains: "字段包含",
  json_path_type: "字段类型",
  json_path_length: "字段长度"
};

export const JSON_FIELD_ASSERTION_TYPES: ApiAssertionType[] = [
  "json_path_exists",
  "json_path_equals",
  "json_path_not_empty",
  "json_path_contains",
  "json_path_type",
  "json_path_length"
];

export const API_JSON_VALUE_TYPE_LABELS: Record<ApiJsonValueType, string> = {
  string: "字符串",
  number: "数字",
  boolean: "布尔",
  object: "对象",
  array: "数组",
  null: "空值"
};

export const API_LENGTH_OPERATOR_LABELS: Record<ApiLengthOperator, string> = {
  eq: "=",
  ne: "!=",
  gt: ">",
  gte: ">=",
  lt: "<",
  lte: "<="
};

export function parseApiAssertions(raw?: string | null): ApiAssertion[] {
  if (!raw?.trim()) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map(normalizeAssertion).filter(Boolean) as ApiAssertion[];
  } catch {
    return [];
  }
}

export function serializeApiAssertions(assertions: ApiAssertion[]): string {
  return JSON.stringify(assertions.map(normalizeAssertion).filter(Boolean), null, 2);
}

export function hasEnabledApiAssertions(raw?: string | null): boolean {
  return parseApiAssertions(raw).some((assertion) => assertion.enabled);
}

export function createApiAssertion(type: ApiAssertionType, path?: string, seed: Partial<ApiAssertion> = {}): ApiAssertion {
  const id = `${type}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  if (type === "status_code") return { id, type, enabled: true, expected_status: 200 };
  if (type === "response_time") return { id, type, enabled: true, max_ms: 1000 };
  const targetPath = cleanJsonPath(path || seed.path);
  if (type === "json_path_equals") {
    return { id, type, enabled: true, path: targetPath, expected_value: seed.expected_value ?? "" };
  }
  if (type === "json_path_contains") {
    return { id, type, enabled: true, path: targetPath, expected_value: seed.expected_value ?? "" };
  }
  if (type === "json_path_type") {
    return { id, type, enabled: true, path: targetPath, expected_type: normalizeValueType(seed.expected_type) };
  }
  if (type === "json_path_length") {
    return {
      id,
      type,
      enabled: true,
      path: targetPath,
      operator: normalizeLengthOperator(seed.operator),
      expected_length: Math.max(0, Number(seed.expected_length ?? 1))
    };
  }
  return { id, type, enabled: true, path: targetPath };
}

function normalizeAssertion(value: unknown): ApiAssertion | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Partial<ApiAssertion>;
  if (!item.type || !(item.type in API_ASSERTION_LABELS)) return null;
  const base = {
    id: String(item.id || `${item.type}-${Date.now()}`),
    type: item.type,
    enabled: item.enabled !== false
  } satisfies Pick<ApiAssertion, "id" | "type" | "enabled">;

  if (item.type === "status_code") {
    return { ...base, expected_status: Math.max(100, Math.min(599, Number(item.expected_status || 200))) };
  }
  if (item.type === "response_time") {
    return { ...base, max_ms: Math.max(1, Number(item.max_ms || 1000)) };
  }
  if (item.type === "json_path_equals") {
    return { ...base, path: cleanJsonPath(item.path), expected_value: item.expected_value ?? "" };
  }
  if (item.type === "json_path_contains") {
    return { ...base, path: cleanJsonPath(item.path), expected_value: item.expected_value ?? "" };
  }
  if (item.type === "json_path_type") {
    return { ...base, path: cleanJsonPath(item.path), expected_type: normalizeValueType(item.expected_type) };
  }
  if (item.type === "json_path_length") {
    return {
      ...base,
      path: cleanJsonPath(item.path),
      operator: normalizeLengthOperator(item.operator),
      expected_length: Math.max(0, Number(item.expected_length ?? 1))
    };
  }
  return { ...base, path: cleanJsonPath(item.path) };
}

function cleanJsonPath(value: unknown): string {
  const path = String(value || "").trim();
  return path.startsWith("$") ? path : "$";
}

function normalizeValueType(value: unknown): ApiJsonValueType {
  return value === "number" || value === "boolean" || value === "object" || value === "array" || value === "null"
    ? value
    : "string";
}

function normalizeLengthOperator(value: unknown): ApiLengthOperator {
  return value === "eq" || value === "ne" || value === "gt" || value === "lt" || value === "lte" ? value : "gte";
}
