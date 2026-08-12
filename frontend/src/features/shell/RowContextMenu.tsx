/**
 * RowContextMenu — the uniform fixed-position right-click menu used by list
 * rows across left bars (files, codes, cases, notes lists).
 */
import type { ReactNode } from "react";
import { Menu, MenuItem } from "@/components/ui/orchestrator";

export interface RowMenuAction {
  label: string;
  icon?: ReactNode;
  danger?: boolean;
  run: () => void;
}

export function RowContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number;
  y: number;
  items: RowMenuAction[];
  onClose: () => void;
}) {
  return (
    <>
      <div
        className="fixed inset-0 z-30"
        onClick={onClose}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
        aria-hidden
      />
      <Menu
        position="fixed"
        className="min-w-40"
        style={{
          left: Math.min(x, window.innerWidth - 170),
          top: Math.min(y, window.innerHeight - items.length * 32 - 10),
        }}
        role="menu"
      >
        {items.map((it) => (
          <MenuItem
            key={it.label}
            role="menuitem"
            className={it.danger ? "text-danger" : ""}
            onClick={() => {
              onClose();
              it.run();
            }}
          >
            {it.icon}
            {it.label}
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}
