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
[Dashboard] [Files] [Cases] [Notes] [Reports] [Graphs] │ [search box]
[Coder switcher: User + name + sync-dot + ▾] [queue chip?] [History]
[AI] [Settings]
```

- Nav buttons: `icon 20 + label text-xs font-medium`, active =
  `bg-surface-higher text-accent`, idle = `text-text-secondary`.
- Divider after nav: `h-5 w-px bg-border`.
- Search: a NATIVE text box in the ribbon (`h-7 w-48`, search icon at the
  left inside the input). The query is treated as a regular expression (an
  unescaped `*` is a wildcard — `LM*` = "LM" + anything; `\*` stays literal);
  the rest of the search UI opens as a FLYOUT **centered in the window**
  (`w-[44rem] max-w-[94vw]`, under the input vertically) on focus: mode toggle
  Exact/Semantic, entity-scope chips (all on one line), semantic index
  controls, live results with the matched span highlighted. No separate search
  button. When the query is non-empty an **X** appears at the right edge of the
  input to clear it (`aria-label` "Clear search", i18n `search.clear`); there
  is NO header/title bar inside the flyout — the query stays in the ribbon
  input.
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
| files, dashboard, graphs | Sidebar — file groups | w-72 | "Files" + count + yellow **URL** button (opens the URL-import dialog) + yellow Import |
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
- Pane structure: `LeftBar borderSide="l"` + `BarHeader`; **AI** is
  `width="lg"` (w-96) with `scroll={false}` and hosts the chat in its body;
  **Settings** is `width="lg"` with stacked `Card` sections; **History** is
  `width="lg"` with a filter bar (action/user selects) under the header and
  change cards with an undo icon. The Help pane (`scroll={false}` — only its
  content area scrolls, never over the mode/search bars) and Settings carry
  the bug-report button in their `BarHeader` actions; the Help doc search is
  regex-native (no toggle).
- Inspector: compact header (`BarHeader`, h-10): item icon + name (or
  "Details") + close button.
- Empty state: "Select a code or file for details." (centered, secondary).
- Code details: highlight toggle ("Highlight in open file" — dims every other
  code's segments in the open coder via `.qc-highlight-filter`), memo editor
  (inline textarea + Save), color, category path, counts, recent examples.
- File details: type/date/owner, memo editor, "Open in coder".
- Editing a file memo from ANYWHERE opens the Inspector's inline editor
  (never window.prompt + toast).

### AI pane (AiView / AiChatPanel)

`AiView` is a `LeftBar borderSide="l" width="lg" scroll={false}` — only the
chat body scrolls, never the header:

- **Header** (custom `cls.bar` row, h-10, outside the scroll area): the "AI"
  title + the instruction-template `<select>` (`min-w-0 flex-1` — it fills the
  bar, leaving minimal gap to the "AI" heading; groups Analysis / Specialized
  / My templates) + three ghost `IconButton size="sm"`: **History**
  (Hourglass → anchored popover with "New chat" and the saved sessions, each
  with hover-revealed inline rename/delete like the file/code rows),
  **Templates** (FileText → the template editor modal, which also edits the
  wrapping prompt), **Help** (HelpCircle → `HelpFlyout`).
- **Messages** (`.qc-scroll` body, max-w-2xl column): user bubbles right
  (`bg-accent text-[var(--qc-bg)]`), assistant bubbles left (`bg-surface`
  with an "AI assistant" label), errors left with `border-danger
  bg-danger/10 text-danger`. A "Thinking…" spinner bubble shows while a
  request runs. **Assistant replies render as Markdown** (headings, lists,
  tables, fenced/inline code, bold/italic; links and images become plain
  text — no raw HTML) via the shared `Markdown` component (`size="sm"`), the
  same renderer the Help pane uses.
- **Tool bubbles** (agentic chat): each executed MCP tool renders inside the
  assistant bubble under a `Tools used` label as a bordered row
  (`rounded-sm border border-border bg-bg px-2 py-1 text-xs`) with a Wrench
  icon + human summary + an `Approved` (Check, `text-success`) or `Rejected`
  (X, `text-danger`) tag — only for write tools that went through an explicit
  approve/reject decision; read tools executed without a gate carry no tag.
- **Pending approval** (agentic + Confirm writes): a panel above the
  composer lists the proposed write tools (Wrench + summary each) with
  `Approve` (primary, Check) and `Reject` (secondary, X) buttons.
- **Data selector (collapsible)**: the context strip above the composer has a
  header row — `MODE: <label>` with a `ChevronDown`/`ChevronRight` arrow
  (`px-3 py-1.5`, `aria-expanded`) that collapses/expands the pickers below.
  When expanded, the `ContextPickerArea` shows the `All | Memos | Codes |
  Files` tab row plus the active picker. **All** is a toggle (`aria-pressed`)
  that selects/clears every memos, code and file key at once; it is **on by
  default**, so all project data is exposed unless the user narrows it.
- **Composer**: a small option row above the textarea holds two checkboxes —
  `Tools` (enable agentic chat) and `Confirm writes` — plus a right-aligned
  MCP access `<select>` (`h-6 rounded-sm border border-border bg-bg px-1
  text-[11px]`, options Read only / Read + write / Full access) that persists
  via `PUT /ai/mcp-permissions` (the same setting as in Settings). Below it
  the textarea + Send + (Clear, on a fresh chat only).
- **Template editor** (Templates icon → modal): two tabs.
  - **Personas** — every chat mode's system prompt as a textarea row with
    `Save` + `Reset to default` (Restores the shipped text); saved app-wide
    via `PUT /ai/personas`. The machine-wide **wrapping prompt** ("be short
    and concise" by default) sits below, with its own Save + reset.
  - **Templates** — the full editable catalog from `GET /ai/templates/all`,
    grouped by Built-in / App / My templates: built-ins are edited via an
    app-wide override (`PUT /ai/templates/all`, scope badge "Built-in",
    `Reset to default` clears it), app templates are stored in the user
    settings and usable in every project, project templates are the
    project's `ai_prompt` rows with a `Save globally` (Globe) action that
    copies them into the app store. New-template buttons create a project
    (`Plus`) or app-wide (`Globe`) template.

### Help pane

The Help pane (`scroll={false}`, right bar) has two tabs: **Browse** — the
in-app `help_docs/*.md` topics served by the backend (topic list + rendered
markdown) with a regex-native search box whose **matched span is highlighted**
in the result snippets (`bg-accent/30`, same as the search flyout) and an **X**
to clear the search when non-empty (same as the ribbon search input) — and
**Ask AI** — a single-turn "help"-mode chat (needs an open project with AI
enabled). The bug-report button sits in the `BarHeader`.

## 10. Function bars per view

- Function bars always render as the **first row of the center view** (`h-10
  border-b border-border bg-surface px-3`) — a bar must never span the side
  bars. The orchestrator's `menuBar` slot exists but is intentionally unused
  by the current views.
- Graphs menu bar (first row of the center): title "Graphs" + graph `<select>`
  + "New graph" + (spacer) + "Models" + zoom controls + connect. The canvas is
  the rest of the center.

## 10a. Memo gutter (Word-style sidebar)

The memo gutter is a **separate reusable module** (`MemoGutter.tsx`) integrated
into TextCoder, HtmlCoder, AvCoder, PdfCoder, and ImageCoder. It provides a
Word-style sidebar for viewing and editing memo cards aligned to coded segments.

The details bubble rendered when the gutter is hidden (`MemoGutterBubble`)
carries `data-gutter` — every host's document-level click-away handler must
keep excluding `[data-gutter]` so clicks inside the bubble never dismiss it.

### Layout & behavior

- **Toggle**: Show/hide via a "Memos" button in each coder's header. Uses
  `useGutterVisible()` from `viewOptions.ts` (persisted in localStorage).
- **Gutter width**: `w-56` (14rem), positioned in the right margin of the
  scroll container.
- **Cards**: Each coded segment with a memo or weight > 0 renders a card in
  the gutter. Cards are stacked vertically, aligned to their anchor spans.
- **Stacking**: Up to `MAX_STACK=3` cards can share a vertical position.
  Overflow collapses into a "+N more" chip that expands on click.
- **Collapsed card**: `h-10` (40px) — shows a colored dot, code name, memo
  preview, and weight chip (if weight > 0).
- **Expanded card**: `h-32` (132px) — shows header + weight steppers + memo
  textarea + delete button + extras slot.
- **Selection**: Click a card to expand it. Click again or press Escape to
  collapse. When the gutter is hidden, selecting a segment opens a floating
  bubble instead.

### Module structure

```
MemoGutter.tsx
├── GutterRow (interface) — normalized coding data
├── hasGutterData() — determines if a card should render
├── toGutterRow() — builds GutterRow from coding objects
├── MemoGutter — the sidebar component
├── MemoGutterBubble — floating editor when gutter is hidden
└── SegmentMemoEditor — shared card component
```

### Shared coder hooks (`features/coding/shared/`)

All coders are built on ONE set of shared modules — never re-implement these
per coder:

- `useSegmentActions({kind, rows, idOf, deleteRow, refresh, onError})` — the
  memo/weight/important/delete quadruplet + undo stack. Deletes confirm AND
  push onto the undo stack; every coder header renders "Unmark last" from it.
- `events.ts` — `useCodingsChanged(handler)` and `useAssignCode(handler)`
  subscriptions to the shell/sidebar broadcasts (latest-closure safe).
- `useEscapeStack(layers)` — layered Escape dismissal; closers return whether
  they consumed the key, ordered topmost-popover first.
- `useSplitResize({axis, min, max, initial, containerSize})` — split-pane
  drag with clamping (text-pane width in Pdf/Html, video height in Av).
- `useGutterRows({rows, kind, idOf, codeById, fallbackName})` — codings →
  gutter-row mapping.
- `toolbarAnchor.ts` — `clampToolbarAnchor` + `useToolbarDismiss` for the
  floating selection toolbar.
- `WeightStepper` — the Minus/value/Plus weight control (0–100, step 10).

### Integration per coder

| Coder | Anchor resolution | Notes |
|---|---|---|
| TextCoder | `[data-ctids~="ctid"]` on spans | Multi-coding support via space-separated IDs |
| HtmlCoder | iframe/doc `[data-ctids~="ctid"]` | Queries both iframe and plain text pane |
| AvCoder | transcript `[data-ctid="ctid"]` | Only transcript codings (timeline codings excluded) |
| PdfCoder | `[data-ctid="imid"/"ctid"]` | Combined image + text codings |
| ImageCoder | `[data-imid="imid"]` | PENDING: new gutter integration |

### Layout solver

`memoLayout.ts` provides pure functions:
- `layoutGutterCards()` — positions cards vertically, pushing down for collisions
- `stackRows()` — groups co-located rows (tolerance 2px)

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

## 13. Motion & interaction (implemented system)

Defined once in `index.css` (consuming the `tokens.json` motion tokens) and in the
orchestrator. Every new screen inherits these automatically — never add a
per-file transition/animation class.

| Rule | Implementation |
|---|---|
| Motion tokens | `--qc-motion-fast: 150ms`, `--qc-motion-base: 250ms`, `--qc-ease: cubic-bezier(0.16, 1, 0.3, 1)` (light/dark aware via the token block) |
| Shared transition layer | `.qc-motion` — transitions background-color / border-color / color / box-shadow / transform at fast + ease. Applied by `Button`, `IconButton`, `Input`/`Select`/`Textarea`, `MenuItem`, `Card` |
| Modal entry | `.qc-modal-backdrop` = fade-in 150ms; `.qc-modal-panel` = pop (fade + `translateY(6px) scale(0.985)`) 250ms |
| Menu / popover entry | `.qc-popover` = rise (fade + `translateY(4px)`) 150ms |
| Toast entry/exit | `.qc-toast` = slide-in from right 150ms; `.qc-toast-out` = fade-out 150ms |
| Hover / press | `.qc-btn-lift:hover:not(:disabled)` → `translateY(-1px)`; `.qc-btn-primary:active:not(:disabled)` → `scale(0.98)`; `.qc-card:hover` → `translateY(-1px)`. **Hover lifts are 1px, never more** |
| Focus ring | Global `:focus-visible { outline: 2px solid var(--qc-accent); outline-offset: 1px }`; form fields use `.qc-field:focus` instead — `outline: none`, `border-color: var(--qc-accent)`, plus a 2px `box-shadow` ring (`color-mix(in srgb, var(--qc-accent) 30%, transparent)`) |
| `Toggle` primitive | Orchestrator `Toggle`: `role="switch"` + `aria-checked`, track `h-4 w-8 rounded-full` (`bg-accent` when on / `bg-border` off), knob `h-3 w-3 rounded-full bg-white` at `left: 2`/`18`, `transition-colors`/`transition-all`. Optional label + hint. **The only switch component — never hand-roll a switch** |
| Reduced motion | `.a11y-reduced-motion` kills all animation/transition (a11y mode); `@media (prefers-reduced-motion: reduce)` also neutralizes them (0.01ms durations). Motion is opacity/transform/color only — nothing that shifts layout |
| Colorblind / high-contrast | `.a11y-colorblind` never lets accent carry information alone (underline + inset accent bar); `.a11y-high-contrast` outlines switches/segments |

Rule: micro-interactions are **subtle and non-intrusive** — no springs, no
staggered list reveals, no colored glow shadows. The `Card` component carries
the hover lift automatically.

Remaining UI-consistency sweep work is tracked in the CHANGELOG: the ad-hoc
`h-6`/`h-7` toolbar clusters and a `cls.toolbarBtn` token are not yet done.

## 14. Cross-cutting rules

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
- Choosing a **code occasion** (clicking a coded segment in any coder —
  text/PDF/HTML/Image/AV) also selects the code in the right-bar Inspector
  (`useInspectorStore.selectCode(cid)`), in addition to the bottom details bar.
