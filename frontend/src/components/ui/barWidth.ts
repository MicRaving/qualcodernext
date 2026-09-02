/** Pixel width injected by WorkspaceLayout's border-drag resize (null when
 *  the bar should use its preset width). Kept separate so the orchestrator
 *  only exports components. */
import { createContext, useContext } from "react";

export const BarWidthContext = createContext<number | null>(null);

/** Whether the bar is too narrow to show full labels — hide the label only
 *  when it would be immediately cut off. The bar is 200-520 px (default 288),
 *  so 200 hides only when the bar is at its minimum and the label would
 *  otherwise truncate to "Cod…". */
export function useIsCompactBar(threshold = 200): boolean {
  const width = useContext(BarWidthContext);
  return width != null && width < threshold;
}
