/**
 * CSV serialization (RFC-4180-ish) with an Excel-friendly BOM, plus a
 * lenient RFC-4180 parser (quoted fields, escaped quotes, embedded
 * newlines, CRLF/LF, TSV auto-detection).
 */

const BOM = "\uFEFF";

/**
 * Pick the field delimiter from the header line: count unquoted tabs vs
 * commas, prefer tabs only when they outnumber commas (TSV). Falls back
 * to the RFC-4180 default comma.
 */
function detectDelimiter(text: string): string {
  const start = text.charCodeAt(0) === 0xfeff ? 1 : 0;
  const firstLine = text.slice(start).split(/\r?\n/, 1)[0] ?? "";
  let commas = 0;
  let tabs = 0;
  let inQuotes = false;
  for (let i = 0; i < firstLine.length; i++) {
    const c = firstLine[i];
    if (c === '"') {
      inQuotes = !inQuotes;
    } else if (!inQuotes) {
      if (c === ",") commas++;
      else if (c === "\t") tabs++;
    }
  }
  return tabs > commas ? "\t" : ",";
}

/**
 * Parse CSV/TSV text into a header row and data rows. RFC-4180 state
 * machine: fields may be quoted, `""` inside a quoted field is an escaped
 * quote, quoted fields may span newlines, records are separated by CRLF
 * (LF tolerated). The delimiter is auto-detected (tabs win only when the
 * header line carries more unquoted tabs than commas), so the same
 * function serves .csv and .tsv sources. A UTF-8 BOM is stripped.
 */
export function parseCsv(text: string): { headers: string[]; rows: string[][] } {
  const delimiter = detectDelimiter(text);
  const records: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  /** True while the current field was opened with a quote — an empty quoted
   *  field (`""`) at EOF must still flush, but a bare empty input must not
   *  produce a phantom record. */
  let fieldOpenedQuoted = false;
  let i = text.charCodeAt(0) === 0xfeff ? 1 : 0;
  const n = text.length;
  while (i < n) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i++;
        continue;
      }
      field += c;
      i++;
      continue;
    }
    if (c === '"' && field.length === 0) {
      inQuotes = true;
      fieldOpenedQuoted = true;
      i++;
      continue;
    }
    if (c === delimiter) {
      row.push(field);
      field = "";
      fieldOpenedQuoted = false;
      i++;
      continue;
    }
    if (c === "\r" || c === "\n") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      fieldOpenedQuoted = false;
      records.push(row);
      row = [];
      i++;
      continue;
    }
    field += c;
    i++;
  }
  // Flush a pending record: a final line without a trailing newline, a lone
  // quoted empty field (`""`), or a quoted field still open at EOF. An
  // empty input produces no records.
  if (inQuotes || fieldOpenedQuoted || field.length > 0 || row.length > 0) {
    row.push(field);
    records.push(row);
  }
  return { headers: records[0] ?? [], rows: records.slice(1) };
}

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
