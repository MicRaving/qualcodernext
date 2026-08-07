/**
 * Pure helpers for the sidebar code-tree CRUD actions.
 */
import type { CodeTreeItem } from "@/lib/api";

/**
 * Find a tree item id by exact (case-insensitive) name for merge prompts.
 * Returns null when no item of the requested kind matches.
 */
export function matchTargetByName(
  tree: CodeTreeItem[],
  name: string,
  kind: "code" | "category" = "code",
): number | null {
  const q = name.trim().toLowerCase();
  if (q === "") return null;
  for (const item of tree) {
    if (item.kind === kind && item.name.toLowerCase() === q) return item.id;
  }
  return null;
}

/**
 * Clamp a context-menu position to the viewport with a small margin,
 * so the menu never renders off-screen.
 */
export function clampToViewport(
  x: number,
  y: number,
  width: number,
  height: number,
  viewportWidth = window.innerWidth,
  viewportHeight = window.innerHeight,
): { x: number; y: number } {
  return {
    x: Math.max(4, Math.min(x, viewportWidth - width - 4)),
    y: Math.max(4, Math.min(y, viewportHeight - height - 4)),
  };
}
