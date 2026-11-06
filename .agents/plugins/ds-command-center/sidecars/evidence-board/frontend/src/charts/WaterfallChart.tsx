// The ESM entry: Vite's CJS interop hands back `{ default }` for lib/core.
import ReactEChartsCore from "echarts-for-react/esm/core";
import { useMemo } from "react";
import type { Cell, Row } from "../types";
import { axisStyle, baseOption, echarts, PALETTE } from "./theme";

/** Display names for the Attribution causes (GLOSSARY.md). */
const CAUSES: Record<string, { label: string; real: boolean }> = {
  pipeline_defect: { label: "Pipeline Defect", real: false },
  sampling_artifact: { label: "Sampling Artifact", real: false },
  outbreak: { label: "Outbreak", real: true },
  seasonal_ramp: { label: "Seasonal Ramp", real: true },
};
const ARTIFACT = "#a1a1aa";
const REAL = "#3b82f6";

/**
 * Segment 1B: the Attribution waterfall. Each cause floats on the running
 * total; the last bar is the Spike they sum to. Artifacts are grey, real
 * disease (Outbreak, Seasonal Ramp) blue.
 */
export function WaterfallChart({ rows, dark }: { rows: Row[]; dark: boolean }) {
  const steps = useMemo(() => {
    let total = 0;
    return rows.map((row) => {
      const points = num(row.contributed_points) ?? 0;
      const start = total;
      total += points;
      const cause = String(row.cause ?? "");
      return {
        row,
        label: CAUSES[cause]?.label ?? cause,
        real: CAUSES[cause]?.real ?? false,
        points,
        base: Math.min(start, total),
        end: total,
      };
    });
  }, [rows]);
  const spike = num(rows[0]?.spike_points) ?? steps.at(-1)?.end ?? 0;
  const real = num(rows[0]?.real_points) ?? steps.filter((s) => s.real).reduce((sum, s) => sum + s.points, 0);

  const option = useMemo(() => {
    const axis = axisStyle(dark);
    const base = baseOption(dark);
    const labels = [...steps.map((s) => s.label), "The Spike"];
    return {
      ...base,
      tooltip: {
        ...base.tooltip,
        trigger: "axis",
        axisPointer: { type: "shadow" },
        extraCssText: "max-width: 360px; white-space: normal;",
        formatter: (items: { dataIndex: number }[]) => {
          const index = items[0]?.dataIndex ?? 0;
          const step = steps[index];
          if (!step) return `<b>The Spike</b><br/>${points(spike)} in total`;
          const evidence = typeof step.row.evidence === "string" ? step.row.evidence : "";
          return [`<b>${step.label}</b>: ${points(step.points)}`, evidence].filter(Boolean).join("<br/>");
        },
      },
      xAxis: { type: "category", data: labels, ...axis, axisTick: { show: false } },
      yAxis: {
        type: "value",
        ...axis,
        axisLabel: { ...axis.axisLabel, formatter: (v: number) => `${v}` },
        name: "points",
        nameTextStyle: { color: dark ? "#a1a1aa" : "#52525b" },
      },
      series: [
        {
          type: "bar",
          stack: "waterfall",
          silent: true,
          itemStyle: { color: "transparent" },
          data: [...steps.map((s) => s.base), 0],
        },
        {
          type: "bar",
          stack: "waterfall",
          barMaxWidth: 72,
          data: [
            ...steps.map((s) => ({
              value: Math.abs(s.points),
              itemStyle: { color: s.real ? REAL : ARTIFACT, borderRadius: 4 },
            })),
            { value: spike, itemStyle: { color: PALETTE.spike, borderRadius: [6, 6, 0, 0] } },
          ],
          label: {
            show: true,
            position: "top",
            fontSize: 16,
            fontWeight: 700,
            color: dark ? "#fafafa" : "#18181b",
            formatter: (item: { dataIndex: number }) => {
              const step = steps[item.dataIndex];
              return step ? `${step.points > 0 ? "+" : ""}${round(step.points)}` : `${round(spike)}`;
            },
          },
        },
      ],
    };
  }, [steps, spike, dark]);

  return (
    <div>
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="font-mono text-5xl font-bold tracking-tight text-blue-600 sm:text-6xl dark:text-blue-400">
          {round(real)}
          <span className="text-3xl text-zinc-400 sm:text-4xl dark:text-zinc-500"> / {round(spike)}</span>
        </div>
        <div className="pb-1.5 text-lg text-zinc-600 dark:text-zinc-300">
          points of the Spike are real disease
          <span className="block text-base text-zinc-500 dark:text-zinc-400">
            <Swatch color={REAL} /> Outbreak and Seasonal Ramp · <Swatch color={ARTIFACT} /> Pipeline Defect and Sampling Artifact
          </span>
        </div>
      </div>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        notMerge={false}
        lazyUpdate
        style={{ height: 320, marginTop: 16 }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}

function Swatch({ color }: { color: string }) {
  return <span aria-hidden className="inline-block size-3 rounded-sm align-middle" style={{ backgroundColor: color }} />;
}

function num(value: Cell | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function round(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function points(value: number): string {
  return `${round(value)} point${Math.abs(value) === 1 ? "" : "s"}`;
}
