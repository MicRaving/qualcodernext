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
 * - rightBar:  the details panel (Inspector)
 * - children:  the center view
 */
import type { ReactNode } from "react";

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
  return (
    <div className="flex h-full flex-col bg-bg text-text-primary">
      {ribbon}
      {menuBar && (
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
          {menuBar}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        {leftBar}
        <main className="min-w-0 flex-1 overflow-hidden">{children}</main>
        {rightBar}
      </div>
      {statusBar}
    </div>
  );
}
