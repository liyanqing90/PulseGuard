import { Skeleton } from "antd";
import { lazy, Suspense } from "react";
import type { CodeEditorPanelProps } from "./CodeEditorPanel";

const CodeEditorPanel = lazy(() => import("./CodeEditorPanel").then((module) => ({ default: module.CodeEditorPanel })));

export function LazyCodeEditorPanel(props: CodeEditorPanelProps) {
  return (
    <Suspense fallback={<EditorLoading title={props.title} compact={props.compact} />}>
      <CodeEditorPanel {...props} />
    </Suspense>
  );
}

function EditorLoading({ title, compact }: Pick<CodeEditorPanelProps, "title" | "compact">) {
  return (
    <section className="editor-section code-editor-panel">
      <div className="section-title code-editor-header">
        <h3>{title}</h3>
      </div>
      <div className={`editor-frame ${compact ? "compact" : ""}`}>
        <Skeleton active title={false} paragraph={{ rows: compact ? 4 : 8 }} />
      </div>
    </section>
  );
}
