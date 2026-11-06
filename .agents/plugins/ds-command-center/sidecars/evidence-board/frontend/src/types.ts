/** Tile states as served by the board backend's `GET /api/tiles`. */

export type Cell = string | number | boolean | null | string[];
export type Row = Record<string, Cell>;

interface TileBase {
  id: string;
  step: string;
  title: string;
  tables: string[];
}

export interface LockedTile extends TileBase {
  state: "locked";
  awaiting: string[];
}

/** What the agent is doing for a Tile, from the hook event log. */
export interface Activity {
  /** Running lanes (e.g. one per triage subagent), with the ISO time each started. */
  lanes?: { label: string; since: string }[];
  /** The latest calls the guardrail denied for this Tile. */
  blocked?: { ts: string; tool: string; summary: string; reason: string }[];
  /** A file the agent wrote that awaits the presenter's approval (e.g. a diff). */
  approval?: { label: string; since: string };
  /** A long-running job: ticks from `since`; `until` and `ok: false` once it failed. */
  timer?: { label: string; since: string; until?: string; ok?: boolean };
  /** A reviewer subagent was dispatched (its verdict is in the agent's chat). */
  review?: { label: string; since: string };
  /** The latest matching calls (e.g. forecasting trials started), oldest first. */
  ticker?: { label: string; ts: string; summary: string }[];
}

export interface InProgressTile extends TileBase {
  state: "in_progress";
  awaiting: string[];
  activity: Activity;
}

export interface LandedTile extends TileBase {
  state: "landed";
  chart: { type: string; rows: Row[] };
  proves: string;
  /** The "Ask the Command Center about this Tile" prompt: names the Tile, its tables and numbers. */
  ask?: { prompt: string };
  activity?: Activity;
}

/** Any state this frontend does not know yet renders as locked. */
export interface OtherTile extends TileBase {
  state: Exclude<string, "locked" | "landed" | "in_progress">;
  awaiting?: string[];
}

export type Tile = LockedTile | InProgressTile | LandedTile | OtherTile;

export function isLanded(tile: Tile): tile is LandedTile {
  return tile.state === "landed" && "chart" in tile;
}

export function isInProgress(tile: Tile): tile is InProgressTile {
  return tile.state === "in_progress" && "activity" in tile;
}
