/**
 * WorkspaceLayout — the app's layout orchestrator. Every view flows through
 * the same slots so the shell always delivers the bars consistently:
 *
 *   ┌────────────────── ribbon ──────────────────┐
 *   ├─────────────── menuBar ────────────────────┤   (view function bar)
 *   ├──── leftBar ────┤        center        ├── rightBar ──┤
 *   └────────────────── statusBar ──────────────────┘
 *
 * - ribbon:    the app top bar (navigation, coder, right-side icons)
 * - menuBar:   the view's function bar (tabs, search, actions)
 * - leftBar:   the view's left panel (sidebar / list)
 * - rightBar:  the details panel (Inspector / panes)
 * - children:  the center view
 *
 * The left/right bars are resizable by dragging their inner border; the
 * pixel width flows through BarWidthContext into the bars themselves, so
 * their content adapts as they resize.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { BarWidthContext } from "@/components/ui/barWidth";

const MIN_BAR = 200;
const MAX_BAR = 520;
/** Dragging a bar past this width snaps it shut (hidden state). */
const HIDE_BAR_BELOW = 140;
/** Edge tab width when a bar is hidden (recall arrow). */
const EDGE_TAB = 16;

export function WorkspaceLayout({
  ribbon,
  menuBar,
  leftBar,
  rightBar,
  statusBar,
  children,
}: {
  ribbon: ReactNode;
  menuBar?: ReactNode;
  leftBar?: ReactNode;
  rightBar?: ReactNode;
  statusBar?: ReactNode;
  children: ReactNode;
}) {
  const [leftW, setLeftW] = useState(288);
  const [rightW, setRightW] = useState(288);
  const [leftHidden, setLeftHidden] = useState(false);
  const [rightHidden, setRightHidden] = useState(false);
  const lastLeftW = useRef(288);
  const lastRightW = useRef(288);
  const dragRef = useRef<{ side: "left" | "right"; startX: number; startW: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  // Ribbon right-pane buttons always reopen a collapsed right bar.
  useEffect(() => {
    const onOpen = () => {
      setRightHidden(false);
      setRightW(Math.min(MAX_BAR, lastRightW.current));
    };
    window.addEventListener("qc:rightbar-open", onOpen);
    return () => window.removeEventListener("qc:rightbar-open", onOpen);
  }, []);

  // Ribbon buttons and pane toggles can also collapse the right bar.
  useEffect(() => {
    const onClose = () => setRightHidden(true);
    window.addEventListener("qc:rightbar-close", onClose);
    return () => window.removeEventListener("qc:rightbar-close", onClose);
  }, []);

  function startResize(side: "left" | "right") {
    return (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = {
        side,
        startX: e.clientX,
        startW: side === "left" ? leftW : rightW,
      };
      setDragging(true);
    };
  }

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const delta = e.clientX - drag.startX;
      const next = drag.side === "left" ? drag.startW + delta : drag.startW - delta;
      if (next < HIDE_BAR_BELOW) {
        // Dragged substantially past the minimum width: hide the bar; it is
        // recalled from the very edge of the window via the arrow tab (or a
        // ribbon button). A drag collapse is permanent.
        if (drag.side === "left") setLeftHidden(true);
        else setRightHidden(true);
        return;
      }
      const clamped = Math.min(MAX_BAR, Math.max(MIN_BAR, Math.round(next)));
      if (drag.side === "left") {
        setLeftHidden(false);
        lastLeftW.current = clamped;
        setLeftW(clamped);
      } else {
        setRightHidden(false);
        lastRightW.current = clamped;
        setRightW(clamped);
      }
    };
    const onUp = () => {
      dragRef.current = null;
      setDragging(false);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging]);

  // Keep the bars responsive to window resizing: clamp them so they never
  // swallow more than a third of the viewport.
  useEffect(() => {
    const clamp = () => {
      const max = Math.max(MIN_BAR, Math.round(window.innerWidth / 3));
      setLeftW((w) => Math.min(max, Math.max(MIN_BAR, w)));
      setRightW((w) => Math.min(max, Math.max(MIN_BAR, w)));
    };
    window.addEventListener("resize", clamp);
    return () => window.removeEventListener("resize", clamp);
  }, []);

  const restoreLeft = () => {
    setLeftHidden(false);
    setLeftW(Math.min(MAX_BAR, lastLeftW.current));
  };
  const restoreRight = () => {
    setRightHidden(false);
    setRightW(Math.min(MAX_BAR, lastRightW.current));
  };

  return (
    <div className="flex h-full flex-col bg-bg text-text-primary">
      {ribbon}
      {menuBar && (
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
          {menuBar}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        {leftBar && (
          <div className="relative flex shrink-0" style={{ width: leftHidden ? EDGE_TAB : leftW }}>
            {!leftHidden && (
              <BarWidthContext.Provider value={leftW}>
                <div className="h-full min-w-0">{leftBar}</div>
              </BarWidthContext.Provider>
            )}
            {leftHidden ? (
              <button
                type="button"
                onClick={restoreLeft}
                aria-label="Show left sidebar"
                title="Show left sidebar"
                className="flex h-full items-center border-r border-border bg-surface px-0.5 text-text-secondary hover:bg-surface-higher"
              >
                <ChevronRight size={12} aria-hidden />
              </button>
            ) : (
              <div
                className={`absolute inset-y-0 -right-1 z-30 w-2 cursor-col-resize ${
                  dragging ? "bg-accent/30" : "hover:bg-accent/30"
                }`}
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize left sidebar"
                onMouseDown={startResize("left")}
              />
            )}
          </div>
        )}
        <main id="qc-main" className="min-w-0 flex-1 overflow-hidden">
          {children}
        </main>
        {rightBar && (
          <div className="relative flex shrink-0" style={{ width: rightHidden ? EDGE_TAB : rightW }}>
            {rightHidden ? (
              <button
                type="button"
                onClick={restoreRight}
                aria-label="Show right sidebar"
                title="Show right sidebar"
                className="flex h-full items-center border-l border-border bg-surface px-0.5 text-text-secondary hover:bg-surface-higher"
              >
                <ChevronLeft size={12} aria-hidden />
              </button>
            ) : (
              <>
                <div
                  className={`absolute inset-y-0 -left-1 z-30 w-2 cursor-col-resize ${
                    dragging ? "bg-accent/30" : "hover:bg-accent/30"
                  }`}
                  role="separator"
                  aria-orientation="vertical"
                  aria-label="Resize right sidebar"
                  onMouseDown={startResize("right")}
                />
                <BarWidthContext.Provider value={rightW}>
                  <div className="h-full min-w-0">{rightBar}</div>
                </BarWidthContext.Provider>
              </>
            )}
          </div>
        )}
      </div>
      {statusBar}
    </div>
  );
}
