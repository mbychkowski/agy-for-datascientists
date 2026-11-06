import { formatCell } from "../format";
import type { Row } from "../types";

const MAX_ROWS = 12;

/** Fallback for chart types this frontend does not draw yet: the first rows as a table. */
export function RowsTable({ rows }: { rows: Row[] }) {
  const columns = Object.keys(rows[0] ?? {});
  if (columns.length === 0) {
    return <p className="text-zinc-500 dark:text-zinc-400">No rows yet.</p>;
  }
  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-left text-base">
        <thead className="sticky top-0 z-10 bg-zinc-100 text-sm text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            {columns.map((c) => (
              <th key={c} className="px-4 py-2 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, MAX_ROWS).map((row, i) => (
            <tr
              key={i}
              className="border-b border-zinc-100 text-zinc-900 transition-colors last:border-0 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-800/50"
            >
              {columns.map((c) => (
                <td key={c} className="px-4 py-2 font-mono text-sm">
                  {formatCell(row[c] ?? null)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
