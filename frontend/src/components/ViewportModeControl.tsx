import { Segmented } from "antd";
import { Monitor, MonitorSmartphone } from "lucide-react";
import type { ReactNode } from "react";
import type { ViewportMode } from "../types";

export const VIEWPORT_PRESETS: Record<ViewportMode, { label: string; width: number; height: number; icon: ReactNode }> = {
  web: { label: "Web", width: 1440, height: 900, icon: <Monitor size={15} /> },
  h5: { label: "H5", width: 390, height: 844, icon: <MonitorSmartphone size={15} /> }
};

interface ViewportModeControlProps {
  value: ViewportMode;
  onChange: (value: ViewportMode) => void;
}

export function ViewportModeControl({ value, onChange }: ViewportModeControlProps) {
  return (
    <Segmented
      value={value}
      options={(Object.entries(VIEWPORT_PRESETS) as Array<[ViewportMode, (typeof VIEWPORT_PRESETS)[ViewportMode]]>).map(([mode, preset]) => ({
        value: mode,
        label: (
          <span className="ui-picker-viewport-label">
            {preset.icon}
            {preset.label}
          </span>
        )
      }))}
      onChange={(mode) => onChange(mode as ViewportMode)}
    />
  );
}
