/**
 * App-update state — check/download/install via the Tauri updater plugin.
 *
 * The check hits the configured GitHub release manifest; in a plain browser
 * (dev server / vitest) the Tauri internals are absent, so checks report a
 * friendly "desktop only" error instead of crashing.
 */
import { errorMessage } from "@/lib/utils";
import { create } from "zustand";
import { api, type UpdatesSettings } from "@/lib/api";

export type UpdateStatus =
  | "idle"
  | "checking"
  | "available"
  | "up-to-date"
  | "downloading"
  | "error";

export interface UpdateInfo {
  version: string;
  body?: string;
  date?: string;
}

interface UpdatesState {
  status: UpdateStatus;
  info: UpdateInfo | null;
  /** Download progress 0–100 (only while downloading). */
  progress: number;
  error: string | null;
  lastCheckedAt: number | null;
  settings: UpdatesSettings | null;
  loadSettings: () => Promise<void>;
  saveSettings: (settings: UpdatesSettings) => Promise<void>;
  checkNow: () => Promise<void>;
  install: () => Promise<void>;
}

/** Whether the Tauri updater plugin is reachable (desktop app only). */
export function updaterAvailable(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export const useUpdatesStore = create<UpdatesState>((set, get) => ({
  status: "idle",
  info: null,
  progress: 0,
  error: null,
  lastCheckedAt: null,
  settings: null,

  loadSettings: async () => {
    try {
      const settings = await api.updatesSettings();
      set({ settings });
    } catch {
      /* settings stay null — the UI falls back to defaults */
    }
  },

  saveSettings: async (settings: UpdatesSettings) => {
    const saved = await api.setUpdatesSettings(settings);
    set({ settings: saved });
  },

  checkNow: async () => {
    if (!updaterAvailable()) {
      set({
        status: "error",
        error: "desktop only",
        info: null,
        lastCheckedAt: Date.now(),
      });
      return;
    }    set({ status: "checking", error: null });
    try {
      const { check } = await import("@tauri-apps/plugin-updater");
      const update = await check({ timeout: 30_000 });
      if (!update) {
        set({ status: "up-to-date", info: null, lastCheckedAt: Date.now() });
        return;
      }
      set({
        status: "available",
        info: {
          version: update.version,
          body: update.body ?? undefined,
          date: update.date ? new Date(update.date).toISOString() : undefined,
        },
        lastCheckedAt: Date.now(),
      });
    } catch (e) {
      set({
        status: "error",
        error: errorMessage(e, String(e)),
        lastCheckedAt: Date.now(),
      });
    }
  },

  install: async () => {
    const info = get().info;
    if (!info || !updaterAvailable()) return;
    set({ status: "downloading", progress: 0, error: null });
    try {
      const { check } = await import("@tauri-apps/plugin-updater");
      const update = await check({ timeout: 30_000 });
      if (!update || update.version !== info.version) {
        await get().checkNow();
        return;
      }
      let contentLength = 0;
      let downloaded = 0;
      await update.downloadAndInstall((event) => {
        if (event.event === "Started") {
          contentLength = event.data.contentLength ?? 0;
        } else if (event.event === "Progress") {
          downloaded += event.data.chunkLength;
          if (contentLength > 0) {
            set({ progress: Math.min(99, Math.round((downloaded / contentLength) * 100)) });
          }
        }
      });
      set({ status: "up-to-date", progress: 100 });
      // On Windows the install step already exited the app; elsewhere the
      // user restarts manually.
    } catch (e) {
      set({
        status: "error",
        error: errorMessage(e, String(e)),
      });
    }
  },
}));

/** Interval between automatic checks, from the saved cadence. */
export function checkIntervalMs(interval: UpdatesSettings["check_interval"] | undefined): number | null {
  switch (interval) {
    case "daily":
      return 24 * 60 * 60 * 1000;
    case "weekly":
      return 7 * 24 * 60 * 60 * 1000;
    default:
      return null;
  }
}
