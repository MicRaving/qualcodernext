import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn/ui class merge helper. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Extract a displayable error message from an unknown caught value. */
export function errorMessage(e: unknown, fallback = "Operation failed"): string {
  if (e instanceof Error) {
    // ApiError carries the backend's `detail` separately — prefer it when the
    // generic message is bare (it contains the status + path + detail).
    const detail = (e as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    return e.message || fallback;
  }
  return fallback;
}

/** Normalize an uncaught error (event reason, Error, string…) to text. */
export function errorTextOf(e: unknown): string {
  if (e instanceof Error) return e.message || e.name;
  if (typeof e === "string") return e;
  if (e && typeof e === "object" && "message" in e && typeof e.message === "string") {
    return e.message;
  }
  try {
    return JSON.stringify(e);
  } catch {
    return String(e);
  }
}
