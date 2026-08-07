import { describe, expect, it } from "vitest";
import { formatImportResult, importLabel } from "@/features/interchange/format";
import type { InterchangeResult } from "@/lib/api";

describe("formatImportResult", () => {
  it("joins present positive counts with separators", () => {
    const result: InterchangeResult = { ok: true, codes: 2, categories: 1, codings: 3, sources: 1 };
    expect(formatImportResult(result)).toBe("Codes: 2 · Categories: 1 · Codings: 3 · Sources: 1");
  });

  it("omits undefined and zero-valued keys", () => {
    expect(formatImportResult({ ok: true, codes: 0, sources: 5 })).toBe("Sources: 5");
    expect(formatImportResult({ ok: true, cases: undefined, categories: 0, codings: 7 })).toBe(
      "Codings: 7",
    );
  });

  it("formats ris and survey style results", () => {
    expect(formatImportResult({ ok: true, references: 4, attributes: 2 })).toBe(
      "References: 4 · Attributes: 2",
    );
  });

  it("falls back to 'Import complete' when no positive counts are present", () => {
    expect(formatImportResult({ ok: true })).toBe("Import complete");
    expect(formatImportResult({ ok: true, codes: 0, sources: 0 })).toBe("Import complete");
  });
});

describe("importLabel", () => {
  it("maps known format kinds to display labels", () => {
    expect(importLabel("refi")).toBe("REFI-QDA");
    expect(importLabel("rqda")).toBe("RQDA");
    expect(importLabel("taguette")).toBe("Taguette");
    expect(importLabel("ris")).toBe("RIS");
    expect(importLabel("survey")).toBe("Survey");
  });

  it("returns the raw kind for unknown formats", () => {
    expect(importLabel("nvivo")).toBe("nvivo");
    expect(importLabel("")).toBe("");
  });
});
