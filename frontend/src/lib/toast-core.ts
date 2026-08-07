/**
 * Pure toast state helpers (no React). The provider in ./toast.tsx consumes
 * these; the tests exercise the reducer logic directly.
 */

export type ToastKind = "success" | "error" | "info";

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

let nextId = 1;

/** Allocate the next monotonically increasing toast id. */
export function nextToastId(): number {
  return nextId++;
}

/** Append a toast with a fresh id, returning a new array. */
export function addToast(toasts: Toast[], kind: ToastKind, message: string): Toast[] {
  return [...toasts, { id: nextToastId(), kind, message }];
}

/** Remove the toast with the given id, returning a new array. */
export function removeToast(toasts: Toast[], id: number): Toast[] {
  return toasts.filter((t) => t.id !== id);
}
