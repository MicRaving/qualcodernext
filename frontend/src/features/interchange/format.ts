import type { InterchangeResult } from "@/lib/api";

const IMPORT_LABELS: Record<string, string> = {
  refi: "REFI-QDA",
  rqda: "RQDA",
  taguette: "Taguette",
  transana: "Transana (.tprd)",
  ris: "RIS",
  survey: "Survey",
  xlsx: "Excel (.xlsx)",
  sav: "SPSS (.sav)",
  codebook: "Codebook",
  merge: "Merge project",
  zotero: "Zotero",
};

/** Human-readable label for an import format kind ("refi" → "REFI-QDA"). */
export function importLabel(kind: string): string {
  return IMPORT_LABELS[kind] ?? kind;
}

/** "Codes: 2 · Categories: 1 · Sources: 1" from the present positive counts. */
export function formatImportResult(result: InterchangeResult): string {
  const parts: string[] = [];
  const counts: [string, number | undefined][] = [
    ["Codes", result.codes],
    ["Categories", result.categories],
    ["Codings", result.codings],
    ["Sources", result.sources],
    ["Cases", result.cases],
    ["References", result.references],
    ["Attributes", result.attributes],
  ];
  for (const [label, value] of counts) {
    if (value !== undefined && value > 0) parts.push(`${label}: ${value}`);
  }
  return parts.length > 0 ? parts.join(" · ") : "Import complete";
}
