/**
 * CSV serialization (RFC-4180-ish) with an Excel-friendly BOM.
 */

const BOM = "\uFEFF";

function escapeCell(cell: unknown): string {
  if (cell === null || cell === undefined) return '""';
  return `"${String(cell).replace(/"/g, '""')}"`;
}

/** Serialize headers + rows: every cell quoted, embedded `"` escaped as `""`,
 * CRLF line endings, trailing CRLF, UTF-8 BOM prefix. */
export function toCsv(headers: string[], rows: unknown[][]): string {
  const lines = [headers.map(escapeCell).join(","), ...rows.map((r) => r.map(escapeCell).join(","))];
  return BOM + lines.join("\r\n") + "\r\n";
}

/** Trigger a browser download of the serialized CSV. */
export function downloadCsv(filename: string, headers: string[], rows: unknown[][]): void {
  const blob = new Blob([toCsv(headers, rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
