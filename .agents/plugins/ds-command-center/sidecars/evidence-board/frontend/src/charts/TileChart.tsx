import type { Row } from "../types";
import { BeforeAfterChart } from "./BeforeAfterChart";
import { CohortsChart } from "./CohortsChart";
import { HeatmapChart } from "./HeatmapChart";
import { LeaderboardChart } from "./LeaderboardChart";
import { RowsTable } from "./RowsTable";
import { WaterfallChart } from "./WaterfallChart";
import { WeeklyBarChart } from "./WeeklyBarChart";

/** Chart per manifest `chart.type`; types without a drawing yet fall back to a table. */
export function TileChart({ type, rows, dark }: { type: string; rows: Row[]; dark: boolean }) {
  switch (type) {
    case "weekly_bar":
      return <WeeklyBarChart rows={rows} dark={dark} />;
    case "heatmap":
      return <HeatmapChart rows={rows} dark={dark} />;
    case "waterfall":
      return <WaterfallChart rows={rows} dark={dark} />;
    case "before_after":
      return <BeforeAfterChart rows={rows} />;
    case "cohorts":
      return <CohortsChart rows={rows} dark={dark} />;
    case "leaderboard":
      return <LeaderboardChart rows={rows} dark={dark} />;
    default:
      return <RowsTable rows={rows} />;
  }
}
