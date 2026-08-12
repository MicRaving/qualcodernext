# QualCoder v4 — UI Design Language & Structural Specification

This is the authoritative spec for the frontend. Every screen, component and
future addition MUST follow it. It defines the layout system, the exact
styling of every control, and where every element sits. When in doubt,
mirror an existing screen — the orchestrator (`WorkspaceLayout`) is the
single source of truth for structure.

## 0. The design orchestrator module

`frontend/src/components/ui/orchestrator.tsx` is the ONLY place that
defines structural UI parts. Views import from it — they never hardcode
design classes:

- `Button` — variants `primary` / `primaryCompact` / `secondary` / `danger`
  with an optional `icon` prop.
- `IconButton` — ghost icon button; `label` (aria-label) and `title` are
  REQUIRED props; `size` is `sm` (p-0.5, toolbar/menu), `md` (p-1.5, bars)
  or `row` (p-1, list rows).
- `ViewHeader` — the center-view header (`h-10`): back button + `title` +
  optional `meta` + `actions` on the right. `wrap` lets the row flow to a
  second line (coder headers); `back` can be `false` or a custom handler.
- `BarHeader` — the left/right bar header (h-10, same height as the center
  header): `title` + `count` badge + `actions`. Never part of the scrollable
  area — it sits in `LeftBar`'s `header` slot.
- `LeftBar` — the uniform left/right bar shell: fixed `header` + a
  `qc-scroll` scrollable body; `width` `sm` (w-64) / `md` (w-72),
  `borderSide` `r` / `l`.
- `Input`, `Select`, `Textarea`, `Field` — form controls built on the
  `cls.input` / `cls.select` / `cls.textarea` tokens; `Field` renders the
  label above its control.
- `Modal` — the uniform dialog: overlay + panel (+ optional header with
  close X). Handles Escape + backdrop dismissal itself; `closeDisabled`
  keeps the X inert while a form is busy; `size` sm/md/lg/xl.
- `Menu` / `MenuItem` — popover dropdowns (absolute under a trigger, or
  `position="fixed"` for right-click context menus).
- `TableHead` — the uniform table header cell (uppercase, tracking-wide).
- `CountBadge`, `SectionLabel`, `Card`, `ErrorBanner` (tone
  `danger`/`warning`/`success`), `LoadingState`, `EmptyState`.

Style strings live in `frontend/src/components/ui/tokens.ts` (`cls`);
additional layout tokens there include `popup` (floating panels),
`row` (list rows), `modal*`, `menu*`, `fieldLabel`, `ghostRow`.
If a part is missing, add it to the orchestrator — never inline new
structural classes in a view.

---

## 1. Layout system — the orchestrator

`frontend/src/components/shell/WorkspaceLayout.tsx` is the ONLY layout
engine. Views never lay themselves out; they fill slots:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ RIBBON  (h-11, bg-surface, border-b border-border, px-3)                 │
├──────────────────────────────────────────────────────────────────────────┤
│ MENU BAR  (h-10, bg-surface, border-b border-border, px-3)   ← optional  │
├──────────────┬──────────────────────────────────────────────┬────────────┤
│ LEFT BAR     │ CENTER VIEW                                 │ RIGHT BAR  │
│ w-64/w-72    │ flex-1, bg-bg, overflow-hidden              │ w-72       │
│ bg-surface   │                                              │ bg-surface │
│ border-r     │                                              │ border-l   │
├──────────────┴──────────────────────────────────────────────┴────────────┤
│ STATUS BAR  (h-6, bg-surface, border-t border-border, px-3)   ← optional │
└──────────────────────────────────────────────────────────────────────────┘
```

### Slot rules (exact)

| Slot | Height/width | Background | Border | Padding |
|---|---|---|---|---|
| Ribbon | `h-11` | `bg-surface` | `border-b border-border` | `px-3` |
| Menu bar | `h-10` | `bg-surface` | `border-b border-border` | `px-3` |
| Left bar | `w-64` (Sidebar) or `w-72` (lists) | `bg-surface` | `border-r border-border` | — |
| Right bar | `w-72` | `bg-surface` | `border-l border-border` | — |
| Center | `flex-1` | `bg-bg` | — | — |
| Status bar | `h-6` | `bg-surface` | `border-t border-border` | `px-3` |

- Every bar except the center is `shrink-0`; the body row is
  `flex min-h-0 flex-1`; the center is `min-w-0 flex-1 overflow-hidden`.
- The whole shell is `flex h-full flex-col bg-bg text-text-primary`.
- Without an open project the shell renders ONLY the ribbon (nav disabled)
  and the center empty state (New project / Open project / recent list).

### Left-bar header (all list left bars)

Every left bar is a `LeftBar` whose fixed header (via `BarHeader`, h-10 —
same height as the center header) sits outside the scrollable area:

```
[h-10, border-b border-border, px-3, flex items-center gap-2]
[ title (h1, text-sm font-semibold) ] [ count badge ] ... [ actions ]
```

- Count badge: `CountBadge` — `rounded-sm bg-surface-higher px-1 py-px text-[10px] font-medium text-text-secondary`.
- Right-side actions: yellow/accent add or import buttons (`Button
  variant="primaryCompact"`) and ghost icons (`IconButton size="sm"`).
- List rows below: `border-b border-border`, selected row `bg-accent/10`.
- Left-bar menus (dropdowns) open below the header: `Menu` — `absolute
  left-0 top-full z-50 mt-1 rounded-md border border-border bg-surface
  py-1 shadow-lg`.

### Center-view header (all views)

Every center view starts with `ViewHeader` (h-10):

```
[back ←] [ h1 title ] [ meta ] ... [ interaction buttons ]
```

- The back button (leftmost) is rendered by `ViewHeader`; it navigates to
  Files. It is present in EVERY center view header.
- Right-side interaction buttons use `Button` variants.

Views that need a function bar render it as the FIRST row of the center
(visually identical: `h-10 border-b border-border bg-surface px-3`).
View-global toolbars (e.g. Graphs) are passed to the orchestrator's
`menuBar` slot instead.

---

## 2. Buttons

### Variants (exact classes)

| Variant | Classes | Use for |
|---|---|---|
| **Primary** | `rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50` | The ONE main action per panel/screen (Import, Save, Create, Set end…) |
| **Secondary** | `rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher` | Alternative actions, toggles, pickers |
| **Ghost icon** | `rounded-sm p-1.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary` | Utility icons: back, refresh, close, bookmark |
| **Danger** | text: `text-danger`; border: `border border-danger/50`; hover `bg-danger/10` | Destructive actions (Delete) |
| **Active/toggle** | `border-accent text-accent` (border buttons) or `bg-surface-higher text-accent` (tabs/segments) | The selected state of toggle groups |

### Rules

- Every icon-only button MUST have `aria-label` + `title` (use `IconButton`;
  its `size` is `sm` p-0.5, `md` p-1.5, `row` p-1).
- Decorative icons MUST have `aria-hidden`.
- Disabled: `disabled:opacity-50` (buttons) / `disabled:opacity-40` (rows).
- Buttons never use shadows; radius is always `rounded-sm` (except cards/panels `rounded-lg`).
- Row-level inline icon buttons: `IconButton size="row"` — `rounded-sm p-1 text-text-secondary hover:bg-surface-higher` (size 13–14 icons).

---

## 3. Icons (lucide-react)

| Size | Where |
|---|---|
| `20` | Ribbon nav buttons + right icon buttons (History/AI/Settings) |
| `16` | Back buttons in center view headers, view-level utility icons |
| `14` | Left-bar header actions, menu items, toolbar buttons |
| `12–13` | Inside buttons, list rows, tabs, badges |

Semantics: `User` = coder, `Captions` = transcript, `Mic` = transcribe,
`Users` = speakers, `Bookmark` = bookmarks, `Plus` = add, `Pencil` = rename,
`Trash2` = delete, `Search` = search, `RefreshCw` = refresh, `X` = close/dismiss,
`ArrowLeft` = back, `Hash` = memos/codes, `StickyNote` = annotations/notes,
`FileText` = text files, `FolderOpen` = categories.

---

## 4. Typography

| Role | Classes |
|---|---|
| View/panel title | `text-sm font-semibold text-text-primary` |
| Section label | `text-xs font-medium uppercase tracking-wide text-text-secondary` |
| Body text | `text-sm text-text-primary` |
| Meta / secondary | `text-xs text-text-secondary` |
| Empty states | `text-sm text-text-secondary`, centered, with a 24px icon above |
| Status/summary | `text-xs` |

---

## 5. Colors (CSS variables — never hardcode hex)

| Variable | Meaning |
|---|---|
| `--qc-accent` | Primary actions, active nav/tabs, selection |
| `--qc-bg` | Content background (center, canvases) |
| `--qc-surface` | Bars, panels, cards |
| `--qc-surface-higher` | Hover, active backgrounds |
| `--qc-border` | All separators and borders |
| `--qc-text-primary` | Primary text |
| `--qc-text-secondary` | Secondary text, meta |
| `--qc-danger` | Destructive text/borders |
| `--qc-warning` | Warnings |
| `--qc-success` | Success indicators (sync dot, health) |

Status dots (e.g. coder/sync indicator): `h-1.5 w-1.5 rounded-full`,
`bg-success` / `bg-danger` / `bg-transparent` (off).

---

## 6. Ribbon (exact order, left → right)

With a project open:

```
[Dashboard] [Files] [Cases] [Notes] [Reports] [Graphs] │ [spacer]
[Coder switcher: User + name + sync-dot + ▾] [queue chip?] [History]
[AI] [Settings]
```

- Nav buttons: `icon 20 + label text-xs font-medium`, active =
  `bg-surface-higher text-accent`, idle = `text-text-secondary`.
- Divider after nav: `h-5 w-px bg-border`.
- Coder switcher: single button `flex max-w-44 items-center gap-1.5 rounded-sm
  border border-border bg-bg px-2 py-1 text-xs`; sync dot INSIDE it (never a
  separate button).
- Right icon buttons (History, AI, Settings): icon-only 20, aria-label+title,
  active = `bg-surface-higher text-accent`.
- Without a project: nav buttons rendered DISABLED
  (`disabled`, `cursor-not-allowed text-text-secondary/40`), right side shows
  only the theme toggle. NO backend status indicator.
- The theme toggle: `rounded-sm border border-border bg-bg px-2 py-1 text-xs`.
- The BACK button is NOT in the ribbon — it lives in every center view
  header (`ViewHeader`).

## 7. Center headers per view (registry)

| View | Center header (ViewHeader) | Notes |
|---|---|---|
| coding (Text/PDF/Image/AV) | back + file name + coder controls | controls wrap to a second row (`wrap` prop on ViewHeader) |
| files | back + "Files" + count + search/filters/import | |
| dashboard | back + project name + version + openers | |
| cases | back + case name | details pane |
| notes | back + type name | editor pane |
| analyze | back + "Analysis" + report title | the reports left bar is the navigation |
| graphs | back + "Graphs" + picker/actions | the function bar renders as the FIRST row of the center (like a ViewHeader function bar) |
| history / ai / settings | back + title + actions | |

## 8. Left bars per view (registry)

| View | Left bar | Width | Header (BarHeader) |
|---|---|---|---|
| coding | Sidebar — code tree (namespace-aware, depth ≤ 64) | w-72 | "Codes" + count + annotation + yellow Code/Category |
| files, dashboard, graphs | Sidebar — file groups | w-72 | "Files" + count + yellow Import |
| analyze | ReportsList — the six merged report screens + Tools group | w-72 | "Reports" + count + refresh |
| history, ai, settings | — (right-bar panes) | — | — |
| cases | CasesList | w-72 | "Cases" + count + refresh + yellow Add |
| notes | NotesList (type dropdown + per-type list) | w-72 | "Notes" + count + type dropdown + actions |

- Every left bar is a `LeftBar` (fixed header + `qc-scroll` body); **all left
  bars share the w-72 width**, and header buttons use the same heights as the
  center header (`Button` / `IconButton` — never `primaryCompact`/`sm`).
- Sidebar rows have a search field below the header (matches file names or
  code/category names; code search renders a flat match list).
- The Sidebar's file groups: group label `px-2 py-1 text-xs font-medium
  text-text-secondary`, rows `flex w-full items-center gap-1.5 rounded-sm
  px-2 py-1 text-left text-sm hover:bg-surface-higher` with a 14px type icon.
- Cases rows support the same right-click context menu as files/codes
  (Details / Rename / Delete).

## 9. Right bar

- Always present with an open project. The default panel is the **Inspector**.
- The top-bar buttons History / AI / Settings **toggle right-bar panes** (the
  center view keeps whatever it shows); clicking the active button closes the
  pane. Opening a file in the coder switches back to the Inspector.
- Pane structure: `LeftBar borderSide="l"` + `BarHeader`; AI is `width="lg"`
  with a Chat/Search tab toggle in the header; Settings is `width="lg"`
  with stacked `Card` sections; History is `width="lg"` with a filter bar
  (action/user selects) under the header and change cards with an undo icon.
- Inspector: compact header (`BarHeader`, h-10): item icon + name (or
  "Details") + close button.
- Empty state: "Select a code or file for details." (centered, secondary).
- Code details: highlight toggle ("Highlight in open file" — dims every other
  code's segments in the open coder via `.qc-highlight-filter`), memo editor
  (inline textarea + Save), color, category path, counts, recent examples.
- File details: type/date/owner, memo editor, "Open in coder".
- Editing a file memo from ANYWHERE opens the Inspector's inline editor
  (never window.prompt + toast).

## 10. Menu bar slot (currently: Graphs)

- Graphs menu bar: title "Graphs" + graph `<select>` + "New graph" +
  "Models" + (spacer) + Delete. The canvas is the center.

## 11. Status bar

`h-6`: project name (font-medium) · "N files · M codes" · spacer · app version.

## 12. States

- **Loading**: `LoadingState` — centered `LoaderCircle 16 animate-spin` + `text-text-secondary` label.
- **Empty**: `EmptyState` — centered icon 24 + `text-sm text-text-secondary` message.
- **Error banner** (in-view): `ErrorBanner` — `flex shrink-0 items-center gap-2 border-b
  border-danger bg-danger/10 px-3 py-1.5 text-sm text-danger` with a dismiss X;
  `tone="warning"` (`border-warning bg-warning/10 text-warning`) and
  `tone="success"` (`bg-surface text-success`) variants exist.
- **Modals/dialogs**: the `Modal` primitive — overlay `fixed inset-0 z-50
  flex items-center justify-center bg-bg/70`; panel `rounded-lg border
  border-border bg-surface shadow-xl`; header `border-b border-border
  px-3 py-2`. Escape and backdrop-click close it; busy forms pass
  `closeDisabled`.
- **Popover menus**: `Menu` — `absolute ... z-50 mt-1 rounded-md border
  border-border bg-surface py-1 shadow-lg`, items `MenuItem` — `flex w-full
  items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher`.
  Right-click context menus use `position="fixed"`.

## 13. Cross-cutting rules

- Text selection: UI chrome (ribbon, left/right bars, status bar, views
  without a selectable document) is `user-select: none` via CSS; the coder
  document uses `.qc-selectable`. NEVER set `user-select: none` on `body`.
- Every destructive action confirms via `window.confirm`; every rename/new
  name uses `window.prompt` (except memo editing, which uses inline editors).
- Right-click context menus: custom menus, never the browser menu
  (contextmenu is globally prevented).
- Layouts are never built ad hoc — use `WorkspaceLayout` and the registry in
  `ProjectShell`. New views must be added to the registry, not given their
  own bars.
- When a file opens in the coder, the Inspector shows its details
  automatically (`setView` handles this).
