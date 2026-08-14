# AI Chat — Should memo / text / code analysis stay separate? (Assessment)

**Question:** the AI chat currently separates three analysis modes (memo analysis, text
analysis, code analysis), each with its own context picker and prompt catalog. Does this
separation make sense, or should they be merged/re-organized?

## 1. What the separation looks like today (from the code)

| Mode | Context shared | Prompt catalog (examples) | Context budget |
|---|---|---|---|
| `memo_analysis` | memos (multi-select; file + code memos) | `memo-analysis/_init` (theory building) | memos capped at 2000 chars each |
| `code_analysis` | codes (multi-select; name, category path, memo, coding count, 2 example coded areas) | code-critic, code-summary, code-comparison, analyze-differences, theoretical-saturation-check | 30 codes / ~5000 chars total |
| `text_analysis` | files (multi-select; fulltext) | Friese-2024 themes, SRP reconstruction, brainstorm, paraphrase-and-summarize, analyze-the-unexpected | ~6000 chars per source / 12000 total |
| `topic_exploration` | ALL three pickers (union) | topic-summary, analyze-differences/unexpected | 12000 chars total |
| `search` | all three pickers (source filter for the index) | focused/open/content-analysis prompts | index-based |
| `general` / `help` | project summary only | paraphrase, sentiment quick actions | ~3000 chars |

The chat thread is per-panel (one history), the modes drive BOTH the context injection
(`ai_service` per-mode context builders) AND the prompt library shown in the dropdown.

## 2. Why the separation makes sense (arguments FOR)

1. **Context budget stays healthy.** Mixing all three kinds into every chat would blow the
   token budget (the union already hits a 12000-char cap) and dilute the signal: a code
   review needs counts + example segments, not 12 documents of raw text; memo work needs
   reflective notes, not the data they annotate. Separation keeps each call focused →
   better answers, fewer hallucinations, lower cost.
2. **Method-specific prompts.** The catalogs are genuinely method-specific: Friese-2024
   theme generation and SRP reconstruction operate on *text*; the code critic and
   saturation check operate on *codes*; memo analysis targets theory-building across
   memos. A merged mode would force one system prompt over three distinct method families.
3. **It mirrors the research workflow.** QDA moves through phases — data → coding → memos →
   theory. The modes map 1:1 onto that pipeline, so the user's intent is expressed by the
   mode choice itself; the per-mode picker then shows only the relevant entity type
   (reduced cognitive load).
4. **MAXQDA does the same.** AI Assist separates "chat with documents/segments" from
   "chat with memos" (added as a distinct flow in 26.3 with its own memo selection), and
   keeps AI suggestions for coded segments / subcodes separate from paraphrase/summary
   actions. The separation is an industry-validated pattern, not an accident.

## 3. Costs and risks of the separation (arguments AGAINST)

1. **Fragmentation of the analysis chat.** A question spanning data + codes ("what does
   the project say about X, and where is it coded?") has no natural home except
   `topic_exploration`, whose 12000-char union cap degrades when all three pickers are
   loaded. Users must either rephrase into mode-shaped questions or lose context.
2. **The memo/text/code boundary is fuzzy in practice.** Memos are text; code memos are
   text attached to codes; "text analysis" of a coded document and "code analysis" of its
   segments view the same content. First-time users may not know which mode their question
   belongs to.
3. **Dropdown weight.** Seven entries (general, help, topic, code, text, memo, search) is
   a lot of surface; without labels/help, the modes feel like an API, not a tool.
4. **Maintenance surface.** Three context builders + three catalogs + three pickers;
   every future context type (attributes? cases? transcripts?) raises the question of yet
   another mode.

## 4. Options

| Option | What changes | Verdict |
|---|---|---|
| **A. Keep, with polish** (recommended) | Modes stay; analysis modes gain the ABILITY to add other context kinds (memos into code analysis, codes into text analysis, etc. — the pickers become additive, as topic_exploration already is); ONE shared chat thread across modes; clearer labels + a one-line help ("data ↔ codes ↔ memos = the research pipeline"). | Best fit: keeps method prompts + budgets, fixes fragmentation, minimal risk |
| **B. Collapse to two** | "Analysis" (text + codes, both pickers) and "Theory" (memos + topic), search separate; the method prompts move from the mode into the prompt dropdown (already exists). | Viable simplification, but blurs the budget story (analysis mixes texts AND codes) and buries the method catalog one level deeper |
| **C. Collapse to one + search** | Single chat with all pickers; mode = prompt choice only. | Simplest UI, but default context becomes ambiguous (what to inject with no mode?) and the 12000-char cap is strained; method-tailored system prompts weaken |
| **D. Merge memo into text** | memo_analysis becomes a picker kind inside text analysis (memos are text); code analysis stays separate. | Tempting, but memo analysis has its own *theory-building* prompt family and MAXQDA treats it as distinct; merging loses that focus |

## 5. Recommendation

**Keep the separation (Option A).** The three analysis modes earn their place: they map to
real QDA phases, keep context budgets healthy, and carry distinct method prompt families —
the same shape MAXQDA's AI Assist converged on. The genuine weakness is fragmentation, and
it is fixable without merging:

1. **Additive pickers in every analysis mode** — the user can attach memos to a code
   review or codes to a text analysis; the backend already supports arbitrary
   `memo_ids`/`code_ids`/`source_ids` in the union path, so this is mostly a UI change
   (show all three picker tabs in every mode, with the mode-relevant one expanded).
2. **One shared thread across modes** — the history survives mode switches (context is a
   request property, not a thread property).
3. **Labels + help** — e.g. "Texts (data)", "Codes (coding system)", "Memos (theory)",
   plus the one-line pipeline hint, so the seven entries feel like a workflow, not an API.

If a future simplification is ever wanted, Option B (collapse text+codes, keep memos +
topic + search) is the least-damaging fallback — it preserves the memo/theory focus and
the search identity while halving the dropdown.

## 6. Not recommended

- Merging memos into text analysis (D): the memo prompt family (theory building) and its
  MAXQDA precedent argue for keeping memos distinct.
- Full single-mode collapse (C): default-context ambiguity + budget strain outweigh the UI
  win.
