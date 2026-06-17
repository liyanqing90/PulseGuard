---
name: PulseGuard
description: Local UI and API probe console for operations work
colors:
  primary: "#2563eb"
  primary-hover: "#1d4ed8"
  primary-soft: "#eaf2ff"
  background: "#f4f6f8"
  surface: "#fbfcfd"
  surface-muted: "#f1f4f7"
  text: "#1f2328"
  text-muted: "#656d76"
  border: "#d8dee4"
  border-strong: "#afb8c1"
  success: "#16833a"
  danger: "#d1242f"
  warning: "#9a6700"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Hiragino Sans GB, Microsoft YaHei UI, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.25
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Hiragino Sans GB, Microsoft YaHei UI, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.35
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei UI, Segoe UI, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei UI, Segoe UI, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.45
  numeric:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Hiragino Sans GB, Microsoft YaHei UI, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.15
rounded:
  sm: "6px"
  md: "8px"
spacing:
  xs: "6px"
  sm: "10px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.sm}"
    height: "36px"
  status-chip:
    component: "AntD Tag"
    colors: "default, blue, processing, success, warning, error"
  metadata-chip:
    component: "AntD Tag"
    colors: "default, blue"
  panel:
    component: "AntD Card"
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
  metric:
    component: "AntD Card + Statistic"
    numericFont: "{typography.numeric.fontFamily}"
---

# Design System: PulseGuard

## 1. Overview

**Creative North Star: "Operations Ledger"**

PulseGuard should read like a working operations ledger: calm, native, explicit, and durable. The interface serves repeated monitoring work, so density is allowed when it improves scanning and action.

The system rejects AI dashboard cliches: decorative gradients, glass cards, generic Inter-only typography, fake hero panels, elastic easing, and motion that animates layout.

**Key Characteristics:**
- Quiet surfaces with restrained accent usage.
- Clear separation between page title, task title, metadata, and numeric status.
- Native controls from Ant Design, constrained by project tokens.
- Data and timestamps use tabular numeric treatment.

## 2. Colors

The palette is a restrained operational blue system with cool tinted neutrals.

### Primary
- **Control Blue** (#2563eb): Primary actions, active navigation, and focus highlights only.
- **Control Blue Soft** (#eaf2ff): Selected backgrounds and low-emphasis active states.

### Neutral
- **Workbench Background** (#f4f6f8): App canvas.
- **Panel Surface** (#fbfcfd): Cards, drawers, toolbars, and forms.
- **Muted Surface** (#f1f4f7): Table headers and recessed controls.
- **Ink** (#1f2328): Primary text.
- **Muted Ink** (#656d76): Labels and metadata.
- **Rule Border** (#d8dee4): Dividers and panel borders.

### Named Rules

**The Rare Accent Rule.** Blue is for current selection, primary action, and focus. It is not decoration.

## 3. Typography

**UI Font:** Native system UI stack with Segoe UI, PingFang SC, and Microsoft YaHei UI fallbacks  
**Heading Font:** Same as UI. Product surfaces use weight and spacing for hierarchy, not a second display family  
**Code Font:** Cascadia Mono or SFMono for code

**Character:** Native, technical, and readable. The goal is consistency and credibility, not typographic novelty.

### Hierarchy
- **Page** (600, 1.25rem, 1.25): Page titles.
- **Section** (600, 1.0625rem, 1.25): Command panels and settings section titles.
- **Title** (600, 0.9375rem, 1.35): Task names and card titles.
- **Body** (400, 0.875rem, 1.5): Form content, toolbar text, and descriptions.
- **Label** (500, 0.75rem, 1.45): Metadata and table headers.
- **Metric** (600, 1.5rem, 1.15): Counts and operational facts.

### Named Rules

**The One UI Family Rule.** Product UI uses one sans stack for headings, labels, data, and controls. Numbers use `font-variant-numeric: tabular-nums`, not a separate display numeric font.

## 4. Elevation

PulseGuard uses tonal layering and borders first. Shadows are reserved for overlays such as drawers and dialogs.

### Shadow Vocabulary
- **Overlay Shadow** (`0 16px 34px rgba(31, 35, 40, 0.12)`): Drawers, modals, and elevated transient UI only.

### Named Rules

**The Flat At Rest Rule.** Panels sit on borders and tonal contrast. Do not add decorative depth to routine cards.

## 5. Components

### Implementation Boundary
- Ant Design is the product design-system substrate.
- Import mature AntD primitives directly: `Button`, `Menu`, `Typography`, `Tag`, `Card`, `Statistic`, `Table`, `Form`, `Drawer`, `Modal`, `Tooltip`, `message`, and `notification`.
- Do not create local wrapper components for primitive controls such as Button, Tag, Card, Typography, or Menu.
- Shared design code is limited to tokens, CSS constraints, and business status mapping helpers. Reusable React components should encapsulate real product workflows, not restyle AntD primitives.
- Repeated page-local patterns may become business components only when they carry domain behavior or data transformation.

### Typography
- Use AntD `Typography` for page titles, labels, and text blocks where a semantic text component is useful.
- Numeric summaries and counts use AntD `Statistic` inside AntD `Card`, constrained by token-based CSS.
- Use only four weights: 400, 500, 600, 700. Routine UI should stay at 400/500/600.

### Buttons
- **Shape:** Compact rectangle with 6px radius.
- **Primary:** Control Blue background, Panel Surface text, 36px height.
- **Hover / Focus:** Color and border changes only. No scale, bounce, or width animation.
- **Secondary:** White-tinted panel surface with border and dark text.

### Chips
- **Style:** Small bordered metadata chips.
- **State:** Semantic color only when status requires it.
- **Metadata:** Use AntD `Tag` with default or blue emphasis.
- **Status:** Use AntD `Tag` with status color values from business mapping helpers such as `runStatusTagColor`, `taskStatusTagColor`, and `notificationStatusTagColor`.

### Cards / Containers
- **Corner Style:** 8px radius.
- **Background:** Panel Surface.
- **Shadow Strategy:** Flat by default.
- **Border:** Rule Border.
- **Internal Padding:** 12px to 16px depending on density.
- **Implementation:** Use AntD `Card` for product panels, detail shells, and tool containers.

### Metrics
- **Implementation:** Use AntD `Card` plus `Statistic` for counts, operational facts, status facts, and compact summary tiles.
- **Shape:** Flat bordered panel with optional 28px or 32px icon cell.
- **Tone:** Semantic icon/value emphasis only. The panel background remains calm.

### Inputs / Fields
- **Style:** Native Ant Design controls with 6px radius.
- **Focus:** Blue focus ring with visible outline.
- **Error / Disabled:** Use semantic status color and text, not color alone.

### Navigation
- **Style:** Left rail on desktop, compact five-item grid on mobile.
- **Active State:** Neutral filled row, 1px border, and restrained blue icon only. No blue pill block and no colored side stripe.

### Feedback Taxonomy
- **Status:** Use `Tag`, `Spin`, `Progress`, and component loading states for current state. Copy must be short nouns or adjectives, not instructional sentences.
- **Toast:** Use AntD `message` for transient action results: save, reset, draft run, scan failure, validation failure after a user action, and batch execution summaries. These must not be inserted into page flow.
- **Tips:** Use `Tooltip` for hover/focus affordances, disabled reasons, and terse control-level context.
- **Overlay:** Use `Popover`, `Drawer`, or `Modal` when the user asks for more detail or enters a focused workflow.
- **Blocking Alert:** Use `Alert` only for blocking page or section failures that prevent normal work from continuing.
- **Empty:** Use `Empty` only for true data absence. Avoid instructional descriptions unless the empty state replaces the whole workflow and includes one primary action.
- **Forbidden:** Do not add persistent informational callouts for routine work surfaces. Draft-run explanations, scan instructions, and “click here” guidance belong in toast, tooltip, or an explicit overlay.

## 6. Do's and Don'ts

### Do:
- **Do** use `frontend/src/designSystem.ts` and `frontend/src/styles.css` as token sources.
- **Do** use Ant Design components before inventing custom controls.
- **Do** use rem-based typography roles for visible text.
- **Do** use tabular numeric treatment for counts, dates, durations, and table data.
- **Do** keep motion to opacity, transform, and color.
- **Do** route feedback through the taxonomy before adding UI copy.

### Don't:
- **Don't** use Inter as the default or only UI font.
- **Don't** add decorative hero sections, eyebrow labels, glass effects, gradient panels, or filler badges.
- **Don't** animate width, height, left, right, or other layout properties unless a component cannot function without it.
- **Don't** use bounce or elastic easing, including `cubic-bezier(0.12, 0.4, 0.29, 1.46)`.
- **Don't** use pure black or pure white as base neutrals.
- **Don't** add page-level informational `Alert` blocks for non-blocking states.
