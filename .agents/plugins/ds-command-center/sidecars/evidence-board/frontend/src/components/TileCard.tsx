import { CircleCheck, Lock, Sparkles } from "lucide-react";
import { TileChart } from "../charts/TileChart";
import type { LandedTile, Tile } from "../types";

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
