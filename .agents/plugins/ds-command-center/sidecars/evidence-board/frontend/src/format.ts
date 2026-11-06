import type { Cell } from "./types";

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/** "2026-10-31" -> "Oct 31, 2026" (dates are calendar days, so format in UTC). */
export function formatDate(value: Cell | undefined): string {
  if (typeof value !== "string") return String(value ?? "");
  const date = new Date(DATE_ONLY.test(value) ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** "2026-10-31" -> "Oct 31" for compact chart axes. */
export function formatShortDate(value: Cell | undefined): string {
  const full = formatDate(value);
  return full.replace(/,\s*\d{4}$/, "");
}

/** A finite number cell, or null for anything else (null, text, NaN). */
export function num(value: Cell | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** 12.5 -> "12.5%"; "—" for anything but a finite number. */
export function percent(value: Cell | undefined): string {
  const n = num(value);
  return n === null ? "—" : `${n.toFixed(1)}%`;
}

export function formatNumber(value: Cell | undefined): string {
  return typeof value === "number" ? value.toLocaleString("en-US") : String(value ?? "—");
}

export function formatPercentChange(value: Cell | undefined): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const rounded = Math.round(value);
  return `${rounded > 0 ? "+" : ""}${rounded}%`;
}

export function formatCell(value: Cell | undefined): string {
  if (typeof value === "string" && DATE_ONLY.test(value)) return formatDate(value);
  return formatNumber(value);
}
