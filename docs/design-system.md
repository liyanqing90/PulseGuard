# PulseGuard 设计系统规范

## 按钮

所有前端按钮必须使用 `frontend/src/components/common/AppButton.tsx` 导出的 `AppButton`，在业务组件中统一以 `Button` 别名引入。

禁止事项：
- 不允许从 `antd` 直接引入 `Button`。
- 不允许写 AntD 裸属性 `type="primary"`、`type="default"`、`type="link"`。
- 不允许在业务组件里单独写按钮颜色、背景色或 hover 颜色。

`AppButton` 的 `intent` 语义：
- `default`：默认按钮。用于工具栏操作、扫描、调试、执行草稿、添加规则、候选元素保存、取消以外的普通动作。
- `primary`：强主操作。只用于最终提交并持久化当前页面主要表单的动作，例如任务抽屉底部“保存”。不得用于元素选择器弹框内的“保存选择”，因为它只把候选规则写入当前草稿。
- `link`：表格内查看、跳转、弱化操作。

危险操作：
- 删除、清空等破坏性操作必须使用公共 `AppButton` 的 `danger`，不得自定义红色样式。
- 危险按钮 hover 不得被公共绿色 hover 覆盖。

颜色规则：
- 默认按钮不填充色，文字使用 `var(--ink)`。
- 主按钮使用 `var(--accent)` 填充，仅在明确的最终提交场景出现。
- 同一视图内不得出现多个主按钮争夺视觉焦点。

检查清单：
- 搜索 `type="primary"` 应无结果。
- 搜索 `from "antd"` 的 `Button` 引入应无结果。
- 新增按钮前先确认是否能使用 `intent="default"`；只有最终提交才考虑 `intent="primary"`。
