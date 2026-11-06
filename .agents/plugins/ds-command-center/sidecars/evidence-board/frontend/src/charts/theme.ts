import { BarChart, HeatmapChart, ScatterChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

// Tree-shaken ECharts: register only what the Tiles use.
echarts.use([
  BarChart,
  HeatmapChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

export { echarts };

/** DAK shared design system: zinc neutrals, a red Spike, Tailwind 500-level series colours. */
export const PALETTE = {
  spike: "#e11d48",
  series: ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1"],
};

export function baseOption(dark: boolean) {
  const text = dark ? "#a1a1aa" : "#52525b";
  return {
    color: PALETTE.series,
    textStyle: { fontFamily: "'DM Sans', sans-serif", fontSize: 14, color: text },
    animationDurationUpdate: 0,
    tooltip: {
      backgroundColor: dark ? "rgba(12, 12, 15, 0.95)" : "rgba(255, 255, 255, 0.95)",
      borderColor: dark ? "#27272a" : "#e4e4e7",
      textStyle: { color: dark ? "#fafafa" : "#09090b", fontSize: 14 },
    },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
  };
}

export function axisStyle(dark: boolean) {
  return {
    axisLine: { lineStyle: { color: dark ? "#3f3f46" : "#d4d4d8" } },
    axisLabel: { color: dark ? "#a1a1aa" : "#52525b", fontSize: 14 },
    splitLine: { lineStyle: { color: dark ? "#27272a" : "#f4f4f5" } },
  };
}
