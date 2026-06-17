import type { ThemeConfig } from "antd";

const uiFont =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", system-ui, sans-serif';

export const palette = {
  background: "#f4f6f8",
  surface: "#fbfcfd",
  surfaceMuted: "#f1f4f7",
  text: "#1f2328",
  textMuted: "#656d76",
  border: "#d8dee4",
  borderStrong: "#afb8c1",
  primary: "#2563eb",
  primaryHover: "#1d4ed8",
  primarySoft: "#eaf2ff",
  success: "#16833a",
  successSoft: "#dafbe1",
  danger: "#d1242f",
  dangerSoft: "#ffebe9",
  warning: "#9a6700",
  warningSoft: "#fff8c5",
  info: "#0969da",
  infoSoft: "#ddf4ff"
} as const;

export const fonts = {
  ui: uiFont,
  heading: uiFont,
  numeric: uiFont,
  code: '"Cascadia Mono", "SFMono-Regular", "JetBrains Mono", Consolas, monospace'
} as const;

export const fontWeights = {
  regular: 400,
  medium: 500,
  semibold: 600,
  bold: 700
} as const;

export const typeScale = {
  small: "0.6875rem",
  caption: "0.75rem",
  meta: "0.8125rem",
  body: "0.875rem",
  title: "0.9375rem",
  section: "1.0625rem",
  page: "1.25rem",
  metric: "1.5rem"
} as const;

export const radii = {
  small: 4,
  tight: 6,
  default: 8
} as const;

export const spacing = {
  inner: 8,
  xs: 6,
  field: 12,
  sm: 10,
  surface: 14,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48
} as const;

export const lineHeights = {
  tight: 1.15,
  normal: 1.35,
  body: 1.5,
  caption: 1.45
} as const;

export const semanticTones = {
  neutral: {
    color: palette.textMuted,
    background: palette.surfaceMuted,
    border: palette.border
  },
  info: {
    color: palette.info,
    background: palette.infoSoft,
    border: palette.border
  },
  processing: {
    color: palette.info,
    background: palette.infoSoft,
    border: palette.border
  },
  success: {
    color: palette.success,
    background: palette.successSoft,
    border: palette.border
  },
  warning: {
    color: palette.warning,
    background: palette.warningSoft,
    border: palette.border
  },
  danger: {
    color: palette.danger,
    background: palette.dangerSoft,
    border: palette.border
  }
} as const;

export const pulseGuardTheme: ThemeConfig = {
  token: {
    colorPrimary: palette.primary,
    colorSuccess: palette.success,
    colorError: palette.danger,
    colorWarning: palette.warning,
    colorInfo: palette.info,
    colorBgBase: palette.background,
    colorBgContainer: palette.surface,
    colorBgLayout: palette.background,
    colorBorder: palette.border,
    colorBorderSecondary: palette.border,
    colorText: palette.text,
    colorTextSecondary: palette.textMuted,
    motionDurationFast: "0.12s",
    motionDurationMid: "0.16s",
    motionDurationSlow: "0.22s",
    motionEaseInBack: "cubic-bezier(0.7, 0, 0.84, 0)",
    motionEaseInOut: "cubic-bezier(0.65, 0, 0.35, 1)",
    motionEaseInOutCirc: "cubic-bezier(0.65, 0, 0.35, 1)",
    motionEaseInQuint: "cubic-bezier(0.64, 0, 0.78, 0)",
    motionEaseOut: "cubic-bezier(0.16, 1, 0.3, 1)",
    motionEaseOutBack: "cubic-bezier(0.16, 1, 0.3, 1)",
    motionEaseOutCirc: "cubic-bezier(0.16, 1, 0.3, 1)",
    motionEaseOutQuint: "cubic-bezier(0.16, 1, 0.3, 1)",
    borderRadius: radii.default,
    borderRadiusSM: radii.tight,
    borderRadiusLG: radii.default,
    controlHeight: 36,
    controlHeightSM: 30,
    controlHeightLG: 40,
    fontFamily: fonts.ui,
    fontSize: 14,
    fontSizeSM: 12,
    fontSizeLG: 16,
    fontSizeHeading1: 22,
    fontSizeHeading2: 20,
    fontSizeHeading3: 17,
    fontSizeHeading4: 16,
    fontSizeHeading5: 15,
    lineHeight: 1.5,
    wireframe: false
  },
  components: {
    Alert: {
      borderRadiusLG: radii.default
    },
    Button: {
      borderRadius: radii.tight,
      controlHeight: 36,
      controlHeightSM: 30,
      fontWeight: fontWeights.medium,
      primaryShadow: "none"
    },
    Card: {
      borderRadiusLG: radii.default,
      colorBgContainer: palette.surface,
      headerBg: palette.surface
    },
    Drawer: {
      colorBgElevated: palette.surface
    },
    Input: {
      borderRadius: radii.tight
    },
    InputNumber: {
      borderRadius: radii.tight
    },
    Menu: {
      itemBorderRadius: radii.tight,
      itemHeight: 40,
      itemMarginBlock: 3,
      itemMarginInline: 0,
      itemSelectedBg: palette.primarySoft,
      itemSelectedColor: palette.primaryHover
    },
    Modal: {
      borderRadiusLG: radii.default
    },
    Select: {
      borderRadius: radii.tight
    },
    Table: {
      borderColor: palette.border,
      headerBg: palette.surfaceMuted,
      headerColor: palette.textMuted,
      headerSplitColor: "transparent",
      rowHoverBg: palette.primarySoft,
      cellPaddingBlock: 12,
      cellPaddingBlockSM: 8
    },
    Tabs: {
      itemSelectedColor: palette.primaryHover,
      inkBarColor: palette.primary
    },
    Tag: {
      borderRadiusSM: radii.tight
    },
    Descriptions: {
      labelBg: palette.surfaceMuted,
      titleColor: palette.text
    },
    Segmented: {
      itemSelectedBg: palette.surface,
      trackBg: palette.surfaceMuted
    },
    Pagination: {
      itemSize: 32,
      itemBg: "transparent"
    },
    Collapse: {
      headerBg: palette.surfaceMuted,
      contentBg: palette.surface
    },
    Empty: {
      colorTextDescription: palette.textMuted
    },
    Skeleton: {
      colorFill: palette.surfaceMuted
    },
    Form: {
      labelColor: palette.textMuted,
      labelFontSize: 13,
      itemMarginBottom: 18
    }
  }
};
