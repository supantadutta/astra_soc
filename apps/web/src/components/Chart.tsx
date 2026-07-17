"use client";

import ReactECharts from "echarts-for-react";
import { useMemo } from "react";

const AXIS = "#4a5a78";
const GRID = "rgba(74,90,120,0.15)";
const PALETTE = ["#22d3ee", "#a78bfa", "#2dd4bf", "#f59e0b", "#f43f5e", "#60a5fa", "#34d399"];

const baseTheme = {
  color: PALETTE,
  textStyle: { color: "#9fb3d1", fontFamily: "ui-sans-serif, system-ui" },
  grid: { left: 40, right: 16, top: 24, bottom: 28, containLabel: true },
  tooltip: {
    backgroundColor: "rgba(10,15,28,0.95)",
    borderColor: "rgba(34,211,238,0.3)",
    textStyle: { color: "#e6f0ff" },
  },
};

export function Chart({
  option,
  height = 240,
  onEvents,
}: {
  option: Record<string, any>;
  height?: number;
  onEvents?: Record<string, (params: any) => void>;
}) {
  const merged = useMemo(() => {
    const axisDefaults = {
      axisLine: { lineStyle: { color: AXIS } },
      axisLabel: { color: "#6f83a6", fontSize: 10 },
      splitLine: { lineStyle: { color: GRID } },
    };
    return {
      ...baseTheme,
      ...option,
      xAxis: option.xAxis
        ? Array.isArray(option.xAxis)
          ? option.xAxis.map((x: any) => ({ ...axisDefaults, ...x }))
          : { ...axisDefaults, ...option.xAxis }
        : undefined,
      yAxis: option.yAxis
        ? Array.isArray(option.yAxis)
          ? option.yAxis.map((y: any) => ({ ...axisDefaults, ...y }))
          : { ...axisDefaults, ...option.yAxis }
        : undefined,
    };
  }, [option]);

  return (
    <ReactECharts
      option={merged}
      style={{ height, width: "100%" }}
      opts={{ renderer: "canvas" }}
      onEvents={onEvents}
      notMerge
    />
  );
}
