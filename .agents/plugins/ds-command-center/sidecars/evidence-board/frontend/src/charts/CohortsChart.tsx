// The ESM entry: Vite's CJS interop hands back `{ default }` for lib/core.
import ReactEChartsCore from "echarts-for-react/esm/core";
import { useMemo } from "react";
import { num } from "../format";
import type { Row } from "../types";
import { axisStyle, baseOption, echarts, PALETTE } from "./theme";

const MUTED = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#06b6d4", "#84cc16"];

/**
 * Segment 2A: one dot per hospital at its seasonal peak week and trend,
 * coloured by K-means Cohort. The breakout Cohort (steepest seasonal rise,
 * chosen by the chart query from the data) is drawn large and red: the
 * Outbreak hospitals in a Cohort of their own.
 */
export function CohortsChart({ rows, dark }: { rows: Row[]; dark: boolean }) {
  const first = rows[0];
  const breakout = String(first?.breakout_cohort ?? "");
  const cohorts = useMemo(() => unique(rows.map((r) => String(r.cohort_id ?? ""))).sort(), [rows]);

  const option = useMemo(() => {
    const axis = axisStyle(dark);
    const base = baseOption(dark);
    let muted = 0;
    const series = cohorts.map((cohort) => {
      const isBreakout = cohort === breakout;
      const color = isBreakout ? PALETTE.spike : MUTED[muted++ % MUTED.length];
      return {
        type: "scatter",
        name: cohortLabel(cohort, isBreakout),
        symbolSize: isBreakout ? 22 : 13,
        z: isBreakout ? 3 : 2,
        itemStyle: { color, opacity: isBreakout ? 1 : 0.75, borderColor: dark ? "#0c0c0f" : "#fff", borderWidth: 1 },
        data: rows
          .filter((r) => String(r.cohort_id ?? "") === cohort)
          .map((r) => ({ value: [num(r.peak_arrival_week), num(r.seasonal_trend)], hospital: String(r.hospital_id ?? "") })),
      };
    });
    return {
      ...base,
      // containLabel ignores axis names, so reserve room for the x-axis name.
      grid: { ...base.grid, top: 48, bottom: 32 },
      legend: { top: 0, left: 0, textStyle: { color: dark ? "#a1a1aa" : "#52525b", fontSize: 14 } },
      tooltip: {
        ...base.tooltip,
        trigger: "item",
        formatter: (item: { seriesName: string; data: { value: (number | null)[]; hospital: string } }) =>
          `<b>${item.data.hospital}</b><br/>${item.seriesName}<br/>Peak week ${item.data.value[0] ?? "—"} · trend ${item.data.value[1] ?? "—"}`,
      },
      xAxis: {
        type: "value",
        scale: true,
        name: "peak arrival week",
        nameLocation: "middle",
        nameGap: 32,
        ...axis,
      },
      yAxis: {
        type: "value",
        scale: true,
        name: "seasonal trend",
        ...axis,
        nameTextStyle: { align: "left" },
      },
      series,
    };
  }, [rows, cohorts, breakout, dark]);

  return (
    <div>
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="font-mono text-5xl font-bold tracking-tight text-rose-600 sm:text-6xl dark:text-rose-400">
          {formatCount(first?.breakout_size)}
          <span className="text-3xl text-zinc-400 sm:text-4xl dark:text-zinc-500"> / {formatCount(first?.hospitals)}</span>
        </div>
        <div className="pb-1.5 text-lg text-zinc-600 dark:text-zinc-300">
          hospitals in the breakout Cohort, {breakout || "—"}
          <span className="block font-mono text-base text-zinc-500 dark:text-zinc-400">
            {String(first?.breakout_hospitals ?? "")}
          </span>
        </div>
      </div>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        notMerge
        lazyUpdate
        style={{ height: 340, marginTop: 16 }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}

function cohortLabel(cohort: string, breakout: boolean): string {
  const name = cohort.replace(/^COHORT_/, "Cohort ");
  return breakout ? `${name} (breakout)` : name;
}

function formatCount(value: Row[string] | undefined): string {
  const n = num(value);
  return n === null ? "—" : String(n);
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}
