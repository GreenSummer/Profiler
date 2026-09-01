import ReactECharts from "echarts-for-react";

export function EChart({ option, height = 320, onEvent }: {
  option: Record<string, unknown>;
  height?: number | string;
  onEvent?: { type: string; handler: (params: unknown) => void };
}) {
  return (
    <ReactECharts
      option={option}
      style={{ height, width: "100%" }}
      notMerge
      lazyUpdate
      opts={{ renderer: "canvas" }}
      onEvents={onEvent ? { [onEvent.type]: onEvent.handler } : undefined}
    />
  );
}

export const PALETTE = {
  good: "#34d399",
  bad: "#f87171",
  neutral: "#60a5fa",
  accent: "#a78bfa",
  muted: "#94a3b8",
};
