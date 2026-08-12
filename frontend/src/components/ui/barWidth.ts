/** Pixel width injected by WorkspaceLayout's border-drag resize (null when
 *  the bar should use its preset width). Kept separate so the orchestrator
 *  only exports components. */
import { createContext } from "react";

export const BarWidthContext = createContext<number | null>(null);
