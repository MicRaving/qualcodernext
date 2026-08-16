/** Design tokens — the style strings behind the orchestrator primitives. */

export const cls = {
  /** Standard center-view header row (h-10). */
  bar: "flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface px-3",
  /** Wrapping header row (coder headers): grows to a second line. */
  barWrap:
    "flex min-h-10 shrink-0 flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-1",
  primary:
    "rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50 qc-motion qc-btn qc-btn-lift qc-btn-primary",
  primaryCompact:
    "flex items-center gap-0.5 rounded-sm bg-accent px-1.5 py-px text-[10px] font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50 qc-motion qc-btn qc-btn-lift",
  secondary:
    "rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher disabled:opacity-50 qc-motion qc-btn qc-btn-lift",
  danger:
    "rounded-sm border border-danger/50 px-2 py-1 text-xs text-danger hover:bg-danger/10 disabled:opacity-50 qc-motion qc-btn qc-btn-lift",
  /** The one compact toolbar button (report + coder toolbars, h-7). */
  toolbarBtn:
    "flex h-7 items-center gap-1 rounded-sm border border-border bg-bg px-2 text-xs hover:bg-surface-higher disabled:opacity-50 qc-motion qc-btn qc-btn-lift",
  /** Compact primary toolbar button (the active tab/toggle in a toolbar). */
  toolbarBtnPrimary:
    "flex h-7 items-center gap-1 rounded-sm bg-accent px-2 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50 qc-motion qc-btn qc-btn-lift qc-btn-primary",
  /** Compact danger toolbar button (cancel/stop in a run bar). */
  toolbarBtnDanger:
    "flex h-7 items-center gap-1 rounded-sm border border-danger/50 px-2 text-xs text-danger hover:bg-danger/10 disabled:opacity-50 qc-motion qc-btn qc-btn-lift",
  /** Compact square icon button (transport: −/+ weight, page nav, memo
   *  save/cancel) — 28px to match toolbarBtn. */
  toolbarIconBtn:
    "flex h-7 w-7 items-center justify-center rounded-sm border border-border bg-bg text-text-secondary hover:bg-surface-higher hover:text-text-primary disabled:opacity-50 qc-motion qc-btn",
  /** Compact square primary icon button (e.g. the AV transport play). */
  toolbarIconBtnPrimary:
    "flex h-7 w-7 items-center justify-center rounded-sm bg-accent text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50 qc-motion qc-btn qc-btn-lift",
  ghost:
    "rounded-sm p-1.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary qc-motion qc-btn",
  ghostSmall:
    "rounded-sm p-0.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary qc-motion qc-btn",
  /** Row-level inline icon button (13–14px icons). */
  ghostRow:
    "rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary qc-motion qc-btn",
  countBadge:
    "rounded-sm bg-surface-higher px-1 py-px text-[10px] font-medium text-text-secondary",
  sectionLabel: "text-xs font-medium tracking-wide text-text-secondary",
  /** Neutral status pill (positions, scopes, counts). */
  pill: "inline-flex items-center gap-1 whitespace-nowrap rounded-sm bg-surface-higher px-1.5 py-px text-[10px] font-medium text-text-secondary",
  /** Accent pill (new/selected markers). */
  pillAccent:
    "inline-flex items-center gap-1 whitespace-nowrap rounded-sm bg-accent px-1.5 py-px text-[10px] font-medium text-[var(--qc-bg)]",
  card: "rounded-lg border border-border bg-surface p-4 qc-card",
  input:
    "h-7 rounded-sm border border-border bg-bg px-2 text-sm outline-none focus:border-accent qc-motion qc-field",
  select:
    "h-7 rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent qc-motion qc-field",
  /** Textarea (sizing/padding via caller class). */
  textarea:
    "rounded-sm border border-border bg-bg text-sm outline-none focus:border-accent qc-motion qc-field",
  /** Floating popup panel (selection toolbar, annotate box, …). */
  popup: "rounded-md border border-border bg-surface shadow-qc-sm",
  /** Field label above a control. */
  fieldLabel: "mb-1 block text-xs text-text-secondary",
  /** Modal/dialog overlay (see Modal in the orchestrator). */
  modalOverlay: "fixed inset-0 z-50 flex items-center justify-center bg-bg/70",
  /** Modal panel (width is set by the size prop or caller class). */
  modalPanel: "rounded-lg border border-border bg-surface shadow-qc-lg",
  /** Modal header row: [icon] [title] ... [close]. */
  modalHeader: "flex items-center gap-2 border-b border-border px-3 py-2",
  /** Popover menu container (dropdowns under bars/buttons). */
  menu: "absolute left-0 top-full z-50 mt-1 rounded-md border border-border bg-surface py-1 shadow-qc-md",
  /** Item inside a Menu. */
  menuItem:
    "flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher qc-motion",
  /** Table header cell. */
  tableHead:
    "border-b border-border px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-text-secondary",
} as const;
