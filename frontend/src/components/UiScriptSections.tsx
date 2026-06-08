import { Button, Collapse } from "antd";
import { uiScriptTemplate, uiSetupScriptTemplate } from "../defaults";
import { LazyCodeEditorPanel as CodeEditorPanel } from "./LazyCodeEditorPanel";

interface UiScriptSectionsProps {
  setupScript: string;
  script: string;
  setupHeight?: string;
  scriptHeight?: string;
  onSetupScriptChange: (value: string) => void;
  onScriptChange: (value: string) => void;
}

export function UiScriptSections({
  setupScript,
  script,
  setupHeight = "280px",
  scriptHeight = "320px",
  onSetupScriptChange,
  onScriptChange
}: UiScriptSectionsProps) {
  return (
    <Collapse
      className="advanced-script-collapse"
      items={[
        {
          key: "setup",
          label: "前置脚本",
          children: (
            <CodeEditorPanel
              title="前置 Python 脚本"
              language="python"
              value={setupScript}
              height={setupHeight}
              onChange={onSetupScriptChange}
              extra={
                !setupScript.trim() && (
                  <Button size="small" onClick={() => onSetupScriptChange(uiSetupScriptTemplate)}>
                    使用模板
                  </Button>
                )
              }
            />
          )
        },
        {
          key: "script",
          label: "高级脚本",
          children: (
            <CodeEditorPanel
              title="Python 脚本"
              language="python"
              value={script}
              height={scriptHeight}
              onChange={onScriptChange}
              extra={
                !script.trim() && (
                  <Button size="small" onClick={() => onScriptChange(uiScriptTemplate)}>
                    使用模板
                  </Button>
                )
              }
            />
          )
        }
      ]}
    />
  );
}
