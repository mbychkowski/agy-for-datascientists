import { CircleCheck, Loader2, Lock, ShieldX, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { TileChart } from "../charts/TileChart";
import type { Activity, InProgressTile, LandedTile, Tile } from "../types";

/** A Tile that has not landed: names its step and the table it is waiting for. */
export function LockedTileCard({ tile }: { tile: Tile }) {
  const awaiting = ("awaiting" in tile && tile.awaiting?.length ? tile.awaiting : tile.tables) ?? [];
  return (
    <article
      data-tile={tile.id}
      data-state="locked"
      className="rounded-xl border border-dashed border-zinc-300 bg-zinc-50/60 p-5 transition-colors duration-300 hover:border-zinc-400 sm:p-6 dark:border-zinc-700 dark:bg-zinc-900/40 dark:hover:border-zinc-600"
    >
      <div className="flex items-start gap-4">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-zinc-200/70 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
          <Lock className="size-5" aria-hidden />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">{tile.step}</p>
          <h3 className="mt-0.5 text-2xl font-semibold text-zinc-500 dark:text-zinc-400">{tile.title}</h3>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-base text-zinc-500 dark:text-zinc-400">
            Awaiting
            {awaiting.map((table) => (
              <code
                key={table}
                className="break-all rounded bg-zinc-200/70 px-1.5 py-0.5 font-mono text-sm text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
              >
                {table}
              </code>
            ))}
          </p>
        </div>
      </div>
    </article>
  );
}

/**
 * A landed Tile: shows its chart and "what this proves". With `unlocking`, it
 * plays the unlock animation and badge on mount (a live lock-to-landed change).
 */
export function LandedTileCard({ tile, dark, unlocking }: { tile: LandedTile; dark: boolean; unlocking: boolean }) {
  return (
    <article
      data-tile={tile.id}
      data-state="landed"
      className={`${unlocking ? "tile-unlock " : ""}relative rounded-xl border border-zinc-200 bg-white p-5 shadow-sm transition-shadow duration-300 hover:shadow-md sm:p-6 dark:border-zinc-800 dark:bg-[#0c0c0f]`}
    >
      {unlocking ? (
        <span aria-hidden className="tile-unlock-badge absolute -top-3 right-5 inline-flex items-center gap-1 rounded-full bg-emerald-600 px-3 py-1 text-sm font-semibold text-white shadow">
          <Sparkles className="size-4" />
          Unlocked
        </span>
      ) : null}
      <div className="flex items-start gap-4">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
          <CircleCheck className="size-6" aria-hidden />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold uppercase tracking-wider text-blue-600 dark:text-blue-400">{tile.step}</p>
          <h3 className="mt-0.5 text-2xl font-semibold text-zinc-950 sm:text-3xl dark:text-zinc-50">{tile.title}</h3>
          <p className="mt-1 flex flex-wrap gap-2 text-sm text-zinc-500 dark:text-zinc-400">
            {tile.tables.map((table) => (
              <code key={table} className="break-all rounded bg-zinc-100 px-1.5 py-0.5 font-mono dark:bg-zinc-800">
                {table}
              </code>
            ))}
          </p>
        </div>
      </div>

      {tile.activity?.blocked?.length ? <BlockedList blocked={tile.activity.blocked} /> : null}

      <div className="mt-6">
        <TileChart type={tile.chart.type} rows={tile.chart.rows} dark={dark} />
      </div>

      <div className="mt-6 flex gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800/30 dark:bg-blue-900/20">
        <div className="min-w-0">
          <p className="text-sm font-semibold uppercase tracking-wider text-blue-700 dark:text-blue-300">What this proves</p>
          <p className="mt-1 text-lg leading-snug text-zinc-900 dark:text-zinc-100">{tile.proves}</p>
        </div>
      </div>
    </article>
  );
}

/**
 * A Tile the agent is working on: its tables have not all landed, but the hook
 * event log shows running lanes (e.g. the three triage subagents) or blocked calls.
 */
export function InProgressTileCard({ tile }: { tile: InProgressTile }) {
  const lanes = tile.activity.lanes ?? [];
  const blocked = tile.activity.blocked ?? [];
  return (
    <article
      data-tile={tile.id}
      data-state="in_progress"
      className="rounded-xl border border-amber-300 bg-amber-50/60 p-5 transition-colors duration-300 sm:p-6 dark:border-amber-700/50 dark:bg-amber-950/20"
    >
      <div className="flex items-start gap-4">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
          <Loader2 className="size-5 animate-spin motion-reduce:animate-none" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-300">{tile.step}</p>
          <h3 className="mt-0.5 text-2xl font-semibold text-zinc-900 dark:text-zinc-100">{tile.title}</h3>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-base text-zinc-500 dark:text-zinc-400">
            In progress, awaiting
            {(tile.awaiting.length ? tile.awaiting : tile.tables).map((table) => (
              <code
                key={table}
                className="break-all rounded bg-zinc-200/70 px-1.5 py-0.5 font-mono text-sm text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
              >
                {table}
              </code>
            ))}
          </p>
          {lanes.length ? <LaneList lanes={lanes} /> : null}
        </div>
      </div>
      {blocked.length ? <BlockedList blocked={blocked} /> : null}
    </article>
  );
}

/** One row per running lane, each with a timer ticking from when it started. */
function LaneList({ lanes }: { lanes: NonNullable<Activity["lanes"]> }) {
  const now = useNow(1000);
  return (
    <ul className="mt-4 grid gap-2 sm:grid-cols-3" aria-label="Running lanes">
      {lanes.map((lane) => (
        <li
          key={lane.label}
          className="flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-white px-3 py-2 dark:border-amber-800/40 dark:bg-zinc-900"
        >
          <span className="flex min-w-0 items-center gap-2 text-base font-medium">
            <span aria-hidden className="size-2 shrink-0 animate-pulse rounded-full bg-amber-500" />
            <span className="truncate">{lane.label}</span>
          </span>
          <span className="shrink-0 font-mono text-sm tabular-nums text-zinc-500 dark:text-zinc-400">
            {elapsed(lane.since, now)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The calls the guardrail denied: what was attempted and why it was refused. */
function BlockedList({ blocked }: { blocked: NonNullable<Activity["blocked"]> }) {
  return (
    <ul className="mt-5 space-y-2" aria-label="Blocked calls">
      {blocked.map((item) => (
        <li
          key={`${item.ts}:${item.summary}`}
          className="flex gap-3 rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-800/50 dark:bg-red-950/30"
        >
          <ShieldX className="mt-0.5 size-5 shrink-0 text-red-600 dark:text-red-400" aria-hidden />
          <div className="min-w-0">
            <p className="text-sm font-semibold uppercase tracking-wider text-red-700 dark:text-red-300">
              Blocked by guardrail
            </p>
            <code className="mt-1 block break-all font-mono text-sm text-zinc-800 dark:text-zinc-200">
              {item.summary || item.tool}
            </code>
            {item.reason ? <p className="mt-1 text-base text-zinc-700 dark:text-zinc-300">{item.reason}</p> : null}
          </div>
        </li>
      ))}
    </ul>
  );
}

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** "1:05" since an ISO timestamp; "" when it does not parse. */
function elapsed(since: string, now: number): string {
  const start = Date.parse(since);
  if (Number.isNaN(start)) return "";
  const seconds = Math.max(0, Math.floor((now - start) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
