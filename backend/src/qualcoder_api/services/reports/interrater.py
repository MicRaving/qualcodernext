"""Interrater reliability: Krippendorff's alpha, Cohen's kappa, Gwet's AC1."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _krippendorff_alpha(cell_sets: list[set[tuple[int, int]]]) -> float | None:
    """Krippendorff's alpha for binary nominal ratings, any number of raters.

    Units are the sources, categories the codes: every rater rates each
    cell of the (sources x codes) grid present/absent — a rater "marks"
    exactly the cells they coded, absent everywhere else. Uses the standard
    coincidence-matrix definition (Krippendorff 2011): coincidences are
    pairable-value counts normalized by (m_u - 1) per unit, and expected
    coincidences come from the value marginals with the (n - 1) correction.

    With two raters the formula reduces to the classical two-rater alpha,
    so a pair entry and the all-coders alpha agree.

    Returns None when the data cannot support the computation: fewer than
    two raters, an empty grid, or a degenerate margin (no expected
    disagreement).
    """
    cells: set[tuple[int, int]] = set()
    for cell_set in cell_sets:
        cells |= cell_set
    n_coders = len(cell_sets)
    fids = {fid for fid, _ in cells}
    cids = {cid for _, cid in cells}
    if n_coders < 2 or not fids or not cids:
        return None

    # Unnormalized coincidence counts over the full grid: o11/o00 count
    # same-value rater pairs, o01 counts discordant pairs (o10 = o01).
    o11 = o00 = o01 = 0
    for fid in fids:
        for cid in cids:
            ones = sum(1 for cell_set in cell_sets if (fid, cid) in cell_set)
            zeros = n_coders - ones
            o11 += ones * (ones - 1)
            o00 += zeros * (zeros - 1)
            o01 += ones * zeros
    total = o11 + o00 + 2 * o01
    if total == 0:
        return None

    # Every unit carries n_coders ratings, so the pairable normalization
    # divides by (n_coders - 1): the coincidence matrix sums to n (the
    # number of ratings) and the value marginals are o0/(m-1), o1/(m-1).
    # alpha = 1 - Do/De with
    #   Do = 2*o01/(m-1) and De = 2*n0*n1/(n-1), n = total/(m-1)
    # which simplifies to the closed form below.
    o0 = o00 + o01
    o1 = o01 + o11
    if o0 == 0 or o1 == 0:
        return None
    n = total / (n_coders - 1)
    do = 2 * o01 / (n_coders - 1)
    de = 2 * (o0 / (n_coders - 1)) * (o1 / (n_coders - 1)) / (n - 1)
    if de == 0:
        return None
    return 1 - do / de


def _pair_report(
    cells_a: set[tuple[int, int]], cells_b: set[tuple[int, int]]
) -> dict:
    """Cohen's Kappa, Krippendorff's Alpha and Gwet's AC1 for two coders.

    The unit space is the union of both coders' (source, code) cells; each
    cell is rated present/absent by each coder. Returns the contingency
    counts (both/only_a/only_b/neither) plus the three measures, all None
    when there is no data.
    """
    file_ids = {fid for fid, _ in cells_a} | {fid for fid, _ in cells_b}
    code_ids = {cid for _, cid in cells_a} | {cid for _, cid in cells_b}
    n_units = len(file_ids)
    n_categories = len(code_ids)
    n_pairs = n_units * n_categories
    if n_units == 0 or n_categories == 0:
        return {
            "n_units": n_units,
            "n_categories": n_categories,
            "n_pairs": 0,
            "both": 0,
            "only_a": 0,
            "only_b": 0,
            "neither": 0,
            "kappa": None,
            "krippendorff": None,
            "gwet_ac1": None,
        }

    both = len(cells_a & cells_b)
    only_a = len(cells_a - cells_b)
    only_b = len(cells_b - cells_a)
    neither = n_pairs - both - only_a - only_b

    po = (both + neither) / n_pairs
    # Cohen's kappa, chance agreement from the marginals.
    a_marked = both + only_a
    b_marked = both + only_b
    pe = (a_marked * b_marked + (n_pairs - a_marked) * (n_pairs - b_marked)) / (n_pairs * n_pairs)
    kappa = (po - pe) / (1 - pe) if pe != 1 else None

    # Krippendorff's alpha, binary nominal, via the coincidence matrix —
    # identical to the all-coders alpha restricted to this pair.
    krippendorff = _krippendorff_alpha([cells_a, cells_b])

    # Gwet's AC1: chance agreement from the mean rating probability.
    p_plus = (a_marked + b_marked) / (2 * n_pairs)
    pe_gwet = 2 * p_plus * (1 - p_plus)
    gwet_ac1 = (po - pe_gwet) / (1 - pe_gwet) if pe_gwet != 1 else None

    return {
        "n_units": n_units,
        "n_categories": n_categories,
        "n_pairs": n_pairs,
        "both": both,
        "only_a": only_a,
        "only_b": only_b,
        "neither": neither,
        "kappa": round(kappa, 4) if kappa is not None else None,
        "krippendorff": round(krippendorff, 4) if krippendorff is not None else None,
        "gwet_ac1": round(gwet_ac1, 4) if gwet_ac1 is not None else None,
    }


def _pairwise_summary(pairs: list[dict]) -> dict:
    """Mean/min/max of each agreement measure across coder pairs."""
    keys = ("kappa", "krippendorff", "gwet_ac1")
    mean: dict[str, float | None] = {}
    minimum: dict[str, float | None] = {}
    maximum: dict[str, float | None] = {}
    for key in keys:
        values = [pair[key] for pair in pairs if pair[key] is not None]
        mean[key] = round(sum(values) / len(values), 4) if values else None
        minimum[key] = min(values) if values else None
        maximum[key] = max(values) if values else None
    return {"mean": mean, "min": minimum, "max": maximum}


async def interrater(
    session: AsyncSession,
    coder_a: str,
    coder_b: str,
    coders: list[str] | None = None,
) -> dict:
    """Interrater reliability over any number of coders.

    Each selected coder rates every (source, code) cell present/absent.
    ``coders`` (optional) restricts the comparison — default: every coder
    in the project with codings. ``coder_a``/``coder_b`` anchor the
    backward-compatible contingency fields (the frontend passes the first
    two selected coders).

    Returns Krippendorff's Alpha over ALL selected coders plus, per
    unordered coder pair, Cohen's Kappa, Krippendorff's Alpha and Gwet's
    AC1 with the contingency detail, and the mean/min/max of each measure
    across pairs.
    """
    if coder_a == coder_b:
        raise ValueError("choose two different coders")

    # owner → set of coded (source, code) cells per coder.
    cells_by_coder: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for tbl, file_col in (
        ("code_text_visible", "fid"),
        ("code_image_visible", "id"),
        ("code_av_visible", "id"),
    ):
        rows = await session.execute(
            text(
                f"SELECT {file_col}, cid, COALESCE(owner, '') FROM {tbl} "
                f"WHERE {file_col} IS NOT NULL AND cid IS NOT NULL"
            )
        )
        for fid, cid, owner in rows:
            cells_by_coder[owner].add((fid, cid))

    if coders is not None:
        selected = list(dict.fromkeys(coders))
        if len(selected) < 2:
            raise ValueError("choose at least two coders")
    else:
        # Default: all project coders with codings (null-owner codings
        # belong to no coder, mirroring the coder-comparison report).
        selected = sorted(name for name in cells_by_coder if name != "")

    pairs = [
        {
            "coder_a": selected[i],
            "coder_b": selected[j],
            **_pair_report(cells_by_coder[selected[i]], cells_by_coder[selected[j]]),
        }
        for i in range(len(selected))
        for j in range(i + 1, len(selected))
    ]
    summary = _pairwise_summary(pairs)
    alpha = _krippendorff_alpha([cells_by_coder[c] for c in selected])

    return {
        "coders": selected,
        "n_coders": len(selected),
        "alpha": round(alpha, 4) if alpha is not None else None,
        # Anchor pair: backward-compatible contingency fields.
        "coder_a": coder_a,
        "coder_b": coder_b,
        **_pair_report(cells_by_coder[coder_a], cells_by_coder[coder_b]),
        "pairs": pairs,
        "pairwise_mean": summary["mean"],
        "pairwise_min": summary["min"],
        "pairwise_max": summary["max"],
    }
