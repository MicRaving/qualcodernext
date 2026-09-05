// @vitest-environment jsdom
/**
 * Updater store tests: a missing release manifest (no qcnext-latest.json
 * on the latest GitHub release) must surface as the dedicated
 * missing-manifest state — not the raw plugin error ("Could not fetch a
 * valid release JSON from the remote").
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ check: vi.fn() }));

vi.mock("@tauri-apps/plugin-updater", () => ({ check: mocks.check }));

import {
  NO_UPDATE_MANIFEST,
  classifyUpdateCheckError,
  useUpdatesStore,
} from "@/stores/updates";

function enableTauri() {
  Object.defineProperty(window, "__TAURI_INTERNALS__", {
    value: {},
    configurable: true,
  });
}

beforeEach(() => {
  mocks.check.mockReset();
  useUpdatesStore.setState({
    status: "idle",
    info: null,
    progress: 0,
    error: null,
    lastCheckedAt: null,
  });
  // @ts-expect-error test cleanup: restore the non-Tauri (browser) default
  delete window.__TAURI_INTERNALS__;
});

describe("classifyUpdateCheckError", () => {
  it("maps the missing-manifest plugin error to the sentinel", () => {
    expect(
      classifyUpdateCheckError(
        new Error("Could not fetch a valid release JSON from the remote"),
      ),
    ).toBe(NO_UPDATE_MANIFEST);
  });

  it("passes unrelated failures through", () => {
    expect(classifyUpdateCheckError(new Error("network timeout"))).toBeNull();
    expect(classifyUpdateCheckError("plain string")).toBeNull();
  });
});

describe("checkNow", () => {
  it("reports the missing-manifest state when the release has no manifest", async () => {
    enableTauri();
    mocks.check.mockRejectedValue(
      new Error("Could not fetch a valid release JSON from the remote"),
    );
    await useUpdatesStore.getState().checkNow();
    const state = useUpdatesStore.getState();
    expect(state.status).toBe("error");
    expect(state.error).toBe(NO_UPDATE_MANIFEST);
  });

  it("reports up-to-date when no update is available", async () => {
    enableTauri();
    mocks.check.mockResolvedValue(null);
    await useUpdatesStore.getState().checkNow();
    const state = useUpdatesStore.getState();
    expect(state.status).toBe("up-to-date");
    expect(state.error).toBeNull();
  });

  it("surfaces unknown failures verbatim", async () => {
    enableTauri();
    mocks.check.mockRejectedValue(new Error("boom"));
    await useUpdatesStore.getState().checkNow();
    const state = useUpdatesStore.getState();
    expect(state.status).toBe("error");
    expect(state.error).toBe("boom");
  });
});
