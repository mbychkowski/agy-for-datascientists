// The ESM entry: Vite's CJS interop hands back `{ default }` for lib/core.
import ReactEChartsCore from "echarts-for-react/esm/core";
import { useMemo } from "react";
import { formatShortDate, num, percent } from "../format";
import type { Row } from "../types";
import { axisStyle, baseOption, echarts, legendStyle } from "./theme";

/** Reality in ink, the clean forecast green, the uncleaned forecast red. */
const SERIES = [
  { key: "reveal_observed_positives", name: "Reality (Reveal)", color: { light: "#18181b", dark: "#fafafa" }, dashed: false },
  { key: "clean_forecast_positives", name: "Clean forecast", color: { light: "#10b981", dark: "#34d399" }, dashed: false },
  { key: "uncleaned_forecast_positives", name: "Uncleaned forecast", color: { light: "#e11d48", dark: "#fb7185" }, dashed: true },
];

/**
 * Segment 2C, the Reveal: weekly Northeast positive flu tests over the six
 * weeks after the Cutoff, against the forecasts trained on clean and on
 * uncleaned Hospital Feeds.
 */
export function RevealChart({ rows, dark }: { rows: Row[]; dark: boolean }) {
  const first = rows[0];

  const option = useMemo(() => {
    const axis = axisStyle(dark);
    const base = baseOption(dark);
    return {
      ...base,
      grid: { ...base.grid, top: 48 },
      legend: legendStyle(dark),
      tooltip: { ...base.tooltip, trigger: "axis" },
      xAxis: {
        type: "category",
        data: rows.map((r) => formatShortDate(r.week_end ?? r.week_start)),
        boundaryGap: false,
        ...axis,
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        name: "Positive flu tests / week",
        scale: true,
        ...axis,
        nameTextStyle: { align: "left" },
      },
      series: SERIES.map((s) => {
        const color = dark ? s.color.dark : s.color.light;
        return {
          type: "line",
          name: s.name,
          symbolSize: 8,
          lineStyle: { width: 3, color, type: s.dashed ? "dashed" : "solid" },
          itemStyle: { color },
          data: rows.map((r) => num(r[s.key])),
        };
      }),
    };
  }, [rows, dark]);

  return (
    <div>
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="font-mono text-5xl font-bold tracking-tight text-emerald-600 sm:text-6xl dark:text-emerald-400">
          {percent(first?.clean_wape)}
          <span className="text-3xl text-rose-600 sm:text-4xl dark:text-rose-400"> vs {percent(first?.uncleaned_wape)}</span>
        </div>
        <div className="pb-1.5 text-lg text-zinc-600 dark:text-zinc-300">
          WAPE against reality, clean vs uncleaned forecast
          <span className="block text-base text-zinc-500 dark:text-zinc-400">
            {String(first?.reveal_weeks ?? rows.length)} Reveal weeks after the Cutoff
          </span>
        </div>
      </div>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        notMerge
        lazyUpdate
        style={{ height: 320, marginTop: 16 }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}
