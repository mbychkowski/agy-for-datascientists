// The ESM entry: Vite's CJS interop hands back `{ default }` for lib/core.
import ReactEChartsCore from "echarts-for-react/esm/core";
import { TrendingUp } from "lucide-react";
import { useMemo } from "react";
import { formatDate, formatNumber, formatPercentChange, formatShortDate } from "../format";
import type { Row } from "../types";
import { axisStyle, baseOption, echarts, PALETTE } from "./theme";

/**
 * Opening Tile: weekly Northeast flu-positive counts up to the Cutoff, with the
 * last week (the Spike) in red and its week-over-week jump as the headline.
 */
export function WeeklyBarChart({ rows, dark }: { rows: Row[]; dark: boolean }) {
  const last = rows.at(-1);
  const jump = formatPercentChange(last?.wow_pct ?? null);

  const option = useMemo(() => {
    const axis = axisStyle(dark);
    const base = baseOption(dark);
    return {
      ...base,
      tooltip: {
        ...base.tooltip,
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (items: { dataIndex: number }[]) => {
          const row = rows[items[0]?.dataIndex ?? 0];
          if (!row) return "";
          const change = formatPercentChange(row.wow_pct);
          return [
            `<b>Week ending ${formatDate(row.week_end)}</b>`,
            `${formatNumber(row.positive_flu_tests)} flu-positive tests`,
            change ? `${change} week over week` : "",
          ]
            .filter(Boolean)
            .join("<br/>");
        },
      },
      xAxis: {
        type: "category",
        data: rows.map((r) => formatShortDate(r.week_end)),
        ...axis,
        axisTick: { show: false },
      },
      yAxis: { type: "value", ...axis, axisLabel: { ...axis.axisLabel, formatter: (v: number) => v.toLocaleString("en-US") } },
      series: [
        {
          type: "bar",
          barMaxWidth: 56,
          data: rows.map((r, i) => {
            const isSpikeWeek = i === rows.length - 1;
            return {
              value: typeof r.positive_flu_tests === "number" ? r.positive_flu_tests : 0,
              itemStyle: {
                color: isSpikeWeek ? PALETTE.spike : dark ? "#52525b" : "#d4d4d8",
                borderRadius: [6, 6, 0, 0],
              },
              label:
                isSpikeWeek && jump
                  ? { show: true, position: "top", formatter: jump, color: PALETTE.spike, fontSize: 18, fontWeight: 700 }
                  : undefined,
            };
          }),
        },
      ],
    };
  }, [rows, dark, jump]);

  return (
    <div>
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="font-mono text-5xl font-bold tracking-tight text-rose-600 sm:text-6xl dark:text-rose-400">
          {jump ?? formatNumber(last?.positive_flu_tests ?? null)}
        </div>
        <div className="pb-1.5 text-lg text-zinc-600 dark:text-zinc-300">
          {jump ? "Northeast flu-positive tests, week over week" : "Northeast flu-positive tests"}
          {last ? (
            <span className="block text-base text-zinc-500 dark:text-zinc-400">
              Week ending {formatDate(last.week_end)} · {formatNumber(last.positive_flu_tests)} positives
            </span>
          ) : null}
        </div>
        {jump ? (
          <span className="mb-2 inline-flex items-center gap-1 rounded-full bg-rose-100 px-3 py-1 text-sm font-semibold text-rose-700 dark:bg-rose-900/30 dark:text-rose-400">
            <TrendingUp className="size-4" aria-hidden />
            The Spike
          </span>
        ) : null}
      </div>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        notMerge={false}
        lazyUpdate
        style={{ height: 300, marginTop: 16 }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}
