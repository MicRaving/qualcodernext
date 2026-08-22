/**
 * Shared types for the sidebar modules (code tree + file groups).
 * Extracted from components/shell/Sidebar.tsx — behavior-neutral.
 */
import type { ReactNode } from "react";
import type { CodeTreeItem, Source } from "@/lib/api";

export type ContextMenu =
  | { kind: "code"; x: number; y: number; item: CodeTreeItem }
  | { kind: "file"; x: number; y: number; source: Source };

export interface MenuAction {
  label: string;
  icon: ReactNode;
  danger?: boolean;
  run: () => void;
}

export const MENU_WIDTH = 176;

/** Payload of the in-flight pointer drag. ``subtree`` is the dragged node's
 *  descendant keys, computed once at dragstart and reused for every cycle
 *  guard (the tree cannot change while a drag is in flight). */
export interface DragNode {
  kind: "code" | "category";
  id: number;
  subtree: Set<string>;
}

/** The current drop affordance on the hovered row (``key`` = kind:id). */
export type DropZone =
  | { mode: "before"; key: string }
  | { mode: "after"; key: string }
  | { mode: "into"; key: string }
  | { mode: "merge"; key: string };

/** Body shapes of the backend move endpoints (only set fields are sent;
 *  an explicit null means "move to the root / clear the parent"). */
export type CodeMoveOpts = {
  parent_catid?: number | null;
  supercid?: number | null;
  after_cid?: number | null;
  before_cid?: number | null;
};
export type CategoryMoveOpts = {
  supercatid?: number | null;
  after_catid?: number | null;
  before_catid?: number | null;
};
