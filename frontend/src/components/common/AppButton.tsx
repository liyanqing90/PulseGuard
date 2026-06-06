import { Button as AntButton } from "antd";
import type { ButtonProps as AntButtonProps } from "antd";

export type AppButtonIntent = "default" | "primary" | "link";

export type AppButtonProps = Omit<AntButtonProps, "type"> & {
  intent?: AppButtonIntent;
};

const BUTTON_TYPE_BY_INTENT = {
  default: "default",
  primary: "primary",
  link: "link"
} satisfies Record<AppButtonIntent, AntButtonProps["type"]>;

export function AppButton({ className, intent = "default", ...props }: AppButtonProps) {
  const normalizedClassName = ["app-button", `app-button-${intent}`, className].filter(Boolean).join(" ");
  return <AntButton {...props} type={BUTTON_TYPE_BY_INTENT[intent]} className={normalizedClassName} />;
}
