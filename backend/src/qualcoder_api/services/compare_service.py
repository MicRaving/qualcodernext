"""Document comparison chart — MAXQDA-style code-sequence alignment.

Sequence semantics
------------------
Each document's coded text is reduced to a *code-id sequence*: its text
codings are sorted by start position and every coding contributes its code
id. When several codings overlap in one region, the overlapping codings
form a *run* (a connected component of the overlap graph — coding B joins
the run when it overlaps any member of it, directly or through a chain);
only the FIRST code of the run is kept — the one whose segment starts
earliest (ties broken by end position, then row id) — so that one passage
maps to exactly one sequence position and the sequences stay tractable.

This is a deliberate simplification, chosen for two reasons:

* A passage coded with A and B would otherwise contribute two symbols
  ("A", "B") whose relative order is arbitrary, inflating the sequence
  with near-duplicate symbols and making the LCS degenerate (it could
  align the same physical passage twice).
* The alignment chart shows each passage once, as the code that "owns" its
  start; the per-code co-occurrence counters still reflect how often each
  code appears.

Similarity
----------
* ``dice`` — Dice coefficient over the code SETS of the two documents:
  ``2*|A∩B| / (|A|+|B|)``. Answers "how much of the codebook vocabulary
  is shared".
* ``sequence`` — sequence-alignment ratio ``2*LCS / (n1+n2)`` over the
  ordered code-id sequences. Answers "how much of the ordered coding
  structure is shared".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

from qualcoder_api.core.models import Code, Coding

# The LCS traceback keeps a byte-per-cell choice matrix; past this many
# cells the trace is dropped (all positions report unaligned) and only the
# length is computed with a two-row DP. 20M cells ≈ 20 MB — documents with
# thousands of codings each still trace fine; only pathological projects
# degrade (to length-only similarity).
_MAX_TRACE_CELLS = 20_000_000


def code_sequence(codings: Iterable[Coding]) -> list[Coding]:
    """Code-id sequence of a document (see the module docstring).

    Returns the *kept* codings in position order; the sequence symbols are
    their ``cid`` values.
    """
    ordered = sorted(codings, key=lambda c: (c.pos0, c.pos1, c.ctid))
    sequence: list[Coding] = []
    run_end = -1
    for coding in ordered:
        if coding.pos0 < run_end:
            # Inside the current overlapping run — only the first code of
            # the run contributes to the sequence. Skipped codings still
            # extend the run's reach, so the run is the connected component
            # of the overlap graph, not just the overlap with the kept one.
            run_end = max(run_end, coding.pos1)
            continue
        sequence.append(coding)
        run_end = max(run_end, coding.pos1)
    return sequence


def lcs_length(a: list[int], b: list[int]) -> int:
    """Length of the longest common subsequence — O(n*m) DP, two rows."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0
    prev = [0] * (m + 1)
    for x in a:
        cur = [0] * (m + 1)
        for j, y in enumerate(b, start=1):
            if x == y:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = prev[j] if prev[j] >= cur[j - 1] else cur[j - 1]
        prev = cur
    return prev[m]


def lcs_pairs(a: list[int], b: list[int]) -> list[tuple[int, int]]:
    """Indices of one LCS in ``a``/``b``, ordered by position.

    O(n*m) DP whose traceback walks a byte-array choice matrix (1 byte per
    cell). Returns ``[]`` for empty sequences or when the matrix would
    exceed ``_MAX_TRACE_CELLS`` cells (callers fall back to
    ``lcs_length``).
    """
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return []
    if n * m > _MAX_TRACE_CELLS:
        return []
    prev = [0] * (m + 1)
    choices: list[bytearray] = []
    for x in a:
        cur = [0] * (m + 1)
        row = bytearray(m + 1)
        for j, y in enumerate(b, start=1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                row[j] = 1  # diagonal: match (a[i-1], b[j-1])
            elif prev[j] >= cur[j - 1]:
                cur[j] = prev[j]
                row[j] = 2  # up: drop a[i-1]
            else:
                cur[j] = cur[j - 1]
                row[j] = 3  # left: drop b[j-1]
        choices.append(row)
        prev = cur
    pairs: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 and j > 0:
        step = choices[i - 1][j]
        if step == 1:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif step == 2:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def align(
    a: Sequence[object], b: Sequence[object], pairs: list[tuple[int, int]]
) -> list[tuple[int | None, int | None]]:
    """Expand the LCS pairs into full alignment rows.

    Each row is ``(a_index, b_index)``; ``None`` marks a gap on that side,
    so a position with a match never waits for unaligned runs — the
    alignment "shifts" unmatched runs of one document into the gaps of the
    other. Rows where both indices are set are the aligned (matched)
    positions; concatenating the non-None sides reproduces ``a`` and ``b``
    in order.
    """
    rows: list[tuple[int | None, int | None]] = []
    ia = ib = 0
    for ma, mb in pairs:
        while ia < ma:
            rows.append((ia, None))
            ia += 1
        while ib < mb:
            rows.append((None, ib))
            ib += 1
        rows.append((ma, mb))
        ia, ib = ma + 1, mb + 1
    while ia < len(a):
        rows.append((ia, None))
        ia += 1
    while ib < len(b):
        rows.append((None, ib))
        ib += 1
    return rows


def dice_coefficient(a: Iterable[int], b: Iterable[int]) -> float:
    """Dice coefficient over two code-id SETS: 2*|A∩B| / (|A|+|B|)."""
    set_a = set(a)
    set_b = set(b)
    denom = len(set_a) + len(set_b)
    if denom == 0:
        return 0.0
    return 2.0 * len(set_a & set_b) / denom


def _position(coding: Coding, codes: dict[int, Code], aligned: bool) -> dict:
    """One sequence position as the API shape {code_name, color, ...}."""
    code = codes.get(coding.cid)
    return {
        "ctid": coding.ctid,
        "cid": coding.cid,
        "code_name": code.name if code else "",
        "color": code.color if code else "#ffffff",
        "pos0": coding.pos0,
        "pos1": coding.pos1,
        "seltext": coding.seltext,
        "aligned": aligned,
    }


def compare_documents(
    codings1: list[Coding],
    codings2: list[Coding],
    codes: dict[int, Code],
) -> dict:
    """Full comparison payload for two documents' text codings.

    ``codes`` maps cid → Code (only the codes used by either document need
    to be present; unknown cids fall back to empty name / white color).
    Returns ``seq1``/``seq2`` (per-position dicts), the alignment ``rows``
    (``{a, b, aligned}`` with ``None`` gaps), ``similarity`` (dice +
    sequence ratio + lcs/n1/n2) and per-code ``cooccurrence`` counters.
    """
    seq1 = code_sequence(codings1)
    seq2 = code_sequence(codings2)
    ids1 = [c.cid for c in seq1]
    ids2 = [c.cid for c in seq2]
    n1, n2 = len(ids1), len(ids2)

    pairs = lcs_pairs(ids1, ids2)
    if pairs:
        lcs = len(pairs)
        matched_a = {i for i, _ in pairs}
        matched_b = {j for _, j in pairs}
    else:
        lcs = lcs_length(ids1, ids2)
        matched_a = set()
        matched_b = set()

    seq1_out = [
        _position(c, codes, i in matched_a) for i, c in enumerate(seq1)
    ]
    seq2_out = [
        _position(c, codes, j in matched_b) for j, c in enumerate(seq2)
    ]
    rows = [
        {
            "a": _position(seq1[ia], codes, True) if ia is not None else None,
            "b": _position(seq2[ib], codes, True) if ib is not None else None,
            "aligned": ia is not None and ib is not None,
        }
        for ia, ib in align(ids1, ids2, pairs)
    ]

    count1 = Counter(ids1)
    count2 = Counter(ids2)
    matched_count = Counter(ids1[i] for i, _ in pairs)
    cids = sorted(set(ids1) | set(ids2))
    cooccurrence = [
        {
            "cid": cid,
            "name": codes[cid].name if cid in codes else "",
            "color": codes[cid].color if cid in codes else "#ffffff",
            "count1": count1.get(cid, 0),
            "count2": count2.get(cid, 0),
            "matched": matched_count.get(cid, 0),
        }
        for cid in cids
    ]

    denom = n1 + n2
    return {
        "seq1": seq1_out,
        "seq2": seq2_out,
        "rows": rows,
        "similarity": {
            "dice": dice_coefficient(ids1, ids2),
            "sequence": 2.0 * lcs / denom if denom else 0.0,
            "lcs": lcs,
            "n1": n1,
            "n2": n2,
        },
        "cooccurrence": cooccurrence,
    }
