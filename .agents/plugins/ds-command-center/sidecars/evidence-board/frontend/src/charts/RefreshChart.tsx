// The ESM entry: Vite's CJS interop hands back `{ default }` for lib/core.
import ReactEChartsCore from "echarts-for-react/esm/core";
import { useMemo } from "react";
import { num } from "../format";
import type { Row } from "../types";
import { axisStyle, baseOption, cohortName, echarts, legendStyle } from "./theme";

const FAMILY_COLORS: Record<string, string> = { ARIMA_PLUS: "#3b82f6", TimesFM: "#10b981" };

/**
 * Segment 2D: the refresh period's backtest WAPE per Cohort and model family,
 * as logged by the cohort-forecast-refresh skill. WAPE is shown as stored
 * (the skill logs a fraction); lower is better.
 */
export function RefreshChart({ rows, dark }: { rows: Row[]; dark: boolean }) {
  const first = rows[0];
  const cohorts = useMemo(() => [...new Set(rows.map((r) => String(r.cohort_id ?? "")))].sort(), [rows]);
  const families = useMemo(() => [...new Set(rows.map((r) => String(r.model_family ?? "")))].sort(), [rows]);

  const option = useMemo(() => {
    const axis = axisStyle(dark);
    const base = baseOption(dark);
    const wape = (cohort: string, family: string) =>
      num(rows.find((r) => r.cohort_id === cohort && r.model_family === family)?.backtest_wape);
    return {
      ...base,
      grid: { ...base.grid, top: 48 },
      legend: legendStyle(dark),
      tooltip: { ...base.tooltip, trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: {
        type: "category",
        data: cohorts.map(cohortName),
        ...axis,
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        name: "Backtest WAPE (lower is better)",
        ...axis,
        nameTextStyle: { align: "left" },
      },
      series: families.map((family) => ({
        type: "bar",
        name: family,
        barMaxWidth: 28,
        itemStyle: { color: FAMILY_COLORS[family], borderRadius: [4, 4, 0, 0] },
        data: cohorts.map((c) => wape(c, family)),
      })),
    };
  }, [rows, cohorts, families, dark]);

  return (
    <div>
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="font-mono text-5xl font-bold tracking-tight text-blue-600 sm:text-6xl dark:text-blue-400">
          {String(first?.period ?? "—")}
        </div>
        <div className="pb-1.5 text-lg text-zinc-600 dark:text-zinc-300">
          {String(first?.new_trials ?? "—")} new trials across {String(first?.cohorts ?? "—")} Cohorts
          <span className="block text-base text-zinc-500 dark:text-zinc-400">
            refreshed by the cohort-forecast-refresh skill
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
