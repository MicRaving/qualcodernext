"""Effect-size derivation and metric completeness (contract §5).

Pure helpers operating on a role-keyed metric (``{role: value}``). No field
names, no third-party deps. Formulas follow the reference pipeline / metafor
large-sample conversions; polarity is applied to the derived ``yi`` so a
positive effect always means "the intervention moved the outcome the good way".

:func:`derive_effect` and :func:`metric_status` share :func:`_derive_raw`, so
the completeness check mirrors the exact derivation preconditions instead of
drifting from them.
"""

from __future__ import annotations

import math
from typing import Any

from qualcoder_api.services.meta_roles import metric_by_role

#: All families understood by :func:`metric_status` (used when a scheme has no
#: explicit ``effect_families`` — i.e. legacy v1 codebooks).
ALL_FAMILIES = (
    "descriptives",
    "t",
    "F",
    "r",
    "yi",
    "d_g",
    "odds_ratio",
    "risk_ratio",
    "beta",
    "eta2p",
    "chi2",
)

_Z_95 = 1.959963984540054

#: Normalised polarity strings that mean "a larger outcome value is worse",
#: so the derived effect must be negated to keep positive = intervention good.
_FLIP_POLARITIES = frozenset({"higher is worse", "worse", "negative", "-1", "-"})

#: Derivation ``method`` labels mapped to the family key ``metric_status`` and
#: ``effect_families`` use (only the d/g and r conversions differ in name).
_METHOD_FAMILY = {
    "reported_yi": "yi",
    "cohens_d": "d_g",
    "hedges_g": "d_g",
    "descriptives": "descriptives",
    "t": "t",
    "F": "F",
    "r_to_d": "r",
    "odds_ratio": "odds_ratio",
    "risk_ratio": "risk_ratio",
    "eta2p": "eta2p",
    "beta": "beta",
    "chi2": "chi2",
}


def _num(value: Any) -> float | None:
    """Numeric value or ``None`` (bools are not numbers here)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _int(value: Any) -> int | None:
    num = _num(value)
    if num is None or num <= 0 or not float(num).is_integer():
        return None
    return int(num)


def _smd_variance(d: float, n1: int, n2: int) -> float:
    return (n1 + n2) / (n1 * n2) + (d * d) / (2 * (n1 + n2))


def _smd_from_means(m1: float, m2: float, sd1: float, sd2: float, n1: int, n2: int) -> float | None:
    if n1 + n2 - 2 <= 0 or sd1 < 0 or sd2 < 0:
        return None
    pooled = ((n1 - 1) * sd1 * sd1 + (n2 - 1) * sd2 * sd2) / (n1 + n2 - 2)
    if pooled <= 0:
        return None
    return (m1 - m2) / math.sqrt(pooled)


def _hedges_j(n1: int, n2: int) -> float:
    """Small-sample Hedges correction ``J = 1 - 3/(4*(n1+n2)-9)``."""
    denom = 4 * (n1 + n2) - 9
    if denom <= 0:
        return 1.0
    return 1.0 - 3.0 / denom


def _normalise_polarity(value: Any) -> str:
    """Lower-case/strip/underscore-collapse a polarity value."""
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def _apply_polarity(by_role: dict[str, Any], yi: float) -> tuple[float, bool]:
    """Flip ``yi`` when the outcome's polarity says higher is worse.

    Accepts the canonical ids plus the common synonyms ``worse`` / ``negative``
    / ``-1`` / ``-`` (any case, underscores or surrounding whitespace).
    """
    if _normalise_polarity(by_role.get("polarity")) in _FLIP_POLARITIES:
        return -yi, True
    return yi, False


def _result(yi: float, vi: float, method: str, sign_flipped: bool) -> dict[str, Any] | None:
    if vi is None or vi < 0 or not math.isfinite(yi) or not math.isfinite(vi):
        return None
    return {
        "yi": yi,
        "vi": vi,
        "sei": math.sqrt(vi),
        "method": method,
        "sign_flipped": sign_flipped,
    }


def _derive_raw(by: dict[str, Any]) -> tuple[str, float, float] | None:
    """First complete derivation ``(method, yi, vi)`` for a role-keyed metric.

    The single source of truth for both :func:`derive_effect` (which applies
    polarity) and :func:`metric_status` (which only needs the family). Returns
    the pre-polarity point estimate and its sampling variance.
    """
    n1 = _int(by.get("n1"))
    n2 = _int(by.get("n2"))
    n_total = _int(by.get("n_total"))

    # 1. reported yi + variance
    yi = _num(by.get("yi"))
    if yi is not None:
        vi = _num(by.get("vi"))
        sei = _num(by.get("sei"))
        if vi is None and sei is not None:
            vi = sei * sei
        if vi is not None:
            return "reported_yi", yi, vi

    # 2. Cohen's d / Hedges' g (+ n, or the reported SE)
    d_val = _num(by.get("d"))
    is_cohens_d = d_val is not None
    if d_val is None:
        d_val = _num(by.get("g"))
    if d_val is not None:
        vi = None
        if n1 and n2:
            vi = _smd_variance(d_val, n1, n2)
        else:
            se = _num(by.get("d_se"))
            if se is None:
                se = _num(by.get("g_se"))
            if se is not None:
                vi = se * se
        if vi is not None:
            if is_cohens_d:
                return "cohens_d", d_val, vi
            j = _hedges_j(n1, n2) if (n1 and n2) else 1.0
            return "hedges_g", j * d_val, j * j * vi

    # 3. full descriptives
    m1, m2 = _num(by.get("m1")), _num(by.get("m2"))
    sd1, sd2 = _num(by.get("sd1")), _num(by.get("sd2"))
    if None not in (m1, m2, sd1, sd2) and n1 and n2:
        d_desc = _smd_from_means(m1, m2, sd1, sd2, n1, n2)  # type: ignore[arg-type]
        if d_desc is not None:
            return "descriptives", d_desc, _smd_variance(d_desc, n1, n2)

    # 4. t statistic (+ n)
    t_val = _num(by.get("t"))
    if t_val is not None and n1 and n2:
        d_t = t_val * math.sqrt(1 / n1 + 1 / n2)
        return "t", d_t, _smd_variance(d_t, n1, n2)

    # 5. F statistic (+ n)
    f_val = _num(by.get("F"))
    if f_val is not None and f_val >= 0 and n1 and n2:
        d_f = math.sqrt(f_val) * math.sqrt(1 / n1 + 1 / n2)
        return "F", d_f, _smd_variance(d_f, n1, n2)

    # 6. correlation r (+ N): Borenstein et al. r-to-d conversion
    r_val = _num(by.get("r"))
    if r_val is not None and -1 < r_val < 1 and n_total and n_total > 1:
        d_r = 2 * r_val / math.sqrt(1 - r_val * r_val)
        var_r = 4 * (1 - r_val * r_val) / (n_total - 1)
        return "r_to_d", d_r, var_r

    # 7. odds ratio / risk ratio (each with its own CI roles)
    for role, method, lo_role, hi_role in (
        ("or", "odds_ratio", "or_ci_low", "or_ci_high"),
        ("rr", "risk_ratio", "rr_ci_low", "rr_ci_high"),
    ):
        point = _num(by.get(role))
        lo = _num(by.get(lo_role))
        hi = _num(by.get(hi_role))
        if point is None or point <= 0:
            continue
        if lo is not None and hi is not None and lo > 0 and hi > 0:
            log_point = math.log(point)
            vi = ((math.log(hi) - math.log(lo)) / (2 * _Z_95)) ** 2
            return method, log_point, vi

    # 8. partial eta squared (+ N)
    eta = _num(by.get("eta2p"))
    if eta is not None and 0 < eta < 1 and n_total and n_total > 1:
        d_eta = 2 * math.sqrt(eta / (1 - eta))
        gn1, gn2 = n_total // 2, n_total - n_total // 2
        if gn1 and gn2:
            return "eta2p", d_eta, _smd_variance(d_eta, gn1, gn2)

    # 9. regression beta (+ SE)
    beta = _num(by.get("beta"))
    beta_se = _num(by.get("beta_se"))
    if beta is not None and beta_se is not None:
        return "beta", beta, beta_se * beta_se

    # 10. chi-square + p (+ N)
    chi2 = _num(by.get("chi2"))
    if chi2 is not None and chi2 >= 0 and n_total and n_total > 1:
        d_chi = 2 * math.sqrt(chi2) / math.sqrt(n_total)
        return "chi2", d_chi, 4 / n_total

    return None


def derive_effect(metric: Any) -> dict[str, Any] | None:
    """Derive ``{yi, vi, sei, method, sign_flipped}`` from a role-keyed metric.

    ``metric`` may already be ``{role: value}`` or a raw metric dict (the v1
    reference aliases are then used to map it to roles). Returns ``None`` when
    no supported statistic family is complete.
    """
    # ``metric_by_role`` accepts both an already role-keyed dict and a raw
    # legacy metric (the aliases include the role ids themselves).
    by = metric_by_role(metric)
    if not by:
        return None
    raw = _derive_raw(by)
    if raw is None:
        return None
    method, value, vi = raw
    signed, flipped = _apply_polarity(by, value)
    return _result(signed, vi, method, flipped)


def metric_status(metric: Any, families: list[str] | None = None) -> tuple[str, str]:
    """``("complete"|"fallback"|"incomplete", reason)``.

    ``complete`` = the full descriptives set is present. ``fallback`` = one of
    the enabled families has a complete statistic set. Every other case is
    ``incomplete``. The fallback check reuses :func:`_derive_raw`, so it can
    never disagree with :func:`derive_effect` about whether a metric is usable.
    """
    by = metric_by_role(metric)
    enabled = set(families) if families else set(ALL_FAMILIES)

    if _complete_set(by, ("n1", "m1", "sd1", "n2", "m2", "sd2")):
        return "complete", ""

    raw = _derive_raw(by)
    if raw is not None:
        family = _METHOD_FAMILY.get(raw[0])
        if family in enabled:
            return "fallback", f"Using {family} fallback"
    return "incomplete", "Missing descriptive or fallback statistics."


def _complete_set(record: dict[str, Any], roles: tuple[str, ...]) -> bool:
    return all(_num(record.get(role)) is not None for role in roles)
