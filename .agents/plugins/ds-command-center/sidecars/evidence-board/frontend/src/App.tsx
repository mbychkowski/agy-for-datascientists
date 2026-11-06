import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { LandedTileCard, LockedTileCard } from "./components/TileCard";
import { isLanded, type Tile } from "./types";
import { useTiles } from "./useTiles";

interface Section {
  key: string;
  title: string;
  subtitle: string;
  tiles: Tile[];
}

const SECTIONS: Record<string, { title: string; subtitle: string }> = {
  opening: { title: "Opening", subtitle: "The question on the table" },
  "1": { title: "Workstream 1", subtitle: "Is the data good to use?" },
  "2": { title: "Workstream 2", subtitle: "Forecast at scale" },
};

/** Group Tiles, in manifest order, under Opening / Workstream 1 / Workstream 2 by their step label. */
function sections(tiles: Tile[]): Section[] {
  const out: Section[] = [];
  for (const tile of tiles) {
    const key = /Segment\s+(\d)/.exec(tile.step)?.[1] ?? "opening";
    const meta = SECTIONS[key] ?? { title: tile.step, subtitle: "" };
    let section = out.at(-1);
    if (!section || section.key !== key) {
      section = { key, ...meta, tiles: [] };
      out.push(section);
    }
    section.tiles.push(tile);
  }
  return out;
}

function useDarkMode(): [boolean, () => void] {
  const [dark, setDark] = useState(() => localStorage.getItem("evidence-board-theme") === "dark");
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("evidence-board-theme", dark ? "dark" : "light");
  }, [dark]);
  return [dark, () => setDark((d) => !d)];
}

export function App() {
  const { tiles, live } = useTiles();
  const [dark, toggleDark] = useDarkMode();
  const landed = tiles?.filter(isLanded).length ?? 0;

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-950 transition-colors dark:bg-[#09090b] dark:text-zinc-50">
      <header className="sticky top-0 z-30 border-b border-zinc-200 bg-zinc-50/90 backdrop-blur dark:border-zinc-800 dark:bg-[#09090b]/90">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Evidence Board</h1>
            <p className="truncate text-base text-zinc-500 dark:text-zinc-400">
              Each Tile lands when the Command Center produces its evidence
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <div
              className="flex items-center gap-2 rounded-full border border-zinc-200 bg-white px-3 py-1.5 font-mono text-base dark:border-zinc-800 dark:bg-[#0c0c0f]"
              title={live ? "Live" : "Reconnecting"}
            >
              <span
                aria-hidden
                className={`size-2.5 rounded-full transition-colors duration-500 ${live ? "bg-emerald-500" : "bg-amber-500"}`}
              />
              <span aria-label="Tiles landed">
                {landed}/{tiles?.length ?? 8}
              </span>
            </div>
            <button
              type="button"
              onClick={toggleDark}
              aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
              className="rounded-lg border border-zinc-200 bg-white p-2 text-zinc-600 shadow-sm transition-colors hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              {dark ? <Sun className="size-5" /> : <Moon className="size-5" />}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
        {tiles === null ? (
          <Skeleton />
        ) : (
          sections(tiles).map((section) => (
            <section key={section.key} className="mt-6 first:mt-0">
              <h2 className="mb-4 flex items-baseline gap-3 border-b border-zinc-200 pb-2 dark:border-zinc-800">
                <span className="text-lg font-bold">{section.title}</span>
                <span className="text-base text-zinc-500 dark:text-zinc-400">{section.subtitle}</span>
              </h2>
              <ol className="relative space-y-5 border-l-2 border-zinc-200 pl-5 sm:pl-8 dark:border-zinc-800">
                {section.tiles.map((tile) => (
                  // Keyed by id + state: a state change remounts the card, which plays the unlock animation;
                  // unchanged polls keep the same element, so nothing flickers.
                  <li key={`${tile.id}:${tile.state}`} className="relative">
                    <span
                      aria-hidden
                      className={`absolute -left-[1.85rem] top-7 size-3.5 rounded-full border-2 border-zinc-50 sm:-left-[2.6rem] dark:border-[#09090b] ${
                        isLanded(tile) ? "bg-emerald-500" : "bg-zinc-300 dark:bg-zinc-700"
                      }`}
                    />
                    {isLanded(tile) ? <LandedTileCard tile={tile} dark={dark} /> : <LockedTileCard tile={tile} />}
                  </li>
                ))}
              </ol>
            </section>
          ))
        )}
      </main>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-5" aria-label="Loading Tiles">
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="h-28 animate-pulse rounded-xl bg-zinc-200 dark:bg-zinc-800" />
      ))}
    </div>
  );
}
