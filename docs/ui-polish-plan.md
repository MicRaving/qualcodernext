# UI Consistency & Motion Polish — Plan (for review)

Based on: (a) a full audit of the QCnext frontend, (b) a design-pattern extraction from the
critcomp project (`D:\critcomp\editor`). Nothing below is implemented yet.

## Goals & principles

1. **Standardize** buttons, text boxes, toggles, icons — one size per job, enforced by
   tokens/primitives, not per-file classes.
2. **Non-intrusive motion**: short (120–200 ms), opacity+transform only, no bounce/springs,
   always disabled under reduced-motion (the existing `.a11y-reduced-motion` guard already
   neutralizes everything; we add a `prefers-reduced-motion` media query as well).
3. **Borrow from critcomp** only the concrete, reusable patterns (below) — no redesign of
   the palette, no new font, no framer-motion (CSS-only keeps the bundle light).
4. Every change passes `tsc`, `eslint`, `vitest` and keeps the e2e suite green.

## What we borrow from critcomp (concrete values)

| critcomp pattern | Value | Applied to QCnext as |
|---|---|---|
| Transition speed/easing | 150 ms, `cubic-bezier(0.16,1,0.3,1)` | matches the existing `motion.fast`/`motion.base` tokens in `tokens.json` (currently unused) — we finally consume them |
| Button hover/active | hover `translateY(-1px)`, active `scale(0.98)`, 150 ms | `cls.primary/secondary/danger` + cards; subtle, 1 px max |
| Modal entry | backdrop fade 150 ms + panel `translateY(6px) scale(0.985)` 250 ms | the orchestrator `Modal` |
| Focus ring | `0 0 0 2px rgba(accent, 0.15)` | all buttons + inputs `:focus-visible` |
| Input focus | border→accent + 2px ring, 150 ms | `cls.input/select/textarea` |
| Elevation (3 levels) | raised / overlay / modal shadows | new `--qc-shadow-sm/md/lg`; standardize the current ad-hoc `shadow`/`shadow-lg`/`shadow-xl` on popups/modal/toast |
| Status chips/pills | 10 px, 600, tinted bg + colored border | standardize the existing ad-hoc badges |
| Empty states | centered muted icon + message | adopt via the existing `EmptyState` component |
| Micro-interaction scope rule | "hover lifts are 1 px, never more" | adopted as a guideline |
| **Not borrowed** | Manrope font, staggered list reveals, springs, colored glow shadows, live-quiz fireworks | out of scope (research app) |

## QCnext audit summary (what's inconsistent today)

- **Buttons**: shared `cls.*`/`Button` used 500+ times (good skeleton), but ~75 ad-hoc size
  overrides: `h-6` (~25), `h-7` (~17), `h-8 w-8` send buttons, `px-3! py-1.5! text-sm!`
  hero buttons, raw icon buttons re-implementing `ghostSmall` (~14). Clusters: analyze report
  toolbars, coder toolbars (4 different heights for the same role), AI panel, Inspector.
- **Text boxes**: `cls.input` is standardized, but 26 raw inputs + 7 textareas + 3 raw
  selects clone it with drift (search fields in Notes/Cases, `bg-surface` vs `bg-bg`,
  `text-sm` vs `text-xs`, h-6 variants, 5 different textarea paddings).
- **Toggles**: 5 hand-rolled switches in 2 sizes — no `Switch` primitive.
- **Icons**: ~42 off-spec sizes (9/10/11/15/18/22) clustered in Inspector, CoderSwitcher,
  RConsole, upstreamReports, Dashboard.
- **Animations**: ~98 % animation-free. The `motion.*` tokens exist but are consumed nowhere.
  Only spinners + the segment flash + switch transitions exist. Modals/menus/toasts pop
  instantly.
- **Shadows/radius/focus**: shadows ad-hoc (toast `shadow` vs popup `shadow-lg`); one
  `rounded-full` button violates the radius rule; focus rings inconsistent on raw inputs.

## Implementation plan (phases)

### Phase A — Foundations (tokens + primitives + global motion) — ~2 agents
1. `lib/tokens.ts` + `index.css`:
   - consume `motion.fast/base` (150/250 ms) + the existing easing for a global set of
     transitions; add the `prefers-reduced-motion` media guard alongside `.a11y-reduced-motion`.
   - add `--qc-shadow-sm/md/lg` (critcomp elevations, light/dark aware).
   - standard `:focus-visible` ring on buttons + inputs (2 px accent-translucent).
2. `components/ui/orchestrator.tsx` + `tokens.ts`:
   - new `Switch` primitive (single size, `role=switch`, accent track, motion.fast).
   - new `cls.toolbarBtn` (compact, one size) replacing the `h-6`/`h-7` hodgepodge in
     toolbars; standard `IconButton` sizes (sm 20 / md 26 / lg 28 px).
   - textarea default padding token (`cls.textarea` gains `p-1.5`).
   - `Button`/`IconButton`/`Input`/`Select`/`Textarea`/`Modal`/`Menu`/`ToastCard` gain the
     transitions + entry animations (modal fade+pop, menu fade+4 px rise, toast slide-in,
     all 120–200 ms).
3. Adopt the `Card` component (exported but unused; 3 hand-rolled copies) with the
   critcomp-style hover lift.

### Phase B — Consistency sweep (~75 sites, ~2–3 agents by cluster)
1. **Analyze report toolbars** (`merged.tsx`, `StatsReport`, `SummaryTableReport`,
   `RConsole`, `PublishDialog`, `SentimentReport`, `DictionaryReport`, `upstreamReports`,
   `SqlReport`): all compact buttons → `cls.toolbarBtn`/`primaryCompact`; icon sizes →
   token sizes; raw icon buttons → `IconButton`.
2. **Coder toolbars** (`TextCoder`, `PdfCoder`, `HtmlCoder`, `AvCoder`, `ImageCoder`): one
   toolbar height everywhere (the token compact size); transport buttons → `IconButton md`.
3. **AI panel** (`AiChatPanel`, `AiView`): send button → `Button primary` at token size;
   quick-action chips → `rounded-sm` per radius rule; `text-[11px]` → token sizes; memo
   picker controls aligned.
4. **Inspector + Notes/Cases/Journal forms**: raw search inputs → `Input` (keeping the
   search-icon wrapper); raw selects → `Select`; the hand-rolled danger delete → `Button
   danger w-full`; `bg-surface` → `bg-bg` drift fixed.
5. **Toggles**: the 5 hand-rolled switches → the new `Switch` primitive (Settings,
   CoderSwitcher).
6. **Icons**: the ~42 off-spec sizes → the DESIGN.md size map (12/13/14/16/20/24).

### Phase C — critcomp-style micro-interactions (light touch, ~1 agent)
- Hover lift (`translateY(-1px)`, 150 ms) on `Button` variants + cards; active
  `scale(0.98)` on primary.
- Status chips/pills standardized (tinted bg + colored border, 10 px label).
- Empty states via `EmptyState` everywhere they're hand-rolled.
- Verify the a11y modes still fully neutralize motion.

### Verification (after each phase)
- `npx tsc --noEmit -p tsconfig.json`, `npx eslint src --max-warnings 0`,
  `npx vitest run`, and the e2e suite (`npx playwright test`, 42 tests) — animations must
  not break selectors (they're all opacity/transform, no layout shift).

## Explicitly out of scope
- No palette change, no font change (critcomp's Manrope stays out), no framer-motion,
  no staggered/spring animations, no shadows on buttons/cards beyond the 3-level elevation,
  no layout changes.

## Open questions for you
1. **Hover lift**: OK to add the 1 px lift + `scale(0.98)` active on buttons/cards (matches
   critcomp), or keep hover purely color-based?
2. **Elevation shadows**: adopt the 3-level shadow system (slightly deeper modal shadow,
   subtle popup shadows) — visual change, or keep the current flat shadows?
3. **Scope of the first iteration**: run all three phases in one pass, or Phase A
   (foundations) first so you can feel the motion/tokens before the sweep?
4. **Animated panel transitions**: on view switches (e.g. ribbon navigation), add a subtle
   120 ms content fade — yes or no? (critcomp does this; it's the one "wow" bit we'd borrow.)
