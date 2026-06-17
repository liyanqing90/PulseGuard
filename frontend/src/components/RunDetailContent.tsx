import type { Run } from "../types";
import { RunResultPanel } from "./RunResultPanel";

interface Props {
  run: Run | null;
}

export function RunDetailContent({ run }: Props) {
  return <RunResultPanel run={run} mode="detail" />;
}
