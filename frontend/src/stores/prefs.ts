/**
 * UI preferences + collaboration sync state (Zustand).
 *
 * Owns the theme mode, the accessibility display modes, the
 * auto-show-segment-details pref and the collaboration sync status/actions.
 * UI components call these actions; the store never renders.
 */
import { create } from "zustand";
import { api, type PresenceEntry, type SyncStatus, type SyncConflictV2 } from "@/lib/api";
import { useProjectStore } from "./project";

export type ThemeMode = "light" | "dark" | "oled";

/** Persist + apply the theme: OLED builds on the dark palette (`.dark` is
 *  set too) plus its own `.oled` class; store in localStorage. */
function applyThemeMode(mode: ThemeMode) {
  if (typeof document !== "undefined") {
    const root = document.documentElement;
    root.classList.toggle("dark", mode === "dark" || mode === "oled");
    root.classList.toggle("oled", mode === "oled");
  }
  if (typeof window !== "undefined") {
    localStorage.setItem("qc-theme", mode);
  }
}

/** Seed the theme from localStorage; fall back to the OS preference. */
function initialThemeMode(): ThemeMode {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("qc-theme");
    if (saved === "dark" || saved === "light" || saved === "oled") return saved;
    if (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    ) {
      return "dark";
    }
  }
  return "light";
}

const INITIAL_THEME_MODE = initialThemeMode();
applyThemeMode(INITIAL_THEME_MODE);

/** Accessibility display modes (visual impairments / screen readers). */
export type A11yMode =
  | "off"
  | "screenreader"
  | "high-contrast"
  | "large-text"
  | "reduced-motion"
  | "colorblind";

/** Apply the a11y mode class on <html> and persist it. */
function applyA11yMode(mode: A11yMode) {
  if (typeof document !== "undefined") {
    const root = document.documentElement;
    for (const m of [
      "screenreader",
      "high-contrast",
      "large-text",
      "reduced-motion",
      "colorblind",
    ] as const) {
      root.classList.toggle(`a11y-${m}`, mode === m);
    }
  }
  if (typeof window !== "undefined") {
    localStorage.setItem("qc-a11y", mode);
  }
}

function initialA11yMode(): A11yMode {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("qc-a11y");
    if (
      saved === "screenreader" ||
      saved === "high-contrast" ||
      saved === "large-text" ||
      saved === "reduced-motion" ||
      saved === "colorblind"
    ) {
      return saved;
    }
  }
  return "off";
}

const INITIAL_A11Y_MODE = initialA11yMode();
applyA11yMode(INITIAL_A11Y_MODE);

/** Auto-show segment details is the default behavior now (shown as a bubble
 *  when the memo gutter is off, and in the gutter when it is on) — always on. */
function applyAutoShowSegmentDetails(v: boolean) {
  if (typeof window !== "undefined") {
    localStorage.setItem("qc-auto-show-segment-details", v ? "1" : "0");
  }
}

function initialAutoShowSegmentDetails(): boolean {
  return true;
}

const INITIAL_AUTO_SHOW_SEGMENT_DETAILS = initialAutoShowSegmentDetails();
applyAutoShowSegmentDetails(INITIAL_AUTO_SHOW_SEGMENT_DETAILS);

interface PrefsState {
  themeMode: ThemeMode;
  setThemeMode: (mode: ThemeMode) => void;

  a11yMode: A11yMode;
  setA11yMode: (mode: A11yMode) => void;

  /** Auto-select a freshly created coding in the segment-details bar. */
  autoShowSegmentDetails: boolean;
  setAutoShowSegmentDetails: (v: boolean) => void;

  /** Collaboration sync (Option C: versioned sidecars + conflict resolution). */
  syncStatus: SyncStatus | null;
  setSyncStatus: (v: SyncStatus | null) => void;
  /** Enable/disable the sync cycle. A manual toggle (remember: true) also
   *  writes the per-project override so the decision survives reopens;
   *  the shared-folder auto-enable passes remember: false. */
  setSyncEnabled: (enabled: boolean, opts?: { remember?: boolean }) => Promise<boolean>;
  runSyncNow: () => Promise<boolean>;
  /** Background pull: run one cycle and, when it imported new rows, refresh
   *  the project data + the open coder's segments so other raters' changes
   *  appear automatically (no manual "Sync now" needed). */
  autoSync: () => Promise<boolean>;
  /** Set by the store when the backend reported a shared folder on open;
   *  the shell shows a transient notice and clears it. */
  syncAutoNotice: boolean;
  setSyncAutoNotice: (v: boolean) => void;

  /** Collaboration (Golden Master + sandbox) mode of the open project. */
  collabMode: "single" | "collaboration";
  setCollabMode: (v: "single" | "collaboration") => void;
  /** Fetch the mode from the backend (called after opening a project). */
  loadProjectMode: () => Promise<void>;
  /** Switch the open project to collaboration mode. */
  activateCollaboration: () => Promise<boolean>;
  /** Consolidate to data.qda and return to single-coder mode (destructive). */
  revertCollaboration: () => Promise<boolean>;
  /** Refresh the cold data.qda archive from the live sandbox. */
  consolidate: () => Promise<boolean>;

  /** Pending conflicts awaiting resolution via the ConflictResolver. */
  conflicts: SyncConflictV2[];
  loadConflicts: () => Promise<void>;
  resolveConflict: (
    conflictId: number,
    resolution: "local" | "remote" | "merged",
    mergedRow?: Record<string, unknown>,
  ) => Promise<boolean>;
  resolveAllConflicts: (resolution: "local" | "remote") => Promise<number>;

  /** Live coder presence (who is actively working, and on which file).
   *  Polled while a project is open; shown in the coder flyout and file list. */
  presence: PresenceEntry[];
  setPresence: (v: PresenceEntry[]) => void;
  refreshPresence: () => Promise<void>;
  /** Report the file this instance is currently working on. */
  reportFileActivity: (fileId: number | null, fileName: string) => void;
}

export const usePrefsStore = create<PrefsState>((set) => ({
  themeMode: INITIAL_THEME_MODE,
  setThemeMode: (mode) => {
    applyThemeMode(mode);
    set({ themeMode: mode });
  },

  a11yMode: INITIAL_A11Y_MODE,
  setA11yMode: (mode) => {
    applyA11yMode(mode);
    set({ a11yMode: mode });
  },

  autoShowSegmentDetails: INITIAL_AUTO_SHOW_SEGMENT_DETAILS,
  setAutoShowSegmentDetails: (v) => {
    applyAutoShowSegmentDetails(v);
    set({ autoShowSegmentDetails: v });
  },

  syncStatus: null,
  setSyncStatus: (v) => set({ syncStatus: v }),
  setSyncEnabled: async (enabled, opts) => {
    try {
      await api.setSyncEnabled(enabled);
      // A manual toggle (the coder flyout) becomes the remembered
      // per-project override; the shared-folder auto-enable must NOT
      // write it, so the next open re-detects.
      if (opts?.remember !== false) {
        const path = useProjectStore.getState().projectPath;
        if (path) {
          void api.syncSetOverride(path, enabled ? "on" : "off").catch(() => {});
        }
      }
      const status = await api.syncStatus();
      set({ syncStatus: status });
      return true;
    } catch {
      return false;
    }
  },
  syncAutoNotice: false,
  setSyncAutoNotice: (v) => set({ syncAutoNotice: v }),
  collabMode: "single",
  setCollabMode: (v) => set({ collabMode: v }),
  loadProjectMode: async () => {
    try {
      const res = await api.projectMode();
      set({ collabMode: res.mode });
    } catch {
      /* project closed etc. — keep the last known mode */
    }
  },
  activateCollaboration: async () => {
    let ok = false;
    try {
      const res = await api.activateCollaboration();
      ok = res.ok === true;
    } catch {
      /* 409s (already active / second coder required) land here — resolved
         below against the backend's actual mode. */
    }
    // Always trust the backend's real mode afterwards: it disambiguates the
    // concurrent-activation 409 ("already active" = success for us) from
    // genuine refusals, and keeps the UI from going stale either way.
    try {
      const mode = await api.projectMode();
      set({ collabMode: mode.mode });
      if (!ok && mode.mode === "collaboration") ok = true;
    } catch {
      /* keep the last known mode */
    }
    return ok;
  },
  revertCollaboration: async () => {
    try {
      const res = await api.revertCollaboration();
      if (!res.ok) return false;
      set({ collabMode: "single" });
      return true;
    } catch {
      return false;
    }
  },
  consolidate: async () => {
    try {
      const res = await api.consolidateProject();
      return res.ok;
    } catch {
      return false;
    }
  },
  runSyncNow: async () => {
    try {
      const res = await api.syncNow();
      if (!res.ok) return false;
      const status = await api.syncStatus();
      set({ syncStatus: status });
      return true;
    } catch {
      return false;
    }
  },
  autoSync: async () => {
    if (!useProjectStore.getState().projectPath) return false;
    try {
      const res = await api.syncNow();
      if (!res.ok) return false;
      const status = await api.syncStatus();
      set({ syncStatus: status });
      const imported = Object.values(res.imported ?? {}).reduce(
        (a, r) => a + (r.applied ?? 0),
        0,
      );
      if (imported > 0) {
        // New rows landed in the local sandbox — repaint project data and the
        // open coder's segments (coders listen for qc:codings-changed).
        await useProjectStore.getState().refreshProject().catch(() => {});
        if (typeof window !== "undefined") {
          window.dispatchEvent(new Event("qc:codings-changed"));
        }
      }
      return true;
    } catch {
      return false;
    }
  },
  conflicts: [],
  loadConflicts: async () => {
    try {
      const res = await api.syncConflicts();
      if (res.ok) set({ conflicts: res.conflicts });
    } catch {
      /* project closed etc. */
    }
  },
  resolveConflict: async (conflictId, resolution, mergedRow) => {
    try {
      const res = await api.resolveConflict({
        conflict_id: conflictId,
        resolution,
        merged_row: mergedRow,
      });
      if (!res.ok) return false;
      // Refresh conflicts and status after resolution.
      const [conflictsRes, statusRes] = await Promise.all([
        api.syncConflicts().catch(() => null),
        api.syncStatus().catch(() => null),
      ]);
      if (conflictsRes?.ok) set({ conflicts: conflictsRes.conflicts });
      if (statusRes) set({ syncStatus: statusRes });
      return true;
    } catch {
      return false;
    }
  },
  resolveAllConflicts: async (resolution) => {
    try {
      const res = await api.resolveAllConflicts(resolution);
      if (!res.ok) return 0;
      const [conflictsRes, statusRes] = await Promise.all([
        api.syncConflicts().catch(() => null),
        api.syncStatus().catch(() => null),
      ]);
      if (conflictsRes?.ok) set({ conflicts: conflictsRes.conflicts });
      if (statusRes) set({ syncStatus: statusRes });
      return res.resolved;
    } catch {
      return 0;
    }
  },
  presence: [],
  setPresence: (v) => set({ presence: v }),
  refreshPresence: async () => {
    try {
      const res = await api.syncPresence();
      set({ presence: res.ok ? res.presence : [] });
    } catch {
      /* project closed etc. — keep the last known state */
    }
  },
  reportFileActivity: (fileId, fileName) => {
    // Fire-and-forget: the backend heartbeat keeps the presence fresh even if
    // this call races with a project close.
    void api.setPresenceActivity(fileId, fileName).catch(() => {});
  },
}));
