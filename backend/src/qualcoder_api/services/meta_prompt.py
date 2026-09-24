"""Meta-analysis LLM helpers — prompt building, JSON extraction, truncation.

Prompt-building and token-budgeting logic is adapted from the reference
``Inoculation_Meta/meta/core/screening.py`` + ``llm.py``; the LLM transport
itself goes through QCnext's ``AiService`` (provider-agnostic OpenAI-compatible
endpoint) instead of a bespoke LM Studio/Gemini client.
"""

from __future__ import annotations

import hashlib
import json

from qualcoder_api.core.models import MetaCriterion
from qualcoder_api.services.meta_scheme import (
    all_fields,
    field_listing,
    normalise_codebook,
)


def extract_json(text: str | None):
    """Parse a JSON value from raw text, tolerating prose/code fences."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def truncate_for_context(text: str, max_chars: int) -> str:
    """Trim long text keeping the head and tail (for small local contexts)."""
    if not text or len(text) <= max_chars:
        return text
    head = max_chars * 3 // 4
    tail = max_chars - head
    return (
        text[:head]
        + f"\n\n[... {len(text) - head - tail} characters omitted ...]\n\n"
        + text[-tail:]
    )


def criteria_prompt_hash(criteria: list[MetaCriterion]) -> str:
    blob = json.dumps(
        [
            {
                "key": c.key,
                "label": c.label,
                "prompt_text": c.prompt_text,
                "kind": c.kind,
                "options": list(c.options or []),
                "pass_values": list(c.pass_values or []),
                "gating": c.gating,
            }
            for c in criteria
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def role_aware_field_listing(codebook: dict | None) -> str:
    """Field listing (with roles) for a codebook, v1 or v2."""
    book = normalise_codebook(codebook)
    return field_listing(all_fields(book), include_role=True)


def scheme_prompt_hash(scheme_name: str, coding_prompt: str, prescreen_prompt: str) -> str:
    blob = f"{scheme_name}\n{coding_prompt}\n{prescreen_prompt}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _criterion_instruction(criterion: MetaCriterion) -> str:
    """Kind-specific answer instruction for one criterion."""
    kind = (criterion.kind or "verdict").strip().lower()
    if kind == "classify":
        options = ", ".join(str(o) for o in (criterion.options or [])) or "(no options configured)"
        return f'choose exactly one of: {options}'
    if kind == "number":
        return "give a single numeric value"
    return '"Yes", "No", or "Unsure"'


def build_screening_system_prompt(criteria: list[MetaCriterion]) -> str:
    """System prompt for one screening cluster (all configured criteria)."""
    criterion_lines = "\n".join(
        f"{i + 1}. {c.label} ({_criterion_instruction(c)}): {c.prompt_text}"
        + (f" Help: {c.help}" if getattr(c, "help", "") else "")
        for i, c in enumerate(criteria)
    )
    verdict_keys = "\n".join(
        f'  - "criterion{i}_applies": {_criterion_instruction(c)}\n'
        f'  - "criterion{i}_certainty": "High", "Medium", or "Low"'
        for i, c in enumerate(criteria, start=1)
    )
    return f"""You are an expert research assistant screening studies for a meta-analysis.
Analyze each abstract against the inclusion criteria and respond with a single
JSON array only (no markdown, no commentary).

Inclusion Criteria:
{criterion_lines}

Each element of the array must correspond to one study and have these keys:
- "index": the study number given in the input
- For every criterion above (numbered 1..{len(criteria)}):
{verdict_keys}
- "intervention_type": a short label for the intervention studied, or "none"
- "intervention_type_certainty": "High", "Medium", or "Low"
- "comments": Brief reasoning (under 25 words).

Return exactly the same number of elements as the input, in the same order.
"""


def build_cluster_messages(
    items: list[tuple[int, dict]],
    criteria: list[MetaCriterion],
    max_context_chars: int = 24000,
    max_response_chars: int = 8000,
) -> list[dict]:
    """Build the message list screening a cluster of abstracts at once."""
    system_prompt = build_screening_system_prompt(criteria)
    margin = 1200
    usable_input = max(2000, max_context_chars - len(system_prompt) - max_response_chars - margin)
    per_abstract_chars = max(300, usable_input // max(1, len(items)))

    def truncate(text: str, budget: int) -> str:
        if not text or len(text) <= budget:
            return text
        cut = budget - 200
        return text[:cut] + f"\n[... truncated, {len(text) - cut} chars omitted ...]"

    parts = []
    for i, row in items:
        parts.append(
            f"""Study {i}:
- Title: {truncate(str(row.get("title") or ""), per_abstract_chars)}
- Authors: {truncate(str(row.get("authors") or ""), 500)}
- Abstract: {truncate(str(row.get("abstract") or ""), per_abstract_chars)}
- DOI: {row.get("doi") or ""}"""
        )
    user_prompt = "Screen the following studies and return the JSON array.\n\n" + "\n\n".join(parts)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_prescreen_messages(prescreen_prompt: str, paper_text: str, title: str = "") -> list[dict]:
    """Build the message list for the scheme's prescreen prompt.

    The configured ``prescreen_prompt`` is embedded in the user content (it
    carries the scheme-specific screening instructions), followed by the paper
    text so the model can actually apply them.
    """
    header = f"Paper: {title}\n\n" if title else ""
    instructions = (prescreen_prompt or "").strip() or (
        "Apply the study's inclusion criteria and report a JSON object with a "
        '"rationale" and one boolean flag per criterion.'
    )
    content = (
        "Read the paper below and apply the screening instructions.\n\n"
        f"Screening instructions:\n{instructions}\n\n"
        f"Paper:\n{header}{paper_text}"
    )
    return [{"role": "user", "content": content}]


def build_extraction_messages(coding_prompt: str, paper_text: str, title: str = "") -> list[dict]:
    """Build the message list for the scheme's full coding prompt.

    The configured ``coding_prompt`` becomes the system message so every field
    and coding rule configured by the scheme reaches the model; the user message
    carries only the paper.
    """
    header = f"Paper: {title}\n\n" if title else ""
    system = (coding_prompt or "").strip() or (
        "You are an expert research assistant extracting data for a "
        "meta-analysis. Return only the requested JSON."
    )
    content = f"Read the paper below and apply the coding scheme.\n\n{header}{paper_text}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]
