import type { Row } from "../types";
import { RowsTable } from "./RowsTable";
import { WeeklyBarChart } from "./WeeklyBarChart";

/** Chart per manifest `chart.type`; types without a drawing yet fall back to a table. */
export function TileChart({ type, rows, dark }: { type: string; rows: Row[]; dark: boolean }) {
  switch (type) {
    case "weekly_bar":
      return <WeeklyBarChart rows={rows} dark={dark} />;
    default:
      return <RowsTable rows={rows} />;
  }
}
