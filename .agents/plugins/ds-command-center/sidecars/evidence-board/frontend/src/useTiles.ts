import { useEffect, useRef, useState } from "react";
import type { Tile } from "./types";

/** How often the page asks the backend; the backend itself re-checks tables every 5 s. */
export const POLL_MS = 2000;
const TIMEOUT_MS = 4000;

export interface TilesFeed {
  /** null until the first successful response. */
  tiles: Tile[] | null;
  /** false while the backend is unreachable; the last good Tiles stay on screen. */
  live: boolean;
}

/**
 * Poll `api/tiles` without flicker: state only changes when the response body
 * changes, so unchanged polls cause no re-render, and a failed poll keeps the
 * last good Tiles instead of showing an error.
 */
export function useTiles(): TilesFeed {
  const [tiles, setTiles] = useState<Tile[] | null>(null);
  const [live, setLive] = useState(true);
  const lastBody = useRef<string>("");

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;

    async function poll(): Promise<void> {
      try {
        const response = await fetch("api/tiles", {
          cache: "no-store",
          signal: AbortSignal.timeout(TIMEOUT_MS),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.text();
        if (!stopped && body !== lastBody.current) {
          const parsed = JSON.parse(body) as { tiles?: Tile[] };
          if (Array.isArray(parsed.tiles)) {
            lastBody.current = body;
            setTiles(parsed.tiles);
          }
        }
        if (!stopped) setLive(true);
      } catch {
        if (!stopped) setLive(false);
      } finally {
        if (!stopped) timer = window.setTimeout(poll, POLL_MS);
      }
    }

    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, []);

  return { tiles, live };
}
