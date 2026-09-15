// @vitest-environment jsdom
/**
 * MetaView import wiring — selecting a search-results file must call
 * `api.metaImportHits` (the Excel import "does nothing" regression).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider, t as tr } from "@/lib/i18n";
import { ToastProvider } from "@/lib/toast";
import { useWorkspaceStore } from "@/stores/workspace";
import { MetaList } from "@/features/meta/MetaList";
import { MetaView } from "@/features/meta/MetaView";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom has no ResizeObserver; the left bar's BarHeader observes its width.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;

const apiMock = vi.hoisted(() => {
  const fns: Record<string, ReturnType<typeof vi.fn>> = {};
  const api = new Proxy({} as Record<string, (...args: unknown[]) => unknown>, {
    get: (_target, prop: string) => {
      fns[prop] ??= vi.fn(async () => []);
      return fns[prop];
    },
  });
  return { api, fns };
});

vi.mock("@/lib/api", () => ({
  api: apiMock.api,
  localRequestBlob: vi.fn(),
  fetchSourceFile: vi.fn(),
  sourceFileUrl: vi.fn(() => "about:blank"),
}));

let root: Root | null = null;
let el: HTMLDivElement | null = null;

async function render() {
  el = document.createElement("div");
  document.body.appendChild(el);
  await act(async () => {
    root = createRoot(el as HTMLDivElement);
    root.render(
      <I18nProvider>
        <ToastProvider>
          {/* The import action lives in the study left bar; MetaView owns the
              dialog it opens (wired through the shared workspace store). */}
          <MetaList />
          <MetaView />
        </ToastProvider>
      </I18nProvider>,
    );
  });
  // Let the initial load() settle.
  await act(async () => {
    await Promise.resolve();
  });
}

afterEach(() => {
  act(() => root?.unmount());
  el?.remove();
  root = null;
  el = null;
  vi.clearAllMocks();
});

beforeEach(() => {
  // The workspace store is module-level; reset the meta slice per test.
  useWorkspaceStore.setState({
    metaUi: {
      tab: "screen",
      selectedHit: null,
      selectedIds: [],
      scheme: "",
      email: "",
      importOpen: false,
      schemeOpen: false,
      tick: 0,
    },
  });
  apiMock.fns.metaHits = vi.fn(async () => ({ hits: [], total: 0, limit: 100, offset: 0 }));
  apiMock.fns.metaStatus = vi.fn(async () => ({
    hits: 0,
    criteria: 1,
    schemes: 1,
    eligible: 0,
    documents_done: 0,
    extracted: 0,
  }));
  apiMock.fns.metaCriteria = vi.fn(async () => [
    { id: 1, position: 0, key: "c1", label: "C1", prompt_text: "p", created: "" },
  ]);
  apiMock.fns.metaSchemes = vi.fn(async () => [
    { id: 1, name: "inoculation", label: "Inoculation", created: "", updated: "" },
  ]);
});

describe("MetaView search-results import", () => {
  it("opens the import dialog and previews a selected file", async () => {
    apiMock.fns.metaPreviewHits = vi.fn(async () => ({
      format: "xlsx",
      structured: false,
      sheets: ["Sheet1"],
      sheet: "Sheet1",
      header_row: 0,
      columns: ["Title", "Authors", "DOI"],
      head_rows: [["Title", "Authors", "DOI"]],
      rows_sample: [["Study A", "Doe, J", "10.1/x"]],
      mapping: { title: 0, authors: 1, doi: 2, abstract: null, year: null, source: null, language: null },
      fields: ["title", "abstract", "authors", "doi", "year", "source", "language"],
    }));
    await render();

    // The import button opens the dialog (which owns the file input).
    const importButton = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent === tr("meta.importSearch"),
    );
    expect(importButton).toBeTruthy();
    await act(async () => {
      importButton?.click();
    });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement | null;
    expect(input).not.toBeNull();
    const file = new File(["x"], "hits.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    await act(async () => {
      input?.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(apiMock.fns.metaPreviewHits).toHaveBeenCalledTimes(1);
  });

  it("batch-imports PDFs from the downloads left bar", async () => {
    apiMock.fns.metaAssignPdfs = vi.fn(async () => ({
      ok: true,
      assigned: [],
      unmatched: [],
      failed: [],
    }));
    await render();

    const downloadTab = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent === tr("meta.tabDownload"),
    );
    await act(async () => {
      downloadTab?.click();
    });

    const importButton = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent === tr("meta.importPdfs"),
    );
    expect(importButton).toBeTruthy();
    await act(async () => {
      importButton?.click();
    });

    const input = document.querySelector('input[multiple][type="file"]') as HTMLInputElement | null;
    expect(input).not.toBeNull();
    const file = new File(["%PDF-1.4"], "10.1000_aaaa.pdf", { type: "application/pdf" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    await act(async () => {
      input?.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(apiMock.fns.metaAssignPdfs).toHaveBeenCalledTimes(1);
    expect(apiMock.fns.metaAssignPdfs.mock.calls[0][0]).toHaveLength(1);
  });
});
