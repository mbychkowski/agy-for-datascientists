// The ESM entry: Vite's CJS interop hands back `{ default }` for lib/core.
import ReactEChartsCore from "echarts-for-react/esm/core";
import { useMemo } from "react";
import { formatDate, formatNumber, formatPercentChange, formatShortDate } from "../format";
import type { Cell, Row } from "../types";
import { axisStyle, baseOption, echarts, PALETTE } from "./theme";

const ROW_HEIGHT = 24;

/**
 * Segment 1A: Northeast hospital-by-week flu-positive counts through the
 * Cutoff, coloured by week-over-week change. Hospitals are listed in the
 * order of the chart rows (largest share of the Spike first).
 */
export function HeatmapChart({ rows, dark }: { rows: Row[]; dark: boolean }) {
  const first = rows[0];
  const weeks = useMemo(() => unique(rows.map((r) => String(r.week_end ?? ""))).sort(), [rows]);
  const hospitals = useMemo(() => unique(rows.map((r) => String(r.hospital_id ?? ""))), [rows]);
  const shares = useMemo(
    () => new Map(rows.map((r) => [String(r.hospital_id ?? ""), num(r.share_of_ne_spike_pct)])),
    [rows],
  );

  const option = useMemo(() => {
    const axis = axisStyle(dark);
    const base = baseOption(dark);
    const changes = rows.map((r) => num(r.wow_pct)).filter((v): v is number => v !== null);
    const reach = Math.max(25, ...changes.map((v) => Math.abs(v)));
    return {
      ...base,
      grid: { ...base.grid, top: 8, right: 96 },
      tooltip: {
        ...base.tooltip,
        formatter: (item: { data: { row: Row } }) => {
          const row = item.data?.row;
          if (!row) return "";
          const change = formatPercentChange(row.wow_pct);
          const positivity = num(row.positivity);
          const share = num(row.share_of_ne_spike_pct);
          return [
            `<b>${row.hospital_id}</b> · week ending ${formatDate(row.week_end)}`,
            `${formatNumber(row.positive_flu_tests)} flu-positive tests`,
            change ? `${change} week over week` : "",
            positivity !== null ? `Positivity ${(positivity * 100).toFixed(1)}%` : "",
            share !== null ? `${share.toFixed(1)}% of the Northeast Spike` : "",
          ]
            .filter(Boolean)
            .join("<br/>");
        },
      },
      xAxis: {
        type: "category",
        data: weeks.map((w) => formatShortDate(w)),
        position: "top",
        ...axis,
        axisTick: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: hospitals,
        ...axis,
        axisTick: { show: false },
        axisLabel: { ...axis.axisLabel, fontSize: 12, formatter: (id: string) => id.replace(/^HOSP_/, "") },
        splitLine: { show: false },
      },
      visualMap: {
        type: "continuous",
        dimension: 3,
        min: -reach,
        max: reach,
        calculable: false,
        orient: "vertical",
        right: 0,
        top: "middle",
        itemHeight: 160,
        text: ["Rising", "Falling"],
        textStyle: { color: dark ? "#a1a1aa" : "#52525b", fontSize: 12 },
        inRange: { color: ["#3b82f6", dark ? "#27272a" : "#f4f4f5", PALETTE.spike] },
        outOfRange: { color: dark ? "#3f3f46" : "#e4e4e7" },
      },
      series: [
        {
          type: "heatmap",
          data: rows.map((r) => {
            const change = num(r.wow_pct);
            return {
              // [week, hospital, positives, change]; a null change (first week) sits out of range.
              value: [
                weeks.indexOf(String(r.week_end ?? "")),
                hospitals.indexOf(String(r.hospital_id ?? "")),
                num(r.positive_flu_tests) ?? 0,
                change ?? reach * 10,
              ],
              row: r,
            };
          }),
          label: {
            show: true,
            fontSize: 11,
            color: dark ? "#fafafa" : "#18181b",
            formatter: (item: { value: number[] }) => item.value[2].toLocaleString("en-US"),
          },
          itemStyle: { borderColor: dark ? "#0c0c0f" : "#ffffff", borderWidth: 2, borderRadius: 3 },
        },
      ],
    };
  }, [rows, dark, weeks, hospitals]);

  const spikeHospitals = num(first?.spike_hospitals);
  const neHospitals = num(first?.ne_hospitals);
  const spikeShare = num(first?.spike_share_pct);
  const topShare = shares.get(hospitals[0] ?? "");

  return (
    <div>
      {spikeHospitals !== null && neHospitals !== null ? (
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
          <div className="font-mono text-5xl font-bold tracking-tight text-rose-600 sm:text-6xl dark:text-rose-400">
            {spikeHospitals}
            <span className="text-3xl text-zinc-400 sm:text-4xl dark:text-zinc-500"> / {neHospitals}</span>
          </div>
          <div className="pb-1.5 text-lg text-zinc-600 dark:text-zinc-300">
            Northeast hospitals carry {spikeShare !== null ? `${Math.round(spikeShare)}%` : "most"} of the Spike
            {topShare != null ? (
              <span className="block text-base text-zinc-500 dark:text-zinc-400">
                Largest single share: {hospitals[0]} at {topShare.toFixed(1)}%
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        notMerge={false}
        lazyUpdate
        style={{ height: Math.max(240, hospitals.length * ROW_HEIGHT + 48), marginTop: 16 }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}

function num(value: Cell | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}
