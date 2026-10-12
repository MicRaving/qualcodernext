// @vitest-environment jsdom
/**
 * MetaView import wiring — selecting a search-results file must call
 * `api.metaImportHits` (the Excel import "does nothing" regression).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider, t as tr } from "@/lib/i18n";
import { localRequestBlob } from "@/lib/api";
import { ToastProvider } from "@/lib/toast";
import { useWorkspaceStore } from "@/stores/workspace";
import { useCoderStore } from "@/stores/coder";
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
      hits: [],
      selectedIds: [],
      scheme: "",
      email: "",
      importOpen: false,
      schemeOpen: false,
      codingStudioOpen: false,
      selectedDocument: null,
      agreementScope: "screening",
      agreementStudy: "",
      coderScope: "default",
      coderScopeCustom: false,
      screeningFilter: "all",
      screeningStage: "abstract",
      blind: false,
      analysisSection: "pooled",
      analysisModel: "frequentist",
      poolModel: "dl",
      subgroupBy: "",
      moderatorTerms: [],
      moderatorInteractions: [],
      bayesMuSd: 1,
      bayesTauKey: "half-normal:0.5",
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
  // The coder store is module-level too; the scope sync follows `coderName`.
  useCoderStore.setState({ coderName: "default", coders: [] });
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

  it("offers existing search runs as datalist suggestions in the import dialog", async () => {
    apiMock.fns.metaSearchRuns = vi.fn(async () => ["run-a", "run-b"]);
    await render();
    await click(buttonByText(tr("meta.importSearch")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaSearchRuns).toHaveBeenCalledTimes(1);
    const options = document.querySelectorAll("#meta-search-runs option");
    expect(Array.from(options).map((o) => (o as HTMLOptionElement).value)).toEqual([
      "run-a",
      "run-b",
    ]);
  });

  it("offers no CSV export in the extract menubar (Excel only)", async () => {
    apiMock.fns.metaSchemes = vi.fn(async () => [
      { id: 1, name: "s", label: "Scheme S", created: "", updated: "" },
    ]);
    const localBlob = vi.mocked(localRequestBlob);
    localBlob.mockResolvedValue(new Blob(["a,b"], { type: "text/csv" }));
    const createObjectURL = vi.fn(() => "blob:xlsx");
    URL.createObjectURL = createObjectURL as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as typeof URL.revokeObjectURL;

    await render();
    await click(buttonByText(tr("meta.tabExtract")));

    expect(buttonByText(tr("meta.exportCsvShort"))).toBeNull();
    const xlsx = buttonByText(tr("meta.exportXlsxShort"));
    expect(xlsx).not.toBeNull();
    await click(xlsx);

    expect(localBlob).toHaveBeenCalledWith("/meta/extract/export?fmt=xlsx");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("sends max_input_chars and fulltext_only with an autocode run", async () => {
    apiMock.fns.metaSchemes = vi.fn(async () => [
      { id: 1, name: "s", label: "Scheme S", created: "", updated: "" },
    ]);
    apiMock.fns.metaDocuments = vi.fn(async () => [
      { id: 1, hit_id: 7, source_id: 3, status: "done", created: "", updated: "" },
    ]);
    apiMock.fns.metaExtractions = vi.fn(async () => [
      {
        id: 1,
        hit_id: 7,
        owner: "alice",
        scheme: "s",
        study_vars: { records: [] },
        dv_metrics: [],
        status: "extracted",
        title: "Paper 7",
        created: "",
        updated: "",
      },
    ]);
    apiMock.fns.metaExtractRun = vi.fn(async () => ({ ok: true, job_id: "j1" }));

    await render();
    await click(buttonByText(tr("meta.tabExtract")));
    await act(async () => {
      useWorkspaceStore.getState().setMetaUi({ scheme: "s", selectedIds: [7] });
    });

    const maxInput = document.querySelector(
      `input[aria-label="${tr("meta.maxInput")}"]`,
    ) as HTMLInputElement | null;
    expect(maxInput).not.toBeNull();
    await act(async () => {
      setInput(maxInput, "50000");
    });
    await act(async () => {
      (buttonByText(tr("meta.autocodeSelected")) as HTMLButtonElement)?.click();
    });

    expect(apiMock.fns.metaExtractRun).toHaveBeenCalledTimes(1);
    expect(apiMock.fns.metaExtractRun.mock.calls[0][0]).toMatchObject({
      scheme: "s",
      hit_ids: [7],
      max_input_chars: 50000,
      fulltext_only: true,
    });
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

function buttonByText(text: string): HTMLElement | null {
  const els = Array.from(document.querySelectorAll('button, [role="button"]'));
  return (
    ((els.find((b) => b.textContent === text) as HTMLElement | undefined) ??
      (els.find((b) => b.getAttribute("aria-label") === text) as HTMLElement | undefined) ??
      null)
  );
}

async function click(el: Element | null) {
  await act(async () => {
    (el as HTMLElement | null)?.click();
    await Promise.resolve();
  });
}

function setInput(node: HTMLInputElement | null, value: string) {
  if (!node) return;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(node, value);
  node.dispatchEvent(new Event("input", { bubbles: true }));
}

function setSelect(node: HTMLSelectElement | null, value: string) {
  if (!node) return;
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
  setter?.call(node, value);
  node.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("MetaView analyze tab", () => {
  it("renders the pooled KPIs and forest table from the analysis endpoints", async () => {
    apiMock.fns.metaAnalysisPooled = vi.fn(async () => ({
      k: 3,
      estimate: 0.4,
      se: 0.1,
      ci_low: 0.2,
      ci_high: 0.6,
      tau2: 0.05,
      q: 4.2,
      q_df: 2,
      q_p: 0.12,
      i2: 52.4,
      p: 0.001,
      n_studies: 3,
    }));
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({
      rows: [{ study_id: "Study 1", effect: 0.5, ci_low: 0.1, ci_high: 0.9, weight: 33 }],
      pooled: { k: 1, estimate: 0.4, se: 0.1, ci_low: 0.2, ci_high: 0.6, tau2: 0, q: 0, q_df: 0, q_p: 1, i2: 0, p: 1 },
    }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({
      rows: [{ study_id: "Study 1", estimate: 0.3, ci_low: 0.1, ci_high: 0.5 }],
    }));
    apiMock.fns.metaAnalysisEgger = vi.fn(async () => ({ intercept: 0.1, se: 0.2, t: 0.5, p: 0.6 }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));

    expect(apiMock.fns.metaAnalysisPooled).toHaveBeenCalled();
    expect(document.body.textContent).toContain(tr("meta.kpiPooled"));
    expect(document.body.textContent).toContain("0.400");
    expect(document.body.textContent).toContain(tr("meta.forestTitle"));
    expect(document.body.textContent).toContain("Study 1");
    expect(document.body.textContent).toContain(tr("meta.kpiI2"));
  });

  it("renders the publication-bias suite and the Bayesian posterior block", async () => {
    apiMock.fns.metaAnalysisPooled = vi.fn(async () => ({
      k: 3,
      estimate: 0.4,
      se: 0.1,
      ci_low: 0.2,
      ci_high: 0.6,
      tau2: 0.05,
      q: 4.2,
      q_df: 2,
      q_p: 0.12,
      i2: 52.4,
      p: 0.001,
      n_studies: 3,
    }));
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisPublicationBias = vi.fn(async () => ({
      k: 3,
      k_total: 3,
      egger: { intercept: 0.11, se: 0.2, t: 0.55, p: 0.6, slope: 0.42, slope_se: 0.1, slope_p: 0.01 },
      pet_peese: {
        pet: { intercept: 0.2, se: 0.05, t: 4, p: 0.01 },
        peese: { intercept: 0.18, se: 0.06, t: 3, p: 0.02 },
        recommended: "peese",
      },
      trim_and_fill: { k0: 2, side: "left", estimate: 0.3, se: 0.1, ci_low: 0.1, ci_high: 0.5 },
      p_curve: { n_significant: 4, n_p_lt_025: 3, p_half: 0.02, evidential: true, note: "evidential value" },
    }));
    apiMock.fns.metaAnalysisBayes = vi.fn(async () => ({
      k: 3,
      k_total: 3,
      mu: { mean: 0.35, median: 0.34, ci_low: 0.1, ci_high: 0.6, p_gt0: 0.98, p_two_sided: 0.01 },
      tau: { mean: 0.2, median: 0.19, ci_low: 0.05, ci_high: 0.4 },
      bf10: 12.3,
      bf01_tau0: 0.08,
      prior: { mu_sd: 1, tau_prior: "half-normal", tau_scale: 0.5 },
      sensitivity: [
        { mu_sd: 1, tau_prior: "half-normal", tau_scale: 0.5, mean: 0.35, ci_low: 0.1, ci_high: 0.6, bf10: 12.3 },
      ],
    }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));

    expect(apiMock.fns.metaAnalysisPublicationBias).toHaveBeenCalled();
    expect(document.body.textContent).toContain(tr("meta.publicationBiasTitle"));
    expect(document.body.textContent).toContain(tr("meta.petPeeseTitle"));
    expect(document.body.textContent).toContain(tr("meta.trimFillTitle"));
    expect(document.body.textContent).toContain(tr("meta.pcurveTitle"));
    expect(document.body.textContent).toContain("0.110");

    // Switch the pooled block to the Bayesian model.
    await click(buttonByText(tr("meta.modelBayes")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaAnalysisBayes).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain(tr("meta.bayesPosterior"));
    expect(document.body.textContent).toContain(tr("meta.bayesBF10"));
    expect(document.body.textContent).toContain(tr("meta.bayesSensitivity"));
    expect(document.body.textContent).toContain("0.350");
  });

  it("renders the multiverse spec table and summary", async () => {
    apiMock.fns.metaAnalysisPooled = vi.fn(async () => ({
      k: 3,
      estimate: 0.4,
      se: 0.1,
      ci_low: 0.2,
      ci_high: 0.6,
      tau2: 0.05,
      q: 4.2,
      q_df: 2,
      q_p: 0.12,
      i2: 52.4,
      p: 0.001,
      n_studies: 3,
    }));
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisMultiverse = vi.fn(async () => ({
      k_total: 3,
      n_specs: 2,
      dimensions: [{ name: "model", levels: ["FE", "RE"] }],
      specs: [
        {
          id: "s1",
          choices: { model: "FE" },
          k: 3,
          estimate: 0.35,
          se: 0.1,
          ci_low: 0.15,
          ci_high: 0.55,
          tau2: 0,
          i2: 0,
        },
        {
          id: "s2",
          choices: { model: "RE" },
          k: 3,
          estimate: 0.42,
          se: 0.12,
          ci_low: 0.18,
          ci_high: 0.66,
          tau2: 0.05,
          i2: 40,
        },
      ],
      summary: {
        n_specs: 2,
        n_ok: 2,
        median: 0.385,
        min: 0.35,
        max: 0.42,
        pct_positive: 100,
        ci_low: 0.3,
        ci_high: 0.5,
      },
    }));
    apiMock.fns.metaAnalysisSpecCurvePng = vi.fn(
      async () => new Blob(["png"], { type: "image/png" }),
    );
    URL.createObjectURL = vi.fn(() => "blob:mock-spec") as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as typeof URL.revokeObjectURL;

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await click(buttonByText(tr("meta.section_multiverse")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaAnalysisMultiverse).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain(tr("meta.multiverseSpecs"));
    expect(document.body.textContent).toContain(tr("meta.multiverseMedian"));
    expect(document.body.textContent).toContain("0.385");
    expect(document.body.textContent).toContain("model=FE");
    expect(document.body.textContent).toContain("0.350");
    expect(document.body.textContent).toContain("100.0%");
  });

  it("shows a computing state while a figure is still rendering", async () => {
    apiMock.fns.metaAnalysisPooled = vi.fn(async () => ({
      k: 1,
      estimate: 0.4,
      se: 0.1,
      ci_low: 0.2,
      ci_high: 0.6,
      tau2: 0,
      q: 0,
      q_df: 0,
      q_p: 1,
      i2: 0,
      p: 1,
      n_studies: 1,
    }));
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));
    // A long-running figure stays pending: the view must read as "computing"
    // rather than a frozen/empty state.
    apiMock.fns.metaAnalysisFunnelPng = vi.fn(() => new Promise<Blob>(() => {}));
    apiMock.fns.metaAnalysisBayesPng = vi.fn(() => new Promise<Blob>(() => {}));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(document.body.textContent).toContain(tr("meta.computing"));
  });

  it("renders the variable audit coverage table and an issue", async () => {
    apiMock.fns.metaAudit = vi.fn(async () => ({
      n_extractions: 2,
      n_records: 3,
      n_metrics: 5,
      fields: [
        {
          name: "sample_n",
          label: "Sample size",
          group: "Study",
          kind: "integer",
          role: "sample_n",
          editor: "number",
          set: 2,
          total: 3,
          coverage: 0.667,
          issues: ["Missing in one record"],
        },
      ],
      issues: [
        { severity: "warn", field: "sample_n", message: "Missing in one record", count: 1 },
      ],
    }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await click(buttonByText(tr("meta.section_audit")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaAudit).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain("Sample size");
    expect(document.body.textContent).toContain(tr("meta.auditCoverage"));
    expect(document.body.textContent).toContain(tr("meta.severity_warning"));
    expect(document.body.textContent).toContain("Missing in one record");
  });

  it("exports a PowerPoint report from the report section", async () => {
    apiMock.fns.metaAnalysisPooled = vi.fn(async () => ({
      k: 1,
      estimate: 0.4,
      se: 0.1,
      ci_low: 0.2,
      ci_high: 0.6,
      tau2: 0,
      q: 0,
      q_df: 0,
      q_p: 1,
      i2: 0,
      p: 1,
    }));
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaReport = vi.fn(
      async () =>
        new Blob(["pptx"], {
          type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }),
    );
    const createObjectURL = vi.fn(() => "blob:mock-pptx");
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as typeof URL.revokeObjectURL;

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await click(buttonByText(tr("meta.section_report")));

    const pptx = buttonByText(tr("meta.exportPptx"));
    expect(pptx).not.toBeNull();
    await click(pptx);

    expect(apiMock.fns.metaReport).toHaveBeenCalledTimes(1);
    expect(apiMock.fns.metaReport.mock.calls[0][0]).toMatchObject({ format: "pptx" });
    expect(createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("renders the nested PRISMA flow and exclusion reasons", async () => {
    apiMock.fns.metaPrisma = vi.fn(async () => ({
      identification: { total: 120, database: 118, other: 2 },
      screening: { screened: 100, excluded: 60, included: 40, reasons: [{ reason: "Wrong pop", n: 60 }] },
      fulltext: {
        sought: 40,
        retrieved: 35,
        not_retrieved: 5,
        assessed: 35,
        excluded: 15,
        included: 20,
        reasons: [{ reason: "No full text", n: 5 }],
      },
      inclusion: { included: 20, studies: 18, reports: 20 },
      exclusion_reasons: [
        { reason: "Wrong pop", n: 60 },
        { reason: "No full text", n: 5 },
      ],
    }));
    apiMock.fns.metaPrismaPng = vi.fn(async () => new Blob(["png"], { type: "image/png" }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await click(buttonByText(tr("meta.section_prisma")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaPrisma).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain(tr("meta.prismaDatabase"));
    expect(document.body.textContent).toContain(tr("meta.prismaNotRetrieved"));
    expect(document.body.textContent).toContain(tr("meta.prismaStudies"));
    expect(document.body.textContent).toContain("Wrong pop");
    expect(document.body.textContent).toContain("118");
  });

  it("renders the categorical summary with n / n_studies", async () => {
    apiMock.fns.metaSummary = vi.fn(async () => ({
      n_extractions: 3,
      n_records: 5,
      n_studies: 4,
      fields: [
        {
          name: "domain",
          label: "Domain",
          group: "Metrics",
          kind: "metric",
          role: "dv_domain",
          levels: [
            { value: "belief", n: 3, n_studies: 2 },
            { value: "attitude", n: 2, n_studies: 2 },
          ],
        },
      ],
    }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await click(buttonByText(tr("meta.section_summary")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaSummary).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain(tr("meta.summaryStudies"));
    expect(document.body.textContent).toContain("Domain");
    expect(document.body.textContent).toContain("belief");
    expect(document.body.textContent).toContain("3");
  });

  it("shows a moderator fit from the coefficients contract", async () => {
    apiMock.fns.metaAnalysisPooled = vi.fn(async () => ({
      k: 4,
      estimate: 0.3,
      se: 0.1,
      ci_low: 0.1,
      ci_high: 0.5,
      tau2: 0.02,
      q: 3,
      q_df: 3,
      q_p: 0.4,
      i2: 30,
      p: 0.01,
    }));
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisSubgroup = vi.fn(async () => ({
      key: "dv_domain",
      groups: [{ key: "belief", value: "belief", label: "belief", k: 2, estimate: 0.4, ci_low: 0.2, ci_high: 0.6, tau2: 0 }],
      qm: 4.2,
      qm_df: 1,
      qm_p: 0.04,
    }));
    apiMock.fns.metaAnalysisModerator = vi.fn(async () => ({
      role: "dv_domain",
      terms: ["dv_domain"],
      k: 4,
      coefficients: [
        { term: "Intercept", estimate: 0.3, se: 0.1, z: 3, p: 0.003, ci_low: 0.1, ci_high: 0.5 },
        { term: "dv_domain:belief", estimate: 0.2, se: 0.08, z: 2.5, p: 0.01, ci_low: 0.04, ci_high: 0.36 },
      ],
      qm: 4.2,
      qm_df: 1,
      qm_p: 0.04,
      r2: 0.35,
      tau2: 0.02,
    }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await click(buttonByText(tr("meta.section_subgroup")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaAnalysisModerator).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain(tr("meta.moderatorFit"));
    expect(document.body.textContent).toContain("dv_domain:belief");
    expect(document.body.textContent).toContain("Intercept");
    expect(document.body.textContent).toContain("35.0%");
    expect(document.body.textContent).toContain("belief");
  });

  it("drives pooling with model=two_level and renders the variance decomposition", async () => {
    const pooled = vi.fn(async (body: { model?: string }) => ({
      k: 4,
      estimate: 0.3,
      se: 0.1,
      ci_low: 0.1,
      ci_high: 0.5,
      tau2: 0.02,
      q: 3,
      q_df: 3,
      q_p: 0.4,
      i2: 30,
      p: 0.01,
      model: body.model,
      tau2_within: 0.01,
      tau2_between: 0.02,
      var_within_share: 0.3,
      var_between_share: 0.5,
      var_sampling_share: 0.2,
    }));
    apiMock.fns.metaAnalysisPooled = pooled;
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(pooled).toHaveBeenCalled();
    const modelSelect = document.querySelector(
      `select[aria-label="${tr("meta.poolModelLabel")}"]`,
    ) as HTMLSelectElement | null;
    expect(modelSelect).not.toBeNull();
    await act(async () => {
      setSelect(modelSelect, "two_level");
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(pooled.mock.calls.at(-1)?.[0]).toMatchObject({ model: "two_level" });
    expect(document.body.textContent).toContain(tr("meta.varianceDecomposition"));
    expect(document.body.textContent).toContain(tr("meta.varianceSampling"));
  });

  it("drives the pooled request from the Analyze menubar without a scheme", async () => {
    const pooled = vi.fn(async (body: { model?: string }) => ({
      k: 2,
      estimate: 0.2,
      se: 0.1,
      ci_low: 0.0,
      ci_high: 0.4,
      tau2: 0,
      q: 1,
      q_df: 1,
      q_p: 0.3,
      i2: 0,
      p: 0.05,
      model: body.model,
    }));
    apiMock.fns.metaAnalysisPooled = pooled;
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));

    await render();
    await act(async () => {
      useWorkspaceStore.getState().setMetaUi({ scheme: "s" });
    });
    await click(buttonByText(tr("meta.tabAnalyze")));
    await act(async () => {
      await Promise.resolve();
    });

    // The scheme selector only lives in the Extract tab now…
    expect(document.querySelector(`select[aria-label="${tr("meta.scheme")}"]`)).toBeNull();
    // …and the request must not carry a scheme (pool every scheme).
    expect(pooled).toHaveBeenCalled();
    expect(pooled.mock.calls.at(-1)?.[0]).not.toHaveProperty("scheme");

    // The estimator select sits in the Analyze menubar and drives pooling.
    const modelSelect = document.querySelector(
      `select[aria-label="${tr("meta.poolModelLabel")}"]`,
    ) as HTMLSelectElement | null;
    expect(modelSelect).not.toBeNull();
    await act(async () => {
      setSelect(modelSelect, "fixed");
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(pooled.mock.calls.at(-1)?.[0]).toMatchObject({ model: "fixed" });
    expect(useWorkspaceStore.getState().metaUi.poolModel).toBe("fixed");
  });

  it("populates the moderator picker from metaModerators and sends the field name", async () => {
    apiMock.fns.metaModerators = vi.fn(async () => [
      {
        name: "sample_n",
        label: "Sample size",
        group: "Study",
        kind: "study",
        role: "sample_n",
        type: "integer",
        editor: "number",
        schemes: ["s"],
      },
      {
        name: "dv_domain",
        label: "Domain",
        group: "Metrics",
        kind: "metric",
        role: "dv_domain",
        type: "string",
        editor: "select",
        schemes: ["s"],
      },
    ]);
    const subgroup = vi.fn(async (body: { field?: string; key?: string }) => ({
      key: body.field ?? body.key ?? "",
      groups: [],
    }));
    const moderator = vi.fn(async (body: { field?: string; role?: string }) => ({
      role: body.field ?? body.role ?? "",
    }));
    apiMock.fns.metaAnalysisSubgroup = subgroup;
    apiMock.fns.metaAnalysisModerator = moderator;

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await click(buttonByText(tr("meta.section_subgroup")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaModerators).toHaveBeenCalled();
    const select = document.querySelector(
      `select[aria-label="${tr("meta.subgroupBy")}"]`,
    ) as HTMLSelectElement | null;
    expect(select).not.toBeNull();
    const labels = Array.from(select?.querySelectorAll("option") ?? []).map((o) => o.textContent);
    expect(labels).toContain("Sample size");
    expect(labels).toContain("Domain");
    expect(Array.from(select?.querySelectorAll("optgroup") ?? []).map((g) => g.label)).toEqual([
      "Study",
      "Metrics",
    ]);

    await act(async () => {
      setSelect(select, "dv_domain");
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(moderator.mock.calls.at(-1)?.[0]).toMatchObject({ field: "dv_domain" });
    expect(subgroup.mock.calls.at(-1)?.[0]).toMatchObject({ field: "dv_domain" });
  });

  it("renders an analyze error banner and drops the old domain/family filters", async () => {
    const pooled = vi.fn<(...args: unknown[]) => Promise<unknown>>(async () => {
      throw new Error("boom");
    });
    apiMock.fns.metaAnalysisPooled = pooled;
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(document.body.textContent).toContain("boom");
    expect(pooled).toHaveBeenCalled();
    // The Analyze toolbar is gone: the request carries no domain/families/primary…
    const body = pooled.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    expect(body).not.toHaveProperty("domain");
    expect(body).not.toHaveProperty("families");
    expect(body).not.toHaveProperty("primary");
    // …and its domain input no longer exists anywhere in the view.
    expect(document.querySelector(`input[aria-label="${tr("meta.colDomain")}"]`)).toBeNull();
  });

  it("adds moderator terms and interactions to the moderator request", async () => {
    apiMock.fns.metaModerators = vi.fn(async () => [
      { name: "sample_n", label: "Sample size", group: "Study", kind: "study" },
      { name: "dv_domain", label: "Domain", group: "Metrics", kind: "metric" },
    ]);
    const moderator = vi.fn(async (body: { terms?: string[]; interactions?: [string, string][] }) => ({
      role: body.terms?.[0] ?? "",
      terms: body.terms,
      interactions: body.interactions,
      coefficients: [{ term: "Intercept", estimate: 0.3, se: 0.1, z: 3, p: 0.003 }],
    }));
    const subgroup = vi.fn(async (body: { field?: string }) => ({
      key: body.field ?? "",
      groups: [],
    }));
    apiMock.fns.metaAnalysisModerator = moderator;
    apiMock.fns.metaAnalysisSubgroup = subgroup;
    apiMock.fns.metaAnalysisPooled = vi.fn(async () => ({
      k: 0,
      estimate: 0,
      se: 0,
      ci_low: 0,
      ci_high: 0,
      tau2: 0,
      q: 0,
      q_df: 0,
      q_p: 1,
      i2: 0,
      p: 1,
    }));
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await act(async () => {
      await Promise.resolve();
    });
    await click(buttonByText(tr("meta.section_subgroup")));
    await act(async () => {
      await Promise.resolve();
    });

    // The menubar default promotes the first moderator to the primary term.
    expect(useWorkspaceStore.getState().metaUi.moderatorTerms).toEqual(["sample_n"]);

    // Add a second term via the collapsible moderator group checkboxes.
    const domainBox = document.querySelector(
      'input[type="checkbox"][aria-label="Domain"]',
    ) as HTMLInputElement | null;
    expect(domainBox).not.toBeNull();
    await act(async () => {
      domainBox?.click();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(useWorkspaceStore.getState().metaUi.moderatorTerms).toEqual(["sample_n", "dv_domain"]);

    // Build the interaction sample_n * dv_domain.
    const aSelect = document.querySelector(
      `select[aria-label="${tr("meta.moderatorInteraction")} 1"]`,
    ) as HTMLSelectElement | null;
    const bSelect = document.querySelector(
      `select[aria-label="${tr("meta.moderatorInteraction")} 2"]`,
    ) as HTMLSelectElement | null;
    await act(async () => {
      setSelect(aSelect, "sample_n");
    });
    await act(async () => {
      setSelect(bSelect, "dv_domain");
    });
    await act(async () => {
      buttonByText(tr("meta.moderatorAddInteraction"))?.click();
    });
    await act(async () => {
      await Promise.resolve();
    });

    const last = moderator.mock.calls.at(-1)?.[0] as {
      field?: string;
      role?: string;
      terms?: string[];
      interactions?: [string, string][];
    };
    expect(last.field).toBe("sample_n");
    expect(last.role).toBe("sample_n");
    expect(last.terms).toEqual(["sample_n", "dv_domain"]);
    expect(last.interactions).toEqual([["sample_n", "dv_domain"]]);
    expect(document.body.textContent).toContain("sample_n * dv_domain");
    expect(subgroup).toHaveBeenCalled();
  });
});

describe("MetaView screening keyboard + job controls", () => {
  it("applies Y/N verdicts and navigates with the arrow keys", async () => {
    const hits = [
      { hit_id: 1, title: "One", status: "imported", created: "", updated: "" },
      { hit_id: 2, title: "Two", status: "imported", created: "", updated: "" },
    ];
    apiMock.fns.metaHits = vi.fn(async () => ({ hits, total: 2, limit: 100, offset: 0 }));
    apiMock.fns.metaScreening = vi.fn(async () => []);
    apiMock.fns.metaCriteria = vi.fn(async () => [
      { id: 1, position: 0, key: "c1", label: "C1", prompt_text: "p", created: "" },
      { id: 2, position: 1, key: "c2", label: "C2", prompt_text: "p", created: "" },
    ]);

    await render();
    await act(async () => {
      await Promise.resolve();
    });
    // Focus the first hit and open a verdict row.
    await act(async () => {
      useWorkspaceStore.getState().setMetaUi({ selectedHit: hits[0] });
    });
    await act(async () => {
      await Promise.resolve();
    });
    const start = buttonByText(tr("meta.verdicts"));
    await click(start);
    expect(buttonByText(tr("meta.saveVerdict"))).not.toBeNull();

    // Y applies "Yes" to the focused gating criterion and advances (two exist).
    const pane = document.querySelector('[tabindex="-1"]') as HTMLElement | null;
    expect(pane).not.toBeNull();
    await act(async () => {
      pane?.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true }));
    });
    const selects = document.querySelectorAll("select");
    expect(Array.from(selects).some((s) => (s as HTMLSelectElement).value === "Yes")).toBe(true);

    // ArrowDown focuses the next hit.
    await act(async () => {
      pane?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    });
    expect(useWorkspaceStore.getState().metaUi.selectedHit?.hit_id).toBe(2);
  });

  it("walks criteria with Y/N/U, advancing and saving the last one", async () => {
    const hits = [
      { hit_id: 1, title: "One", status: "imported", created: "", updated: "" },
      { hit_id: 2, title: "Two", status: "imported", created: "", updated: "" },
    ];
    apiMock.fns.metaHits = vi.fn(async () => ({ hits, total: 2, limit: 100, offset: 0 }));
    apiMock.fns.metaScreening = vi.fn(async () => []);
    apiMock.fns.metaSaveScreening = vi.fn(async () => ({ ok: true, id: 1 }));
    apiMock.fns.metaCriteria = vi.fn(async () => [
      { id: 1, position: 0, key: "c1", label: "C1", prompt_text: "p", created: "" },
      { id: 2, position: 1, key: "c2", label: "C2", prompt_text: "p", created: "" },
    ]);

    await render();
    await act(async () => {
      useWorkspaceStore.getState().setMetaUi({ selectedHit: hits[0] });
    });
    await act(async () => {
      await Promise.resolve();
    });
    await click(buttonByText(tr("meta.verdicts")));

    const pane = document.querySelector('[tabindex="-1"]') as HTMLElement | null;
    const press = async (key: string, shiftKey = false) => {
      await act(async () => {
        pane?.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true }));
      });
    };

    // The first gating criterion starts focused.
    expect(document.querySelector('[data-focused="true"]')?.textContent).toContain("C1");

    // Y sets Yes on the focused criterion and advances to the next one.
    await press("y");
    expect(useWorkspaceStore.getState().metaUi.selectedHit?.hit_id).toBe(1);
    expect(
      Array.from(document.querySelectorAll("select")).some(
        (s) => (s as HTMLSelectElement).value === "Yes",
      ),
    ).toBe(true);
    expect(document.querySelector('[data-focused="true"]')?.textContent).toContain("C2");

    // U on the last criterion persists the row and loads the next hit.
    await press("u");
    expect(apiMock.fns.metaSaveScreening).toHaveBeenCalledTimes(1);
    const saved = apiMock.fns.metaSaveScreening.mock.calls[0][0] as {
      hit_id: number;
      verdicts: Record<string, { applies: string }>;
    };
    expect(saved.hit_id).toBe(1);
    expect(saved.verdicts.c1.applies).toBe("Yes");
    expect(saved.verdicts.c2.applies).toBe("Unsure");
    expect(useWorkspaceStore.getState().metaUi.selectedHit?.hit_id).toBe(2);
  });

  it("moves the focused criterion with Tab and Shift+Tab", async () => {
    const hits = [{ hit_id: 1, title: "One", status: "imported", created: "", updated: "" }];
    apiMock.fns.metaHits = vi.fn(async () => ({ hits, total: 1, limit: 100, offset: 0 }));
    apiMock.fns.metaScreening = vi.fn(async () => []);
    apiMock.fns.metaCriteria = vi.fn(async () => [
      { id: 1, position: 0, key: "c1", label: "C1", prompt_text: "p", created: "" },
      { id: 2, position: 1, key: "c2", label: "C2", prompt_text: "p", created: "" },
      { id: 3, position: 2, key: "c3", label: "C3", prompt_text: "p", created: "" },
    ]);

    await render();
    await act(async () => {
      useWorkspaceStore.getState().setMetaUi({ selectedHit: hits[0] });
    });
    await act(async () => {
      await Promise.resolve();
    });
    await click(buttonByText(tr("meta.verdicts")));

    const pane = document.querySelector('[tabindex="-1"]') as HTMLElement | null;
    const press = async (key: string, shiftKey = false) => {
      await act(async () => {
        pane?.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true }));
      });
    };

    expect(document.querySelector('[data-focused="true"]')?.textContent).toContain("C1");
    await press("Tab");
    expect(document.querySelector('[data-focused="true"]')?.textContent).toContain("C2");
    await press("Tab");
    expect(document.querySelector('[data-focused="true"]')?.textContent).toContain("C3");
    await press("Tab", true);
    expect(document.querySelector('[data-focused="true"]')?.textContent).toContain("C2");
  });

  it("pauses a running job and deletes a hit", async () => {
    apiMock.fns.metaJobs = vi.fn(async () => [
      {
        id: "j1",
        kind: "screen",
        label: "LLM screening",
        state: "running",
        progress: 10,
        message: "screening",
        paused: false,
        started: 1,
      },
    ]);
    apiMock.fns.metaJobControl = vi.fn(async () => ({ ok: true }));
    apiMock.fns.metaDeleteHit = vi.fn(async () => undefined);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMock.fns.metaHits = vi.fn(async () => ({
      hits: [{ hit_id: 5, title: "Delete me", status: "imported", created: "", updated: "" }],
      total: 1,
      limit: 100,
      offset: 0,
    }));

    await render();
    await act(async () => {
      await Promise.resolve();
    });

    const pause = document.querySelector(
      `button[aria-label="${tr("meta.pauseJob")}"]`,
    ) as HTMLButtonElement | null;
    expect(pause).not.toBeNull();
    await click(pause);
    expect(apiMock.fns.metaJobControl).toHaveBeenCalledWith("j1", "pause");

    const del = document.querySelector(
      `button[aria-label="${tr("meta.deleteHit")}"]`,
    ) as HTMLButtonElement | null;
    expect(del).not.toBeNull();
    await click(del);
    expect(confirmSpy).toHaveBeenCalled();
    expect(apiMock.fns.metaDeleteHit).toHaveBeenCalledWith(5);
    confirmSpy.mockRestore();
  });

  it("loads the next page of hits", async () => {
    const pageOne = Array.from({ length: 100 }, (_, i) => ({
      hit_id: i + 1,
      title: `Hit ${i + 1}`,
      status: "imported",
      created: "",
      updated: "",
    }));
    const pageTwo = [{ hit_id: 101, title: "Hit 101", status: "imported", created: "", updated: "" }];
    const metaHits = vi.fn(async (opts: { offset?: number }) =>
      (opts?.offset ?? 0) === 0
        ? { hits: pageOne, total: 101, limit: 100, offset: 0 }
        : { hits: pageTwo, total: 101, limit: 100, offset: 100 },
    );
    apiMock.fns.metaHits = metaHits;

    await render();
    await act(async () => {
      await Promise.resolve();
    });
    await click(buttonByText(tr("meta.next")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(metaHits).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 100 }));
    expect(document.body.textContent).toContain("Hit 101");
  });
});

describe("MetaView conflicts tab", () => {
  it("renders the conflicts envelope and resolves with the real ids", async () => {
    apiMock.fns.metaScreeningAgreement = vi.fn(async () => ({
      reference: "screening",
      unit: "screening",
      n_units: 5,
      raters: ["alice", "bob"],
      overall: { ac1: 0.85, ac2: 0.7, n_fields: 1, n_items_total: 5 },
      fields: [
        {
          name: "c1",
          label: "Randomised",
          unit: "Exp",
          n_levels: 2,
          n_items: 5,
          n_raters: 2,
          ac1: 0.85,
          ac2: 0.7,
        },
      ],
      llm_excluded: [],
    }));
    apiMock.fns.metaScreeningConflicts = vi.fn(async () => ({
      total: 1,
      offset: 0,
      limit: 300,
      master: "judge",
      raters: ["alice", "bob"],
      fields: [{ name: "c1", label: "Randomised", open: 1, settled: 0 }],
      studies: [{ key: 1, label: "1", n_open: 1, n_settled: 0, n_fields: 1 }],
      rows: [
        {
          key: "1|c1",
          hit_id: 1,
          criterion_key: "c1",
          field: "c1",
          kind: "screening",
          values: { alice: "Yes", bob: "No" },
          settled: false,
        },
      ],
    }));
    apiMock.fns.metaResolveScreeningConflict = vi.fn(async () => ({ ok: true }));

    await render();
    await click(buttonByText(tr("meta.tabConflicts")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaScreeningAgreement).toHaveBeenCalled();
    expect(document.body.textContent).toContain("Randomised");
    expect(document.body.textContent).toContain("0.850");

    const chip = document.querySelector(
      `button[title="${tr("meta.resolveWith", { owner: "alice" })}"]`,
    );
    expect(chip).not.toBeNull();
    await click(chip);

    expect(apiMock.fns.metaResolveScreeningConflict).toHaveBeenCalledTimes(1);
    expect(apiMock.fns.metaResolveScreeningConflict.mock.calls[0][0]).toMatchObject({
      hit_id: 1,
      criterion_key: "c1",
      value: "Yes",
    });
  });

  it("sends field_name (not field) when resolving an extraction conflict", async () => {
    apiMock.fns.metaExtractionAgreement = vi.fn(async () => ({
      reference: "extraction",
      unit: "extraction",
      n_units: 2,
      raters: ["alice", "bob"],
      overall: { ac1: 0.6, ac2: null, n_fields: 1, n_items_total: 2 },
      fields: [
        { name: "domain", label: "Domain", unit: "Metric", n_levels: 2, n_items: 2, n_raters: 2, ac1: 0.6 },
      ],
      llm_excluded: [],
    }));
    apiMock.fns.metaExtractionConflicts = vi.fn(async () => ({
      total: 1,
      offset: 0,
      limit: 300,
      master: "judge",
      raters: ["alice", "bob"],
      fields: [{ name: "domain", label: "Domain", open: 1, settled: 0 }],
      studies: [{ key: 7, label: "7", n_open: 1, n_settled: 0, n_fields: 1 }],
      rows: [
        {
          key: "7|0|Y|domain",
          hit_id: 7,
          field: "domain",
          field_name: "domain",
          record_index: 0,
          metric_key: "Y",
          metric_index: 0,
          kind: "metric",
          values: { alice: "belief", bob: "attitude" },
          settled: false,
        },
      ],
    }));
    apiMock.fns.metaResolveExtractionConflict = vi.fn(async () => ({ ok: true }));

    await render();
    await click(buttonByText(tr("meta.tabConflicts")));
    await act(async () => {
      await Promise.resolve();
    });
    // Switch the conflicts tab to the extraction scope.
    await click(buttonByText(tr("meta.agreementExtraction")));
    await act(async () => {
      await Promise.resolve();
    });

    const chip = document.querySelector(
      `button[title="${tr("meta.resolveWith", { owner: "alice" })}"]`,
    );
    expect(chip).not.toBeNull();
    await click(chip);

    expect(apiMock.fns.metaResolveExtractionConflict).toHaveBeenCalledTimes(1);
    expect(apiMock.fns.metaResolveExtractionConflict.mock.calls[0][0]).toMatchObject({
      hit_id: 7,
      field_name: "domain",
      record_index: 0,
      metric_key: "Y",
      value: "belief",
    });
  });

  it("passes the active screening stage and renders llm_excluded", async () => {
    apiMock.fns.metaScreeningAgreement = vi.fn(async () => ({
      reference: "screening",
      unit: "screening",
      n_units: 1,
      raters: ["alice"],
      overall: { ac1: null, ac2: null, n_fields: 0, n_items_total: 0 },
      fields: [],
      llm_excluded: [
        { key: "9", title: "Hidden paper", authors: "Doe", year: "2020", include_raters: ["alice"] },
      ],
    }));
    apiMock.fns.metaScreeningConflicts = vi.fn(async () => ({
      total: 0,
      offset: 0,
      limit: 300,
      master: "",
      raters: [],
      fields: [],
      studies: [],
      rows: [],
    }));

    await render();
    act(() => {
      useWorkspaceStore.setState({
        metaUi: { ...useWorkspaceStore.getState().metaUi, screeningStage: "fulltext" },
      });
    });
    await click(buttonByText(tr("meta.tabConflicts")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaScreeningAgreement.mock.calls[0][0]).toMatchObject({ stage: "fulltext" });
    expect(apiMock.fns.metaScreeningConflicts.mock.calls[0][0]).toMatchObject({ stage: "fulltext" });
    expect(document.body.textContent).toContain("Hidden paper");
    expect(document.body.textContent).toContain(tr("meta.llmExcludedTitle"));
  });
});

describe("MetaView extraction editor", () => {
  it("renders the scheme-driven form inline for the selected study", async () => {
    const codebook = {
      version: 2,
      category: "Meta",
      groups: [{ name: "Study", label: "Study" }],
      fields: [
        {
          name: "notes",
          label: "Coder notes",
          group: "Study",
          type: "string",
          editor: "text",
          required: false,
          description: "",
          role: null,
        },
      ],
      metrics: { enabled: false, group: "Metrics", label: "Effect sizes", fields: [] },
      effect_families: [],
      code_fields: [],
    };
    apiMock.fns.metaSchemes = vi.fn(async () => [
      {
        id: 1,
        name: "instruct",
        label: "Instruct",
        codebook: JSON.stringify(codebook),
        created: "",
        updated: "",
      },
    ]);
    apiMock.fns.metaDocuments = vi.fn(async () => [
      { id: 1, hit_id: 7, source_id: 3, status: "done", created: "", updated: "" },
    ]);
    apiMock.fns.metaExtractions = vi.fn(async () => [
      {
        id: 1,
        hit_id: 7,
        owner: "alice",
        scheme: "instruct",
        study_vars: { records: [{ study: { notes: "hello" }, metrics: [] }] },
        dv_metrics: [],
        status: "extracted",
        title: "Paper 7",
        created: "",
        updated: "",
      },
    ]);
    apiMock.fns.metaSaveExtraction = vi.fn(async () => ({
      id: 1,
      hit_id: 7,
      owner: "alice",
      scheme: "instruct",
      study_vars: { records: [] },
      dv_metrics: [],
      status: "extracted",
      created: "",
      updated: "",
    }));

    apiMock.fns.metaHits = vi.fn(async () => ({
      hits: [{ hit_id: 7, title: "Paper 7", status: "included", created: "", updated: "" }],
      total: 1,
      limit: 100,
      offset: 0,
    }));

    await render();
    await click(buttonByText(tr("meta.tabExtract")));
    // Focus the study in the left bar; the center renders its coding form.
    const study = document.querySelector('button[title="Paper 7"]');
    expect(study).not.toBeNull();
    await click(study);

    expect(document.body.textContent).toContain(tr("meta.rawView"));
    const notes = document.querySelector('[aria-label="Coder notes"]') as HTMLInputElement | null;
    expect(notes).not.toBeNull();
    expect(notes?.value).toBe("hello");

    await click(buttonByText(tr("common.save")));
    expect(apiMock.fns.metaSaveExtraction).toHaveBeenCalledTimes(1);
  });
});

describe("MetaView screening filters", () => {
  it("filters the study list by screening status", async () => {
    apiMock.fns.metaHits = vi.fn(async () => ({
      hits: [
        {
          hit_id: 1,
          title: "Included paper",
          status: "included",
          eligible: true,
          screened: true,
          created: "",
          updated: "",
        },
        {
          hit_id: 2,
          title: "Excluded paper",
          status: "excluded",
          eligible: false,
          screened: true,
          created: "",
          updated: "",
        },
        {
          hit_id: 3,
          title: "To screen paper",
          status: "imported",
          eligible: false,
          screened: false,
          created: "",
          updated: "",
        },
      ],
      total: 3,
      limit: 500,
      offset: 0,
    }));

    await render();
    expect(document.body.textContent).toContain("Included paper");
    expect(document.body.textContent).toContain("To screen paper");

    await click(buttonByText(tr("meta.filter_included")));
    expect(document.body.textContent).toContain("Included paper");
    expect(document.body.textContent).not.toContain("Excluded paper");
    expect(document.body.textContent).not.toContain("To screen paper");

    await click(buttonByText(tr("meta.filter_todo")));
    expect(document.body.textContent).toContain("To screen paper");
    expect(document.body.textContent).not.toContain("Included paper");
  });
});

describe("MetaView coder scope + download rows", () => {
  it("defaults the coder scope to the current coder and follows switches until picked", async () => {
    useCoderStore.setState({ coderName: "alice" });
    await render();
    await act(async () => {
      await Promise.resolve();
    });
    expect(useWorkspaceStore.getState().metaUi.coderScope).toBe("alice");

    // Switching the app coder follows while no explicit scope was chosen.
    await act(async () => {
      useCoderStore.setState({ coderName: "bob" });
    });
    expect(useWorkspaceStore.getState().metaUi.coderScope).toBe("bob");

    // An explicit choice pins the scope against later switches.
    await act(async () => {
      useWorkspaceStore.getState().setMetaUi({ coderScope: "alice", coderScopeCustom: true });
    });
    await act(async () => {
      useCoderStore.setState({ coderName: "carol" });
    });
    expect(useWorkspaceStore.getState().metaUi.coderScope).toBe("alice");
  });

  it("lists the coders with All coders last and marks an explicit choice", async () => {
    useCoderStore.setState({ coderName: "alice" });
    apiMock.fns.coders = vi.fn(async () => ({
      current: "alice",
      coders: [
        { name: "alice", coding_count: 2 },
        { name: "bob", coding_count: 0 },
      ],
    }));
    await render();
    // Open the Agreement tab, whose left bar hosts the coder scope.
    await click(buttonByText(tr("meta.tabConflicts")));
    await act(async () => {
      await Promise.resolve();
    });

    const select = document.querySelector(
      `select[aria-label="${tr("meta.coderScope")}"]`,
    ) as HTMLSelectElement | null;
    expect(select).not.toBeNull();
    const values = Array.from(select?.querySelectorAll("option") ?? []).map(
      (o) => (o as HTMLOptionElement).value,
    );
    expect(values).toEqual(["alice", "bob", ""]);

    await act(async () => {
      setSelect(select, "");
    });
    expect(useWorkspaceStore.getState().metaUi.coderScopeCustom).toBe(true);
    expect(useWorkspaceStore.getState().metaUi.coderScope).toBe("");
  });

  it("opens a download row's linked paper in the right bar", async () => {
    apiMock.fns.metaDocuments = vi.fn(async () => [
      { id: 1, hit_id: 7, source_id: 3, status: "done", title: "Paper 7", created: "", updated: "" },
    ]);
    const opened = vi.fn();
    window.addEventListener("qc:rightbar-open", opened);

    await render();
    await click(buttonByText(tr("meta.tabDownload")));
    await act(async () => {
      await Promise.resolve();
    });

    // The old per-row View PDF control and modal are gone…
    expect(buttonByText(tr("meta.viewPdf"))).toBeNull();

    const row = document.querySelector('tr[role="button"]') as HTMLTableRowElement | null;
    expect(row).not.toBeNull();
    await click(row);

    expect(useWorkspaceStore.getState().metaUi.selectedDocument?.source_id).toBe(3);
    expect(opened).toHaveBeenCalled();
    window.removeEventListener("qc:rightbar-open", opened);
  });
});

describe("MetaView workspace UI batch", () => {
  it("shows one-line hints per Analyze section like Reports", async () => {
    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    for (const section of [
      "pooled",
      "subgroup",
      "multiverse",
      "prisma",
      "audit",
      "summary",
      "report",
    ]) {
      expect(document.body.textContent).toContain(tr(`meta.section_${section}_hint`));
    }
  });

  it("renders the Agreement scope and stage switches side by side in one row", async () => {
    await render();
    await click(buttonByText(tr("meta.tabConflicts")));
    await act(async () => {
      await Promise.resolve();
    });

    const scope = buttonByText(tr("meta.agreementScreening"));
    const stage = buttonByText(tr("meta.stageFulltext"));
    expect(scope).not.toBeNull();
    expect(stage).not.toBeNull();
    // Two compact switch groups sharing the same row container.
    expect(scope?.parentElement?.parentElement).toBe(stage?.parentElement?.parentElement);

    await click(stage);
    expect(useWorkspaceStore.getState().metaUi.screeningStage).toBe("fulltext");
  });

  it("keeps the Screen tab free of stage switches and hosts Blind in the menubar", async () => {
    await render();
    expect(buttonByText(tr("meta.stageAbstract"))).toBeNull();
    expect(buttonByText(tr("meta.stageFulltext"))).toBeNull();
    const blindSwitch = document.querySelector(
      `button[role="switch"][aria-label="${tr("meta.blind")}"]`,
    );
    expect(blindSwitch).not.toBeNull();
    await act(async () => {
      (blindSwitch as HTMLElement)?.click();
    });
    expect(useWorkspaceStore.getState().metaUi.blind).toBe(true);
  });

  it("saves screen-tab verdicts at abstract stage", async () => {
    const hits = [{ hit_id: 1, title: "One", status: "imported", created: "", updated: "" }];
    apiMock.fns.metaHits = vi.fn(async () => ({ hits, total: 1, limit: 100, offset: 0 }));
    apiMock.fns.metaScreening = vi.fn(async () => []);
    apiMock.fns.metaSaveScreening = vi.fn(async () => ({ ok: true, id: 1 }));
    apiMock.fns.metaCriteria = vi.fn(async () => [
      { id: 1, position: 0, key: "c1", label: "C1", prompt_text: "p", created: "" },
    ]);
    // Even with a full-text stage stored (e.g. from the Conflicts tab), the
    // Screen tab records abstract-stage verdicts.
    useWorkspaceStore.setState({
      metaUi: { ...useWorkspaceStore.getState().metaUi, screeningStage: "fulltext" },
    });

    await render();
    await act(async () => {
      useWorkspaceStore.getState().setMetaUi({ selectedHit: hits[0] });
    });
    await act(async () => {
      await Promise.resolve();
    });
    await click(buttonByText(tr("meta.verdicts")));

    const pane = document.querySelector('[tabindex="-1"]') as HTMLElement | null;
    await act(async () => {
      pane?.dispatchEvent(new KeyboardEvent("keydown", { key: "u", bubbles: true }));
    });

    expect(apiMock.fns.metaSaveScreening).toHaveBeenCalledTimes(1);
    expect(apiMock.fns.metaSaveScreening.mock.calls[0][0]).toMatchObject({
      hit_id: 1,
      stage: "abstract",
    });
  });

  it("starts collapsed and only sends the criteria the user sets", async () => {
    apiMock.fns.metaCriteria = vi.fn(async () => [
      {
        id: 1,
        position: 0,
        key: "c1",
        label: "Randomised",
        prompt_text: "p",
        created: "",
        exclude_reason: "Not randomised",
      },
      {
        id: 2,
        position: 1,
        key: "c2",
        label: "Control group",
        prompt_text: "p",
        created: "",
        exclude_reason: "No control",
      },
    ]);
    apiMock.fns.metaSaveScreening = vi.fn(async () => ({ ok: true, id: 1 }));
    apiMock.fns.metaHits = vi.fn(async () => ({
      hits: [{ hit_id: 7, title: "Paper 7", status: "included", created: "", updated: "" }],
      total: 1,
      limit: 100,
      offset: 0,
    }));

    await render();
    await click(buttonByText(tr("meta.tabExtract")));
    await act(async () => {
      useWorkspaceStore.getState().setMetaUi({
        selectedHit: { hit_id: 7, title: "Paper 7", status: "included", created: "", updated: "" },
      });
    });
    await act(async () => {
      await Promise.resolve();
    });

    // The panel opens collapsed and invents no verdicts.
    const header = document.querySelector(
      `button[aria-label="${tr("meta.fulltextTitle")}"]`,
    ) as HTMLButtonElement | null;
    expect(header).not.toBeNull();
    expect(header?.getAttribute("aria-expanded")).toBe("false");
    expect(buttonByText(tr("meta.fulltextInclude"))).toBeNull();
    expect(header?.textContent).toBe(tr("meta.fulltextTitle"));

    await click(header);
    expect(buttonByText(tr("meta.fulltextInclude"))).not.toBeNull();
    // Nothing was answered yet: no header badge and no write on open.
    expect(header?.textContent).toBe(tr("meta.fulltextTitle"));
    expect((buttonByText(tr("meta.saveVerdict")) as HTMLButtonElement).disabled).toBe(true);
    expect(apiMock.fns.metaSaveScreening).not.toHaveBeenCalled();

    // Answer only the first criterion; the second stays unset.
    const excludeButtons = Array.from(document.querySelectorAll("button")).filter(
      (b) => b.textContent === tr("meta.fulltextExclude"),
    );
    expect(excludeButtons.length).toBe(2);
    await click(excludeButtons[0]);

    const reason = document.querySelector(
      `input[aria-label="Randomised — ${tr("meta.fulltextReason")}"]`,
    ) as HTMLInputElement | null;
    expect(reason).not.toBeNull();
    await act(async () => {
      setInput(reason, "quasi-experimental only");
    });

    // The badge reflects the explicit choice only.
    expect(header?.textContent).toContain(tr("meta.fulltextExclude"));
    await click(buttonByText(tr("meta.saveVerdict")));

    expect(apiMock.fns.metaSaveScreening).toHaveBeenCalledTimes(1);
    const saved = apiMock.fns.metaSaveScreening.mock.calls[0][0] as {
      verdicts: Record<string, unknown>;
      reason: string;
    };
    expect(saved).toMatchObject({
      hit_id: 7,
      stage: "fulltext",
      verdicts: {
        c1: { applies: "No", certainty: "Medium", reason: "quasi-experimental only" },
      },
      reason: "Randomised: quasi-experimental only",
    });
    // The untouched criterion is never sent.
    expect(saved.verdicts).not.toHaveProperty("c2");

    // Re-include clears the full-text row.
    await click(buttonByText(tr("meta.fulltextReinclude")));
    expect(apiMock.fns.metaSaveScreening).toHaveBeenCalledTimes(2);
    expect(apiMock.fns.metaSaveScreening.mock.calls[1][0]).toMatchObject({
      hit_id: 7,
      stage: "fulltext",
      verdicts: {},
      reason: "",
    });
  });

  it("drives moderator terms from the collapsible group checkboxes", async () => {
    apiMock.fns.metaModerators = vi.fn(async () => [
      { name: "sample_n", label: "Sample size", group: "Study", kind: "study" },
      { name: "dv_domain", label: "Domain", group: "Metrics", kind: "metric" },
    ]);
    const moderator = vi.fn(async (body: { terms?: string[] }) => ({
      role: body.terms?.[0] ?? "",
      terms: body.terms,
      coefficients: [{ term: "Intercept", estimate: 0.3, se: 0.1, z: 3, p: 0.003 }],
    }));
    apiMock.fns.metaAnalysisModerator = moderator;
    apiMock.fns.metaAnalysisSubgroup = vi.fn(async () => ({ key: "", groups: [] }));
    apiMock.fns.metaAnalysisPooled = vi.fn(async () => ({
      k: 0,
      estimate: 0,
      se: 0,
      ci_low: 0,
      ci_high: 0,
      tau2: 0,
      q: 0,
      q_df: 0,
      q_p: 1,
      i2: 0,
      p: 1,
    }));
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await click(buttonByText(tr("meta.section_subgroup")));
    await act(async () => {
      await Promise.resolve();
    });

    // One collapsible group per catalogue group with variable checkboxes.
    expect(document.body.textContent).toContain("Study");
    expect(document.body.textContent).toContain("Metrics");
    const sampleBox = document.querySelector(
      'input[type="checkbox"][aria-label="Sample size"]',
    ) as HTMLInputElement | null;
    const domainBox = document.querySelector(
      'input[type="checkbox"][aria-label="Domain"]',
    ) as HTMLInputElement | null;
    expect(sampleBox?.checked).toBe(true);
    expect(domainBox?.checked).toBe(false);

    await act(async () => {
      domainBox?.click();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(useWorkspaceStore.getState().metaUi.moderatorTerms).toEqual([
      "sample_n",
      "dv_domain",
    ]);
    const last = moderator.mock.calls.at(-1)?.[0] as { terms?: string[] };
    expect(last.terms).toEqual(["sample_n", "dv_domain"]);

    // The menubar "Subgroup by" sets the primary term; both stay in sync.
    const subgroup = document.querySelector(
      `select[aria-label="${tr("meta.subgroupBy")}"]`,
    ) as HTMLSelectElement | null;
    await act(async () => {
      setSelect(subgroup, "dv_domain");
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(useWorkspaceStore.getState().metaUi.moderatorTerms[0]).toBe("dv_domain");
    expect(useWorkspaceStore.getState().metaUi.moderatorTerms).toEqual([
      "dv_domain",
      "sample_n",
    ]);
  });

  it("renders the report preview as markdown instead of raw text", async () => {
    apiMock.fns.metaReport = vi.fn(
      async () => new Blob(["# Results\n\nPooled **effect**."], { type: "text/markdown" }),
    );

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await click(buttonByText(tr("meta.section_report")));
    await click(buttonByText(tr("meta.reportPreview")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaReport).toHaveBeenCalledWith({ scheme: undefined, format: "md" });
    expect(document.querySelector("pre")).toBeNull();
    expect(document.body.textContent).toContain("Results");
    expect(document.body.textContent).toContain("effect");
    // The md/docx/pptx downloads stay available.
    expect(buttonByText(tr("meta.exportMarkdown"))).not.toBeNull();
    expect(buttonByText(tr("meta.exportDocx"))).not.toBeNull();
    expect(buttonByText(tr("meta.exportPptx"))).not.toBeNull();
  });
});

describe("MetaView consensus analysis", () => {
  it("shows no coder picker on Analyze and sends no owner", async () => {
    apiMock.fns.metaAnalysisPooled = vi.fn(async () => ({
      k: 2,
      estimate: 0.4,
      se: 0.1,
      ci_low: 0.2,
      ci_high: 0.6,
      tau2: 0.05,
      q: 1.1,
      q_df: 1,
      q_p: 0.3,
      i2: 9.1,
      p: 0.001,
      n_studies: 2,
      consensus: {
        n_hits: 2,
        n_groups: 2,
        n_single_owner: 0,
        n_consensus_units: 2,
        n_fields_unanimous: 10,
        n_master_resolved: 1,
        n_dropped_conflicts: 1,
        n_dropped_metrics: 0,
      },
    }));
    apiMock.fns.metaAnalysisForest = vi.fn(async () => ({ rows: [] }));
    apiMock.fns.metaAnalysisLeaveOneOut = vi.fn(async () => ({ rows: [] }));

    await render();
    await click(buttonByText(tr("meta.tabAnalyze")));
    await act(async () => {
      await Promise.resolve();
    });

    // No coder scope select on the Analyze left bar…
    expect(
      document.querySelector(`select[aria-label="${tr("meta.coderScope")}"]`),
    ).toBeNull();
    // …but it stays for the Conflicts tab.
    await click(buttonByText(tr("meta.tabConflicts")));
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      document.querySelector(`select[aria-label="${tr("meta.coderScope")}"]`),
    ).not.toBeNull();

    // Every analysis request is owner-free (consensus pooling).
    expect(apiMock.fns.metaAnalysisPooled).toHaveBeenCalled();
    for (const call of apiMock.fns.metaAnalysisPooled.mock.calls) {
      expect(call[0]).not.toHaveProperty("owner");
    }
    for (const call of apiMock.fns.metaAnalysisLeaveOneOut.mock.calls) {
      expect(call[0]).not.toHaveProperty("owner");
    }

    // The consensus drop/count behaviour surfaces instead of staying silent.
    await click(buttonByText(tr("meta.tabAnalyze")));
    await act(async () => {
      await Promise.resolve();
    });
    expect(document.body.textContent).toContain(
      tr("meta.consensusNote", { units: 2, resolved: 1, dropped: 1, metrics: 0 }),
    );
  });

  it("keeps the Screening left bar free of an Agreement shortcut", async () => {
    await render();
    // The Screen tab's left bar offers Import only — the titled Agreement
    // shortcut is gone (agreement lives on the pipeline tabs, not as a
    // Screen shortcut; the "Agreement" pipeline tab itself is untouched).
    expect(buttonByText(tr("meta.importSearch"))).not.toBeNull();
    expect(
      document.querySelector(`button[title="${tr("meta.agreementTitle")}"]`),
    ).toBeNull();
  });
});

describe("MetaView progress consistency", () => {
  it("uses screened_hits (not by_status) for the progress bar", async () => {
    // The backend now reports the distinct screened hits; by_status would tally
    // 10 here even though only 4 studies have a screening row.
    apiMock.fns.metaStatus = vi.fn(async () => ({
      hits: 10,
      criteria: 1,
      schemes: 1,
      eligible: 0,
      documents_done: 0,
      extracted: 0,
      screened_hits: 4,
      by_status: { included: 5, excluded: 5, screened: 0 },
    }));

    await render();
    await act(async () => {
      await Promise.resolve();
    });

    expect(document.body.textContent).toContain(
      tr("meta.screenedProgress", { done: 4, total: 10 }),
    );
    expect(document.body.textContent).not.toContain(
      tr("meta.screenedProgress", { done: 10, total: 10 }),
    );
  });
});

describe("MetaView download progress", () => {
  it("shows downloaded/total and the failed count from status.documents", async () => {
    apiMock.fns.metaStatus = vi.fn(async () => ({
      hits: 10,
      criteria: 1,
      schemes: 1,
      eligible: 6,
      documents_done: 2,
      extracted: 0,
      documents: {
        done: 3,
        failed: 2,
        pending: 1,
        working: 0,
        unretrievable: 0,
        total: 6,
      },
    }));
    apiMock.fns.metaDocuments = vi.fn(async () => [
      { id: 1, hit_id: 7, source_id: 3, status: "done", title: "Paper 7", created: "", updated: "" },
    ]);

    await render();
    await click(buttonByText(tr("meta.tabDownload")));
    await act(async () => {
      await Promise.resolve();
    });

    // The Download left bar reports the backend's document tally…
    expect(document.body.textContent).toContain(
      tr("meta.documentsProgress", { done: 3, total: 6 }),
    );
    // …together with the non-zero failure count.
    expect(document.body.textContent).toContain(tr("meta.documentsFailed", { count: 2 }));
    // The screening bar is not reused on the Download tab.
    expect(document.body.textContent).not.toContain(
      tr("meta.screenedProgress", { done: 0, total: 10 }),
    );
  });

  it("falls back to the eligible-hits count when documents counts are absent", async () => {
    apiMock.fns.metaStatus = vi.fn(async () => ({
      hits: 10,
      criteria: 1,
      schemes: 1,
      eligible: 5,
      documents_done: 1,
      extracted: 0,
    }));

    await render();
    await click(buttonByText(tr("meta.tabDownload")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(document.body.textContent).toContain(
      tr("meta.documentsProgress", { done: 1, total: 5 }),
    );
    // No failures reported, so the danger chip stays hidden.
    expect(document.body.textContent).not.toContain(tr("meta.documentsFailed", { count: 0 }));
  });
});

describe("MetaView agreement shortcut", () => {
  it("drops the Agreement menubar button on Extract/Download/Analyze", async () => {
    await render();
    for (const tabKey of ["meta.tabDownload", "meta.tabExtract", "meta.tabAnalyze"]) {
      await click(buttonByText(tr(tabKey)));
      await act(async () => {
        await Promise.resolve();
      });
      // The old menubar shortcut carried the "Coder agreement" title; the
      // pipeline tab is labelled "Agreement" too, so it is the only match.
      expect(
        document.querySelector(`button[title="${tr("meta.agreementTitle")}"]`),
      ).toBeNull();
      expect(
        Array.from(document.querySelectorAll("button")).filter(
          (b) => b.textContent === tr("meta.agreement"),
        ).length,
      ).toBe(1);
    }
    // The Agreement tab itself stays.
    expect(buttonByText(tr("meta.tabConflicts"))).not.toBeNull();
  });
});

describe("MetaView extract split", () => {
  const codebook = {
    version: 2,
    category: "Meta",
    groups: [{ name: "Study", label: "Study" }],
    fields: [
      {
        name: "notes",
        label: "Coder notes",
        group: "Study",
        type: "string",
        editor: "text",
        required: false,
        description: "",
        role: null,
      },
    ],
    metrics: { enabled: false, group: "Metrics", label: "Effect sizes", fields: [] },
    effect_families: [],
    code_fields: [],
  };

  function schemesMock() {
    apiMock.fns.metaSchemes = vi.fn(async () => [
      {
        id: 1,
        name: "instruct",
        label: "Instruct",
        codebook: JSON.stringify(codebook),
        created: "",
        updated: "",
      },
    ]);
  }

  it("renders the form beside the empty paper state with a divider", async () => {
    schemesMock();
    apiMock.fns.metaDocuments = vi.fn(async () => []);
    apiMock.fns.metaHits = vi.fn(async () => ({
      hits: [{ hit_id: 7, title: "Paper 7", status: "included", created: "", updated: "" }],
      total: 1,
      limit: 100,
      offset: 0,
    }));

    await render();
    await click(buttonByText(tr("meta.tabExtract")));
    await click(document.querySelector('button[title="Paper 7"]'));
    await act(async () => {
      await Promise.resolve();
    });

    expect(document.querySelector('[role="separator"]')).not.toBeNull();
    expect(document.body.textContent).toContain(tr("meta.rawView"));
    expect(document.body.textContent).toContain(tr("meta.noPdfLinked"));
  });

  it("shows the linked paper beside the form when a PDF is linked", async () => {
    schemesMock();
    apiMock.fns.metaDocuments = vi.fn(async () => [
      { id: 1, hit_id: 7, source_id: 3, status: "done", title: "Paper 7", created: "", updated: "" },
    ]);
    apiMock.fns.metaHits = vi.fn(async () => ({
      hits: [{ hit_id: 7, title: "Paper 7", status: "included", created: "", updated: "" }],
      total: 1,
      limit: 100,
      offset: 0,
    }));

    await render();
    await click(buttonByText(tr("meta.tabExtract")));
    await click(document.querySelector('button[title="Paper 7"]'));
    await act(async () => {
      await Promise.resolve();
    });

    expect(document.querySelector('[role="separator"]')).not.toBeNull();
    expect(document.body.textContent).toContain(tr("meta.rawView"));
    // The viewer (not the empty state) occupies the right pane.
    expect(document.body.textContent).not.toContain(tr("meta.noPdfLinked"));
  });
});

describe("MetaView CodingStudio folder import", () => {
  function previewMock() {
    return vi.fn(async () => ({
      folder: "C:/proj",
      exists: true,
      papers: 12,
      texts: 5,
      extraction_files: 3,
      study_count: 7,
      screenings: [{ coder: "alice", rows: 14 }],
      workbook: { rows: 42, path: "extraction.xlsx" },
      schema_version: "2.1",
      sample_studies: [{ key: "s1", title: "Study One", doi: "10.1/a", records: 2 }],
      errors: [],
    }));
  }

  it("opens the CodingStudio dialog from the Screen left bar", async () => {
    await render();

    const openButton = buttonByText(tr("meta.codingStudioImport"));
    expect(openButton).not.toBeNull();
    await click(openButton);

    expect(useWorkspaceStore.getState().metaUi.codingStudioOpen).toBe(true);
    const input = document.querySelector(
      `input[aria-label="${tr("meta.codingStudioFolder")}"]`,
    ) as HTMLInputElement | null;
    expect(input).not.toBeNull();
  });

  it("labels the import button CS-Import with a CodingStudio tooltip", async () => {
    await render();

    const openButton = buttonByText(tr("meta.codingStudioImport"));
    expect(openButton?.textContent).toBe("CS-Import");
    expect(openButton?.getAttribute("title")).toBe(tr("meta.codingStudioTitle"));
  });

  it("previews the folder and shows the summary counts", async () => {
    apiMock.fns.metaCodingStudioPreview = previewMock();
    await render();
    await click(buttonByText(tr("meta.codingStudioImport")));

    const input = document.querySelector(
      `input[aria-label="${tr("meta.codingStudioFolder")}"]`,
    ) as HTMLInputElement | null;
    await act(async () => {
      setInput(input, "C:/proj");
    });
    await click(buttonByText(tr("meta.codingStudioPreview")));
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaCodingStudioPreview).toHaveBeenCalledWith("C:/proj");
    expect(document.body.textContent).toContain("12");
    expect(document.body.textContent).toContain(tr("meta.codingStudioWorkbookRows", { rows: 42 }));
    expect(document.body.textContent).toContain("alice: 14");
    expect(document.body.textContent).toContain("Study One");
    expect(document.body.textContent).toContain("2.1");
  });

  it("imports with the chosen flags and shows the result counts", async () => {
    apiMock.fns.metaCodingStudioPreview = previewMock();
    apiMock.fns.metaCodingStudioImport = vi.fn(async () => ({
      ok: true,
      scheme: "codingstudio",
      hits_imported: 12,
      hits_skipped: 1,
      screening_rows: 14,
      extractions_imported: 3,
      pdfs_linked: 2,
      errors: [],
    }));
    await render();
    await click(buttonByText(tr("meta.codingStudioImport")));

    const input = document.querySelector(
      `input[aria-label="${tr("meta.codingStudioFolder")}"]`,
    ) as HTMLInputElement | null;
    await act(async () => {
      setInput(input, "C:/proj");
    });
    await click(buttonByText(tr("meta.codingStudioPreview")));
    await act(async () => {
      await Promise.resolve();
    });

    // Set an owner and turn "Link PDFs" off; the other flags stay on.
    const owner = document.querySelector(
      `input[aria-label="${tr("meta.codingStudioOwner")}"]`,
    ) as HTMLInputElement | null;
    await act(async () => {
      setInput(owner, "bob");
    });
    const linkBox = document.querySelector(
      `input[type="checkbox"][aria-label="${tr("meta.codingStudioLinkPdfs")}"]`,
    ) as HTMLInputElement | null;
    expect(linkBox?.checked).toBe(true);
    await act(async () => {
      linkBox?.click();
    });

    const runButton = document.querySelector(
      `button[aria-label="${tr("meta.codingStudioRun")}"]`,
    ) as HTMLButtonElement | null;
    expect(runButton).not.toBeNull();
    await click(runButton);
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMock.fns.metaCodingStudioImport).toHaveBeenCalledTimes(1);
    expect(apiMock.fns.metaCodingStudioImport.mock.calls[0][0]).toMatchObject({
      folder: "C:/proj",
      owner: "bob",
      import_hits: true,
      import_screening: true,
      import_extractions: true,
      link_pdfs: false,
    });
    expect(document.body.textContent).toContain(
      tr("meta.codingStudioDone", {
        hits: "12",
        skipped: "1",
        screening: "14",
        extractions: "3",
        pdfs: "2",
      }),
    );
  });
});
