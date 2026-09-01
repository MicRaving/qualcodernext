/** Pixel width injected by WorkspaceLayout's border-drag resize (null when
 *  the bar should use its preset width). Kept separate so the orchestrator
 *  only exports components. */
import { createContext, useContext } from "react";

export const BarWidthContext = createContext<number | null>(null);

/** Whether the bar is too narrow to show full labels — show icon + counter only. */
export function useIsCompactBar(threshold = 220): boolean {
  const width = useContext(BarWidthContext);
  return width != null && width < threshold;
}
