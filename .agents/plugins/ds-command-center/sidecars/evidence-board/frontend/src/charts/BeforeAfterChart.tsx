import { ArrowRight } from "lucide-react";
import { formatNumber, num } from "../format";
import type { Row } from "../types";

/**
 * Segment 1C: Hospital Feed rows and duplicate (hospital, feed date) keys,
 * before (`staging.hospital_flu`) vs after (`staging.hospital_flu_clean`).
 */
export function BeforeAfterChart({ rows }: { rows: Row[] }) {
  const row = rows[0] ?? {};
  const panels = [
    { title: "Hospital Feed rows", before: num(row.before_rows), after: num(row.after_rows) },
    { title: "Duplicate keys", before: num(row.before_duplicate_keys), after: num(row.after_duplicate_keys) },
  ];
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {panels.map((panel) => (
        <Panel key={panel.title} {...panel} />
      ))}
    </div>
  );
}

function Panel({ title, before, after }: { title: string; before: number | null; after: number | null }) {
  const change = before !== null && after !== null ? after - before : null;
  const scale = Math.max(before ?? 0, after ?? 0, 1);
  return (
    <section
      aria-label={title}
      className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
    >
      <p className="text-sm font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">{title}</p>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-3 font-mono text-3xl font-bold tabular-nums sm:text-4xl">
        <span className="text-rose-600 dark:text-rose-400">{formatNumber(before)}</span>
        <ArrowRight className="size-6 self-center text-zinc-400" aria-hidden />
        <span className="text-emerald-600 dark:text-emerald-400">{formatNumber(after)}</span>
      </div>
      {change !== null ? (
        <p className="mt-1 text-base text-zinc-600 dark:text-zinc-300">
          {change === 0 ? "No change" : `${change > 0 ? "+" : "−"}${Math.abs(change).toLocaleString("en-US")}`}
        </p>
      ) : null}
      <div className="mt-4 space-y-2">
        <Bar label="Before" value={before} scale={scale} className="bg-rose-500/80" />
        <Bar label="After" value={after} scale={scale} className="bg-emerald-500/80" />
      </div>
    </section>
  );
}

function Bar({ label, value, scale, className }: { label: string; value: number | null; scale: number; className: string }) {
  const width = value === null ? 0 : Math.max(value > 0 ? 1 : 0, (value / scale) * 100);
  return (
    <div className="flex items-center gap-3 text-sm text-zinc-500 dark:text-zinc-400">
      <span className="w-12 shrink-0">{label}</span>
      <div className="h-3 flex-1 rounded-full bg-zinc-100 dark:bg-zinc-800">
        <div className={`h-3 rounded-full ${className}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}
