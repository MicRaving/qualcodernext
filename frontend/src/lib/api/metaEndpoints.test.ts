// @vitest-environment jsdom
/**
 * Heavy meta-analysis calls must use the long `ANALYSIS_TIMEOUT_MS` budget.
 * With the 15 s default they aborted mid-computation, retried against a
 * freshly resolved base and then surfaced a bogus "Backend unreachable"
 * (nothing was wrong with the backend — the analysis was simply still running).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { ANALYSIS_TIMEOUT_MS, REQUEST_TIMEOUT_MS } from "@/lib/config";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** Run one endpoint call and collect every numeric delay handed to
 *  `window.setTimeout` (the fetch abort timer schedules exactly one). */
async function delaysFor(run: () => Promise<unknown>): Promise<number[]> {
  const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const spy = vi.spyOn(window, "setTimeout");
  try {
    await run();
    return spy.mock.calls
      .map((call) => call[1])
      .filter((delay): delay is number => typeof delay === "number");
  } finally {
    spy.mockRestore();
    vi.unstubAllGlobals();
  }
}

describe("heavy meta-analysis request timeouts", () => {
  it("uses ANALYSIS_TIMEOUT_MS for the fitted analysis calls", async () => {
    expect(await delaysFor(() => api.metaAnalysisPooled({}))).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaAnalysisModerator({ role: "x" }))).toContain(
      ANALYSIS_TIMEOUT_MS,
    );
    expect(await delaysFor(() => api.metaAnalysisSubgroup({ key: "x" }))).toContain(
      ANALYSIS_TIMEOUT_MS,
    );
    expect(await delaysFor(() => api.metaAnalysisEgger({}))).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaAnalysisPublicationBias({}))).toContain(
      ANALYSIS_TIMEOUT_MS,
    );
    expect(await delaysFor(() => api.metaAnalysisBayes({}))).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaAnalysisLeaveOneOut({}))).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaAnalysisForest())).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaAnalysisMultiverse({}))).toContain(ANALYSIS_TIMEOUT_MS);
  });

  it("uses ANALYSIS_TIMEOUT_MS for figures, reports and the CodingStudio import", async () => {
    expect(await delaysFor(() => api.metaAnalysisForestPng())).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaAnalysisFunnelPng())).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaAnalysisSpecCurvePng())).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaAnalysisBayesPng())).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaPrisma())).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaPrismaPng())).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaSummary())).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaAudit())).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaReport({ format: "md" }))).toContain(ANALYSIS_TIMEOUT_MS);
    expect(await delaysFor(() => api.metaCodingStudioImport({ folder: "x" }))).toContain(
      ANALYSIS_TIMEOUT_MS,
    );
  });

  it("keeps the default budget for light meta calls", async () => {
    const status = await delaysFor(() => api.metaStatus());
    expect(status).toContain(REQUEST_TIMEOUT_MS);
    expect(status).not.toContain(ANALYSIS_TIMEOUT_MS);
  });
});
