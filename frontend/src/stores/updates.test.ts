// @vitest-environment jsdom
/**
 * Updater store tests: a missing release manifest (no qcnext-latest.json
 * on the latest GitHub release) must surface as the dedicated
 * missing-manifest state — not the raw plugin error ("Could not fetch a
 * valid release JSON from the remote").
 */
import { beforeEach, describe, expect, it, vi, afterEach } from "vitest";

const mocks = vi.hoisted(() => ({ check: vi.fn() }));

vi.mock("@tauri-apps/plugin-updater", () => ({ check: mocks.check }));

import {
  LARGE_UPDATE_BYTES,
  NO_UPDATE_MANIFEST,
  NATIVE_DELTA_MAX_BYTES,
  classifyUpdateCheckError,
  compareNightlyVersions,
  effectiveVersion,
  formatBytes,
  nightlyManifestUsable,
  nightlyVisibleOnChannel,
  parseNightlyVersion,
  patchHooks,
  updateDownloadSize,
  useUpdatesStore,
} from "@/stores/updates";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/api";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

function enableTauri() {
  Object.defineProperty(window, "__TAURI_INTERNALS__", {
    value: {},
    configurable: true,
  });
}

beforeEach(async () => {
  mocks.check.mockReset();
  useUpdatesStore.setState({
    status: "idle",
    info: null,
    progress: 0,
    error: null,
    lastCheckedAt: null,
    settings: null,
    hotpatch: null,
    overlay: null,
    native: null,
  });
  // @ts-expect-error test cleanup: restore the non-Tauri (browser) default
  delete window.__TAURI_INTERNALS__;
  // Fresh reload mock for every test (jsdom has no navigation).
  patchHooks.reload = vi.fn();
  // Sane default for Tauri invokes (individual tests override per command).
  const core = await import("@tauri-apps/api/core");
  vi.mocked(core.invoke).mockReset().mockResolvedValue(8765);
});

afterEach(() => {
  vi.unstubAllGlobals();
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

describe("nightly versions (X.Y.Z_NNN)", () => {
  it("parses stable and nightly versions", () => {
    expect(parseNightlyVersion("0.1.13")).toEqual([0, 1, 13, null]);
    expect(parseNightlyVersion("0.1.13_001")).toEqual([0, 1, 13, 1]);
    expect(parseNightlyVersion("garbage")).toBeNull();
    expect(parseNightlyVersion("1.2")).toBeNull();
  });

  it("sorts nightlies before the stable of the same base", () => {
    expect(compareNightlyVersions("0.1.13_009", "0.1.13")).toBeLessThan(0);
    expect(compareNightlyVersions("0.1.13", "0.1.13_009")).toBeGreaterThan(0);
    expect(compareNightlyVersions("0.1.13_001", "0.1.13_002")).toBeLessThan(0);
    expect(compareNightlyVersions("0.1.12", "0.1.13_001")).toBeLessThan(0);
  });

  it("hides nightlies from the stable channel", () => {
    expect(nightlyVisibleOnChannel("0.1.14", "0.1.13", "stable")).toBe(true);
    expect(nightlyVisibleOnChannel("0.1.14_001", "0.1.13", "stable")).toBe(false);
    expect(nightlyVisibleOnChannel("0.1.14_001", "0.1.13", "nightly")).toBe(true);
    expect(nightlyVisibleOnChannel("0.1.13", "0.1.13_009", "nightly")).toBe(true);
  });

  function stubNightlyManifest(version: string) {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          version,
          base: "9.9.9",
          url: "https://example.test/qcnext-frontend-nightly.zip",
          sha256: "abc",
          signature: "sig",
        }),
      }),
    );
  }

  it("offers a newer nightly on the nightly channel", async () => {
    enableTauri();
    mocks.check.mockResolvedValue(null);
    useUpdatesStore.setState({
      settings: { check_interval: "daily", auto_update: true, channel: "nightly", auto_large_updates: true },
      hotpatch: null,
    });
    stubNightlyManifest("9.9.9_001");
    await useUpdatesStore.getState().checkNow();
    const state = useUpdatesStore.getState();
    expect(state.status).toBe("available");
    expect(state.info?.kind).toBe("nightly");
    expect(state.info?.version).toBe("9.9.9_001");
  });

  it("ignores nightlies on the stable channel", async () => {
    enableTauri();
    mocks.check.mockResolvedValue(null);
    useUpdatesStore.setState({
      settings: { check_interval: "daily", auto_update: true, channel: "stable", auto_large_updates: true },
      hotpatch: null,
    });
    stubNightlyManifest("9.9.9_001");
    await useUpdatesStore.getState().checkNow();
    const state = useUpdatesStore.getState();
    expect(state.status).toBe("up-to-date");
    expect(state.info).toBeNull();
  });
});

describe("nightly install + rollback", () => {
  const nightlyInfo = {
    version: "9.9.9_001",
    kind: "nightly" as const,
    url: "https://example.test/p.zip",
    sha256: "abc123",
    signature: "sig456",
  };
  const nightlySettings = {
    check_interval: "daily" as const,
    auto_update: true,
    channel: "nightly" as const,
    auto_large_updates: true,
  };

  it("rejects manifests without an installable section", () => {
    expect(nightlyManifestUsable({ version: "9.9.9_001" })).toBe(false);
    expect(nightlyManifestUsable({ version: "garbage", url: "u", sha256: "s", signature: "g" })).toBe(false);
    expect(
      nightlyManifestUsable({ version: "9.9.9_001", url: "u", sha256: "s", signature: "g" }),
    ).toBe(true);
    expect(
      nightlyManifestUsable({
        version: "9.9.9_001",
        backend: { url: "u", sha256: "s", signature: "g" },
      }),
    ).toBe(true);
  });

  it("applies a nightly patch and reloads", async () => {
    enableTauri();
    useUpdatesStore.setState({
      status: "available",
      info: nightlyInfo,
      settings: nightlySettings,
      hotpatch: null,
    });
    const apply = vi.spyOn(api, "applyHotpatch").mockResolvedValue({
      app_version: "9.9.9",
      frontend_version: "9.9.9_001",
      previous_version: null,
      channel: "nightly",
    });
    await useUpdatesStore.getState().install();
    expect(apply).toHaveBeenCalledWith({
      version: "9.9.9_001",
      url: "https://example.test/p.zip",
      sha256: "abc123",
      signature: "sig456",
    });
    const state = useUpdatesStore.getState();
    expect(state.status).toBe("up-to-date");
    expect(state.hotpatch?.frontend_version).toBe("9.9.9_001");
    expect(patchHooks.reload).toHaveBeenCalled();
    apply.mockRestore();
  });

  it("surfaces patch failures without reloading", async () => {
    enableTauri();
    useUpdatesStore.setState({
      status: "available",
      info: nightlyInfo,
      settings: nightlySettings,
      hotpatch: null,
    });
    const apply = vi.spyOn(api, "applyHotpatch").mockRejectedValue(new Error("patch signature invalid"));
    await useUpdatesStore.getState().install();
    const state = useUpdatesStore.getState();
    expect(state.status).toBe("error");
    expect(state.error).toContain("signature invalid");
    expect(patchHooks.reload).not.toHaveBeenCalled();
    apply.mockRestore();
  });

  it("rolls back to the previous patch and reloads", async () => {
    enableTauri();
    useUpdatesStore.setState({
      hotpatch: {
        app_version: "9.9.9",
        frontend_version: "9.9.9_002",
        previous_version: "9.9.9_001",
        channel: "nightly",
      },
    });
    const rollback = vi.spyOn(api, "rollbackHotpatch").mockResolvedValue({
      app_version: "9.9.9",
      frontend_version: "9.9.9_001",
      previous_version: null,
      channel: "nightly",
    });
    const rollbackNativeNone = vi.spyOn(api, "rollbackNative").mockRejectedValue(
      new ApiError(404, "no active native delta"),
    );
    const rollbackOverlay = vi.spyOn(api, "rollbackOverlay").mockRejectedValue(
      new ApiError(404, "API error 404 on /patches/rollback: no previous overlay"),
    );
    await useUpdatesStore.getState().rollback();
    expect(rollback).toHaveBeenCalled();
    const state = useUpdatesStore.getState();
    expect(state.hotpatch?.frontend_version).toBe("9.9.9_001");
    expect(patchHooks.reload).toHaveBeenCalled();
    rollback.mockRestore();
    rollbackNativeNone.mockRestore();
    rollbackOverlay.mockRestore();
  });

  it("applies backend + frontend sections with a restart in between", async () => {
    enableTauri();
    const core = await import("@tauri-apps/api/core");
    const invoke = vi.mocked(core.invoke).mockImplementation((cmd: string) =>
      cmd === "restart_backend" ? Promise.resolve(8766) : Promise.resolve(8765),
    );
    const { useProjectStore } = await import("@/stores/project");
    useUpdatesStore.setState({
      status: "available",
      info: {
        version: "9.9.9_001",
        kind: "nightly",
        url: "https://example.test/f.zip",
        sha256: "f",
        signature: "fs",
        backend: { url: "https://example.test/b.zip", sha256: "b", signature: "bs" },
      },
      settings: nightlySettings,
      hotpatch: null,
      overlay: null,
    });
    useProjectStore.setState({ projectPath: "C:/proj.qda" });
    const applyOverlay = vi.spyOn(api, "applyOverlay").mockResolvedValue({
      overlay_version: "9.9.9_001",
      previous_version: null,
      overlay_active: false,
    });
    const applyHotpatch = vi.spyOn(api, "applyHotpatch").mockResolvedValue({
      app_version: "9.9.9",
      frontend_version: "9.9.9_001",
      previous_version: null,
      channel: "nightly",
    });
    const patchesVersion = vi.spyOn(api, "patchesVersion").mockResolvedValue({
      overlay_version: "9.9.9_001",
      previous_version: null,
      overlay_active: true,
    });
    const openProject = vi
      .spyOn(useProjectStore.getState(), "openProject")
      .mockResolvedValue(true);
    await useUpdatesStore.getState().install();
    expect(applyOverlay).toHaveBeenCalledWith({
      version: "9.9.9_001",
      url: "https://example.test/b.zip",
      sha256: "b",
      signature: "bs",
    });
    expect(invoke).toHaveBeenCalledWith("restart_backend");
    expect(openProject).toHaveBeenCalledWith("C:/proj.qda");
    expect(applyHotpatch).toHaveBeenCalled();
    const state = useUpdatesStore.getState();
    expect(state.status).toBe("up-to-date");
    expect(state.overlay?.overlay_active).toBe(true);
    expect(patchHooks.reload).toHaveBeenCalled();
    const order = [
      applyOverlay.mock.invocationCallOrder[0],
      invoke.mock.invocationCallOrder[0],
      applyHotpatch.mock.invocationCallOrder[0],
    ];
    expect(order).toEqual([...order].sort((a, b) => (a ?? 0) - (b ?? 0)));
    applyOverlay.mockRestore();
    applyHotpatch.mockRestore();
    patchesVersion.mockRestore();
    openProject.mockRestore();
    useProjectStore.setState({ projectPath: "" });
  });
});

describe("native deltas", () => {
  const nightlySettings = {
    check_interval: "daily" as const,
    auto_update: true,
    channel: "nightly" as const,
    auto_large_updates: true,
  };
  const nativeState = {
    staged: null,
    applied_from: null,
    applied_to: null,
    previous_to: null,
    bundle_base: "9.9.9",
    pointer: "9.9.9",
  };

  function stubNativeManifest(native: object) {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ version: "9.9.9_001", base: "9.9.9", native }),
      }),
    );
  }

  const nativeSection = {
    from: "9.9.9",
    to: "9.9.9_001",
    url: "https://example.test/n.zip",
    sha256: "n",
    signature: "ns",
    size: 1000,
  };

  it("computes the effective version as the newest layer", () => {
    expect(effectiveVersion(null, null)).toBeDefined();
    expect(
      effectiveVersion(
        { app_version: "9.9.9", frontend_version: "9.9.9_001", previous_version: null, channel: "nightly" },
        { ...nativeState, applied_to: "9.9.9_002" },
      ),
    ).toBe("9.9.9_002");
    expect(
      effectiveVersion(
        { app_version: "9.9.9", frontend_version: "9.9.9_003", previous_version: null, channel: "nightly" },
        { ...nativeState, applied_to: "9.9.9_002" },
      ),
    ).toBe("9.9.9_003");
  });

  it("offers a native delta chaining onto the pointer", async () => {
    enableTauri();
    mocks.check.mockResolvedValue(null);
    useUpdatesStore.setState({
      settings: nightlySettings,
      hotpatch: null,
      overlay: null,
      native: nativeState,
    });
    stubNativeManifest(nativeSection);
    await useUpdatesStore.getState().checkNow();
    const state = useUpdatesStore.getState();
    expect(state.status).toBe("available");
    expect(state.info?.native?.to).toBe("9.9.9_001");
    expect(state.info?.url).toBeUndefined();
  });

  it("skips native deltas on pointer mismatch or oversize", async () => {
    enableTauri();
    mocks.check.mockResolvedValue(null);
    useUpdatesStore.setState({
      settings: nightlySettings,
      hotpatch: null,
      overlay: null,
      native: nativeState,
    });
    stubNativeManifest({ ...nativeSection, from: "9.9.8" });
    await useUpdatesStore.getState().checkNow();
    expect(useUpdatesStore.getState().status).toBe("up-to-date");
    stubNativeManifest({ ...nativeSection, size: NATIVE_DELTA_MAX_BYTES + 1 });
    await useUpdatesStore.getState().checkNow();
    expect(useUpdatesStore.getState().status).toBe("up-to-date");
  });

  it("stages a native delta and relaunches instead of reloading", async () => {
    enableTauri();
    const core = await import("@tauri-apps/api/core");
    const invoke = vi.mocked(core.invoke).mockImplementation((cmd: string) =>
      cmd === "apply_native_plan_and_relaunch"
        ? Promise.resolve("relaunching")
        : Promise.resolve(8765),
    );
    useUpdatesStore.setState({
      status: "available",
      info: { version: "9.9.9_001", kind: "nightly", native: nativeSection },
      settings: nightlySettings,
      hotpatch: null,
      overlay: null,
      native: nativeState,
    });
    const applyNative = vi.spyOn(api, "applyNative").mockResolvedValue({
      staged: "9.9.9_001",
      applied_from: null,
      applied_to: null,
      previous_to: null,
      bundle_base: "9.9.9",
      pointer: "9.9.9",
    });
    const applyHotpatch = vi.spyOn(api, "applyHotpatch").mockResolvedValue({
      app_version: "9.9.9",
      frontend_version: "9.9.9_001",
      previous_version: null,
      channel: "nightly",
    });
    await useUpdatesStore.getState().install();
    expect(applyNative).toHaveBeenCalledWith({
      version: "9.9.9_001",
      from_version: "9.9.9",
      url: "https://example.test/n.zip",
      sha256: "n",
      signature: "ns",
      size: 1000,
    });
    expect(invoke).toHaveBeenCalledWith("apply_native_plan_and_relaunch");
    expect(applyHotpatch).not.toHaveBeenCalled();
    expect(patchHooks.reload).not.toHaveBeenCalled();
    applyNative.mockRestore();
    applyHotpatch.mockRestore();
  });

  it("rolls back a native delta via relaunch", async () => {
    enableTauri();
    const core = await import("@tauri-apps/api/core");
    const invoke = vi.mocked(core.invoke).mockResolvedValue("relaunching");
    useUpdatesStore.setState({
      native: { ...nativeState, applied_from: "9.9.9", applied_to: "9.9.9_001" },
    });
    const rollbackNative = vi.spyOn(api, "rollbackNative").mockResolvedValue({
      staged: null,
      applied_from: "9.9.9",
      applied_to: "9.9.9_001",
      previous_to: null,
      bundle_base: "9.9.9",
      pointer: "9.9.9",
    });
    const rollbackOverlay = vi.spyOn(api, "rollbackOverlay").mockRejectedValue(
      new ApiError(404, "no previous overlay"),
    );
    const rollbackHotpatch = vi.spyOn(api, "rollbackHotpatch").mockRejectedValue(
      new ApiError(404, "no previous patch"),
    );
    await useUpdatesStore.getState().rollback();
    expect(rollbackNative).toHaveBeenCalled();
    expect(invoke).toHaveBeenCalledWith("apply_native_plan_and_relaunch");
    expect(patchHooks.reload).not.toHaveBeenCalled();
    rollbackNative.mockRestore();
    rollbackOverlay.mockRestore();
    rollbackHotpatch.mockRestore();
  });
});

describe("large-update bandwidth control", () => {
  const bigNightly = {
    version: "9.9.9_001",
    kind: "nightly" as const,
    url: "https://example.test/f.zip",
    sha256: "f",
    signature: "fs",
    size: LARGE_UPDATE_BYTES + 1,
  };

  it("formats byte counts", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(12)).toBe("12 B");
    expect(formatBytes(1500)).toBe("1.5 KB");
    expect(formatBytes(900 * 1024)).toBe("900 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(updateDownloadSize({ version: "1", kind: "full" })).toBe(Number.POSITIVE_INFINITY);
    expect(updateDownloadSize(bigNightly)).toBe(LARGE_UPDATE_BYTES + 1);
  });

  it("auto-install skips large updates unless opted in", async () => {
    enableTauri();
    useUpdatesStore.setState({
      status: "available",
      info: bigNightly,
      settings: {
        check_interval: "daily",
        auto_update: true,
        channel: "nightly",
        auto_large_updates: false,
      },
      hotpatch: null,
      overlay: null,
      native: null,
    });
    const applyHotpatch = vi.spyOn(api, "applyHotpatch");
    await useUpdatesStore.getState().install();
    expect(applyHotpatch).not.toHaveBeenCalled();
    expect(useUpdatesStore.getState().status).toBe("available");
    applyHotpatch.mockRestore();
  });

  it("manual install proceeds for large updates", async () => {
    enableTauri();
    useUpdatesStore.setState({
      status: "available",
      info: bigNightly,
      settings: {
        check_interval: "daily",
        auto_update: true,
        channel: "nightly",
        auto_large_updates: false,
      },
      hotpatch: null,
      overlay: null,
      native: null,
    });
    const applyHotpatch = vi.spyOn(api, "applyHotpatch").mockResolvedValue({
      app_version: "9.9.9",
      frontend_version: "9.9.9_001",
      previous_version: null,
      channel: "nightly",
    });
    await useUpdatesStore.getState().install({ manual: true });
    expect(applyHotpatch).toHaveBeenCalled();
    expect(patchHooks.reload).toHaveBeenCalled();
    applyHotpatch.mockRestore();
  });
});
