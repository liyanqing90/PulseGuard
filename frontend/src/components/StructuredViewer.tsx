import { Empty, Segmented, Skeleton } from "antd";
import { lazy, Suspense, useMemo, useState } from "react";

const JsonTreeViewer = lazy(() => import("./JsonTreeViewer").then((module) => ({ default: module.JsonTreeViewer })));
const MarkdownViewer = lazy(() => import("./MarkdownViewer").then((module) => ({ default: module.MarkdownViewer })));

type ViewerMode = "auto" | "json" | "markdown" | "text";

interface Props {
  title?: string;
  value?: unknown;
  defaultMode?: ViewerMode;
}

export function StructuredViewer({ title, value, defaultMode = "auto" }: Props) {
  const [mode, setMode] = useState<ViewerMode>(defaultMode);
  const parsed = useMemo(() => parseViewerValue(value), [value]);
  const effectiveMode = mode === "auto" ? parsed.detectedMode : mode;

  return (
    <section className="structured-viewer">
      <div className="structured-viewer-header">
        <strong>{title || "内容"}</strong>
        <Segmented
          size="small"
          value={mode}
          onChange={(next) => setMode(next as ViewerMode)}
          options={[
            { label: "自动", value: "auto" },
            { label: "JSON", value: "json" },
            { label: "Markdown", value: "markdown" },
            { label: "文本", value: "text" }
          ]}
        />
      </div>
      <div className="structured-viewer-body">{renderValue(parsed, effectiveMode)}</div>
    </section>
  );
}

function renderValue(parsed: ParsedValue, mode: Exclude<ViewerMode, "auto">) {
  if (parsed.empty) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无内容" />;
  }

  if (mode === "json") {
    if (!parsed.jsonValid) {
      return <pre className="code-block">{parsed.text}</pre>;
    }
    return (
      <div className="json-view-shell">
        <Suspense fallback={<ViewerLoading />}>
          <JsonTreeViewer value={asJsonObject(parsed.jsonValue)} />
        </Suspense>
      </div>
    );
  }

  if (mode === "markdown") {
    return (
      <div className="markdown-body">
        <Suspense fallback={<ViewerLoading />}>
          <MarkdownViewer value={parsed.text} />
        </Suspense>
      </div>
    );
  }

  return <pre className="code-block">{parsed.text}</pre>;
}

interface ParsedValue {
  empty: boolean;
  text: string;
  jsonValid: boolean;
  jsonValue: unknown;
  detectedMode: Exclude<ViewerMode, "auto">;
}

function parseViewerValue(value: unknown): ParsedValue {
  if (value === null || value === undefined || value === "") {
    return {
      empty: true,
      text: "",
      jsonValid: false,
      jsonValue: null,
      detectedMode: "text"
    };
  }

  if (typeof value !== "string") {
    return {
      empty: false,
      text: JSON.stringify(value, null, 2),
      jsonValid: true,
      jsonValue: value,
      detectedMode: "json"
    };
  }

  const text = value.trim();
  if (!text) {
    return {
      empty: true,
      text: "",
      jsonValid: false,
      jsonValue: null,
      detectedMode: "text"
    };
  }

  try {
    const jsonValue = JSON.parse(text);
    return {
      empty: false,
      text: JSON.stringify(jsonValue, null, 2),
      jsonValid: true,
      jsonValue,
      detectedMode: "json"
    };
  } catch {
    return {
      empty: false,
      text,
      jsonValid: false,
      jsonValue: null,
      detectedMode: looksLikeMarkdown(text) ? "markdown" : "text"
    };
  }
}

function ViewerLoading() {
  return (
    <div className="structured-viewer-loading">
      <Skeleton active paragraph={{ rows: 3 }} title={false} />
    </div>
  );
}

function looksLikeMarkdown(text: string): boolean {
  return /(^#{1,6}\s)|(```)|(^\s*[-*]\s)|(\|.+\|)|(\[[^\]]+\]\([^)]+\))/m.test(text);
}

function asJsonObject(value: unknown): object {
  if (value !== null && typeof value === "object") {
    return value;
  }
  return { value };
}
