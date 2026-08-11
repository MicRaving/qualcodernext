/** Design tokens — the style strings behind the orchestrator primitives. */

export const cls = {
  /** Standard center-view header row (h-10). */
  bar: "flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface px-3",
  /** Compact left/right bar header row (h-5, half of the center bar). */
  compactBar: "flex h-5 shrink-0 items-center gap-1 border-b border-border px-2",
  primary:
    "rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50",
  primaryCompact:
    "flex items-center gap-0.5 rounded-sm bg-accent px-1.5 py-px text-[10px] font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50",
  secondary:
    "rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher disabled:opacity-50",
  danger:
    "rounded-sm border border-danger/50 px-2 py-1 text-xs text-danger hover:bg-danger/10 disabled:opacity-50",
  ghost: "rounded-sm p-1.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary",
  ghostSmall: "rounded-sm p-0.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary",
  countBadge:
    "rounded-sm bg-surface-higher px-1 py-px text-[10px] font-medium text-text-secondary",
  sectionLabel: "text-xs font-medium uppercase tracking-wide text-text-secondary",
  card: "rounded-lg border border-border bg-surface p-4",
  input:
    "h-7 rounded-sm border border-border bg-bg px-2 text-sm outline-none focus:border-accent",
  select:
    "h-7 rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent",
} as const;
