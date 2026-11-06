// The ESM entry: Vite's CJS interop hands back `{ default }` for lib/core.
import ReactEChartsCore from "echarts-for-react/esm/core";
import { useMemo } from "react";
import { num } from "../format";
import type { Row } from "../types";
import { axisStyle, baseOption, echarts } from "./theme";

/** One bar series per (model family, training data); clean is solid, uncleaned pale. */
const SERIES = [
  { family: "ARIMA_PLUS", version: "clean", color: "#3b82f6" },
  { family: "ARIMA_PLUS", version: "uncleaned", color: "#bfdbfe" },
  { family: "TimesFM", version: "clean", color: "#10b981" },
  { family: "TimesFM", version: "uncleaned", color: "#a7f3d0" },
];

/**
 * Segment 2B: backtest WAPE per Cohort for ARIMA_PLUS and TimesFM, each
 * trained on clean and on uncleaned Hospital Feeds. Lower is better.
 */
export function LeaderboardChart({ rows, dark }: { rows: Row[]; dark: boolean }) {
  const first = rows[0];
  const cohorts = useMemo(() => [...new Set(rows.map((r) => String(r.cohort_id ?? "")))].sort(), [rows]);

  const option = useMemo(() => {
    const axis = axisStyle(dark);
    const base = baseOption(dark);
    const wape = (cohort: string, family: string, version: string) =>
      num(
        rows.find(
          (r) => r.cohort_id === cohort && r.model_family === family && r.training_data_version === version,
        )?.backtest_wape,
      );
    return {
      ...base,
      grid: { ...base.grid, top: 48 },
      legend: { top: 0, left: 0, textStyle: { color: dark ? "#a1a1aa" : "#52525b", fontSize: 14 } },
      tooltip: {
        ...base.tooltip,
        trigger: "axis",
        axisPointer: { type: "shadow" },
        valueFormatter: (v: number | null) => (v === null ? "—" : `${v.toFixed(1)}%`),
      },
      xAxis: {
        type: "category",
        data: cohorts.map((c) => c.replace(/^COHORT_/, "Cohort ")),
        ...axis,
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        name: "WAPE (lower is better)",
        ...axis,
        nameTextStyle: { align: "left" },
        axisLabel: { ...axis.axisLabel, formatter: (v: number) => `${v}%` },
      },
      series: SERIES.map((s) => ({
        type: "bar",
        name: `${s.family} · ${s.version}`,
        barMaxWidth: 28,
        itemStyle: { color: s.color, borderRadius: [4, 4, 0, 0] },
        data: cohorts.map((c) => wape(c, s.family, s.version)),
      })),
    };
  }, [rows, cohorts, dark]);

  return (
    <div>
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="font-mono text-5xl font-bold tracking-tight text-emerald-600 sm:text-6xl dark:text-emerald-400">
          {percent(first?.clean_wape)}
          <span className="text-3xl text-zinc-400 sm:text-4xl dark:text-zinc-500"> vs {percent(first?.uncleaned_wape)}</span>
        </div>
        <div className="pb-1.5 text-lg text-zinc-600 dark:text-zinc-300">
          mean WAPE, clean vs uncleaned training data
          <span className="block text-base text-zinc-500 dark:text-zinc-400">
            Clean wins {String(first?.clean_wins ?? "—")} of {String(first?.comparisons ?? "—")} Cohort and model pairs
            {first?.best_family ? ` · ${String(first.best_family)} leads` : ""}
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

function percent(value: Row[string] | undefined): string {
  const n = num(value);
  return n === null ? "—" : `${n.toFixed(1)}%`;
}
