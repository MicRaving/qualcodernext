// @vitest-environment jsdom
/**
 * Port-resolution tests: the boot gate awaits initApiBase(), so a shell
 * that denies the backend_port command (pre-ACL app builds) must fall back
 * instantly instead of burning the full ~30s poll budget on every boot.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));

import { apiBaseSync, initApiBase, invalidateApiBase } from "@/lib/api/transport";
import { DEV_API_BASE } from "@/lib/config";

function enableTauri() {
  Object.defineProperty(window, "__TAURI_INTERNALS__", {
    value: {},
    configurable: true,
  });
}

beforeEach(() => {
  mocks.invoke.mockReset();
  invalidateApiBase();
  // @ts-expect-error test cleanup: restore the non-Tauri (browser) default
  delete window.__TAURI_INTERNALS__;
});

describe("initApiBase", () => {
  it("resolves the backend port when the command is allowed", async () => {
    enableTauri();
    mocks.invoke.mockResolvedValue(8765);
    await expect(initApiBase()).resolves.toBe("http://127.0.0.1:8765/api/v1");
    expect(apiBaseSync()).toBe("http://127.0.0.1:8765/api/v1");
  });

  it("keeps polling through transient (backend still booting) failures", async () => {
    enableTauri();
    mocks.invoke
      .mockRejectedValueOnce(new Error("backend not ready"))
      .mockResolvedValue(8766);
    await expect(initApiBase()).resolves.toBe("http://127.0.0.1:8766/api/v1");
    expect(mocks.invoke).toHaveBeenCalledTimes(2);
  });

  it("falls back instantly when the shell denies the command by ACL", async () => {
    enableTauri();
    mocks.invoke.mockRejectedValue(
      new Error("Command backend_port not allowed by ACL"),
    );
    const started = Date.now();
    await expect(initApiBase()).resolves.toBe(DEV_API_BASE);
    // The full poll budget is ~30s; a denial must not burn any of it.
    expect(Date.now() - started).toBeLessThan(5000);
    expect(mocks.invoke).toHaveBeenCalledTimes(1);
  });
});
