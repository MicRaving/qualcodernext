/**
 * Shared window-event subscriptions for coders.
 *
 * Every coder used to hand-roll identical listeners for the shell's
 * `qc:codings-changed` (history undo/redo + coder visibility toggles) and
 * the sidebar's `qc:assign-code` broadcasts — five to six copies each,
 * some without dependency arrays (re-subscribing every render). These
 * hooks are THE implementations; handlers always run through a latest-
 * closure ref so callers can pass inline closures safely.
 */
import { useEffect, useRef } from "react";

/** Subscribe to codings-changed (history undo/redo, visibility toggles). */
export function useCodingsChanged(handler: () => void | Promise<void>): void {
  const ref = useRef(handler);
  useEffect(() => {
    ref.current = handler;
  });
  useEffect(() => {
    const h = () => void ref.current();
    window.addEventListener("qc:codings-changed", h);
    return () => window.removeEventListener("qc:codings-changed", h);
  }, []);
}

/** Subscribe to sidebar code clicks (assign the clicked code to whatever
 *  the coder currently has pending). */
export function useAssignCode(handler: (cid: number) => void): void {
  const ref = useRef(handler);
  useEffect(() => {
    ref.current = handler;
  });
  useEffect(() => {
    const h = (e: Event) => {
      const cid = (e as CustomEvent<{ cid?: number }>).detail?.cid;
      if (typeof cid === "number") ref.current(cid);
    };
    window.addEventListener("qc:assign-code", h);
    return () => window.removeEventListener("qc:assign-code", h);
  }, []);
}
