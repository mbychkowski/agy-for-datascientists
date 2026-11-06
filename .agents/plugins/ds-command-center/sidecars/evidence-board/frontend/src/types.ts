/** Tile states as served by the board backend's `GET /api/tiles`. */

export type Cell = string | number | boolean | null;
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

export interface LandedTile extends TileBase {
  state: "landed";
  chart: { type: string; rows: Row[] };
  proves: string;
}

/** Any state this frontend does not know yet renders as locked. */
export interface OtherTile extends TileBase {
  state: Exclude<string, "locked" | "landed">;
  awaiting?: string[];
}

export type Tile = LockedTile | LandedTile | OtherTile;

export function isLanded(tile: Tile): tile is LandedTile {
  return tile.state === "landed" && "chart" in tile;
}
