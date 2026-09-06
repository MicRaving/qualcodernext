// @vitest-environment jsdom
/**
 * Project open tests: the open call carries the long project timeout
 * (slow opens are legitimate), and transport stalls map to the
 * slow-project message instead of the raw "Backend unreachable".
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type OpenProjectResult } from "@/lib/api";
import { PROJECT_OPEN_TIMEOUT_MS } from "@/lib/config";
import { useProjectStore } from "@/stores/project";

function failedOpen(): OpenProjectResult {
  return {
    ok: false,
    project_path: "",
    project_name: "",
    migrations_applied: [],
    error: "nope",
    lock_user: "",
  };
}

beforeEach(() => {
  useProjectStore.setState({ busy: false, error: null });
});

describe("openProject", () => {
  it("opens with the long project timeout", async () => {
    expect(PROJECT_OPEN_TIMEOUT_MS).toBe(120_000);
    const open = vi.spyOn(api, "openProject").mockResolvedValue(failedOpen());
    const ok = await useProjectStore.getState().openProject("C:/x.qda");
    expect(ok).toBe(false);
    expect(open).toHaveBeenCalledWith("C:/x.qda", undefined, PROJECT_OPEN_TIMEOUT_MS);
    open.mockRestore();
  });

  it("maps transport stalls to the slow-project message", async () => {
    const open = vi
      .spyOn(api, "openProject")
      .mockRejectedValue(new ApiError(0, "Backend unreachable — gone"));
    const ok = await useProjectStore.getState().openProject("C:/x.qda");
    expect(ok).toBe(false);
    expect(useProjectStore.getState().error).toContain("taking too long");
    open.mockRestore();
  });

  it("keeps raw messages for other failures", async () => {
    const open = vi.spyOn(api, "openProject").mockRejectedValue(new Error("boom"));
    const ok = await useProjectStore.getState().openProject("C:/x.qda");
    expect(ok).toBe(false);
    expect(useProjectStore.getState().error).toContain("boom");
    open.mockRestore();
  });
});
