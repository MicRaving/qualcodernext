/**
 * Centralised view options for coding views.
 * Persists to localStorage so view state survives sessions.
 * Every coder imports from here — no scattered localStorage calls.
 */
import { useCallback, useState } from "react";

const STORAGE_KEY = "qc-coding-view-options";

interface ViewOptions {
  gutterVisible: boolean;
}

const DEFAULTS: ViewOptions = { gutterVisible: false };

function load(): ViewOptions {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch { /* corrupt storage — reset */ }
  return { ...DEFAULTS };
}

function persist(opts: ViewOptions) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(opts));
}

/* ---- plain accessors (for non-React contexts) ---- */

export function getGutterVisible(): boolean {
  return load().gutterVisible;
}

export function setGutterVisible(v: boolean) {
  persist({ ...load(), gutterVisible: v });
}

/* ---- React hook ---- */

export function useGutterVisible(): [boolean, () => void] {
  const [visible, setVisible] = useState(getGutterVisible);

  const toggle = useCallback(() => {
    setVisible((prev) => {
      const next = !prev;
      persist({ ...load(), gutterVisible: next });
      return next;
    });
  }, []);

  return [visible, toggle];
}
