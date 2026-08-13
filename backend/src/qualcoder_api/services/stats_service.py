"""Pure-Python statistics for the reports module (stdlib only — no scipy).

Implements the small statistical toolkit the analysis suite needs:

* chi-square test on an r x c contingency table (Yates correction for 2 x 2)
  with expected cell counts, Cramér's V and a p-value computed from the
  regularized incomplete gamma function;
* Mann-Whitney U with an exact combinatorial p-value for small samples
  (both n ≤ 10) and a normal approximation with continuity correction
  (and the tie correction) otherwise;
* Spearman rank correlation with a two-tailed p-value from Student's t
  distribution via the regularized incomplete beta function;
* per-group descriptives (count, mean, median, sample sd, min, max).

All p-values are computed here; nothing is imported from scipy.
"""

from __future__ import annotations

import math

_FPMIN = 1e-300
_ITMAX = 200
_EPS = 3e-14

# ----------------------------------------------------------------------
# Special functions: regularized incomplete gamma/beta (Numerical Recipes
# style series + continued fractions, adapted to pure Python).
# ----------------------------------------------------------------------


def _lngamma(x: float) -> float:
    """Natural log of the gamma function (Lanczos approximation, g=7)."""
    if x <= 0:
        return float("inf")
    coefficients = (
        0.99999999999980993,
        676.5203681218851,
        -1259.1392167224028,
        771.32342877765313,
        -176.61502916214059,
        12.507343278686905,
        -0.13857109526572012,
        9.9843695780195716e-6,
        1.5056327351493116e-7,
    )
    if x < 0.5:
        # Reflection formula for small arguments.
        return math.log(math.pi) - math.log(math.sin(math.pi * x)) - _lngamma(1.0 - x)
    z = x - 1.0
    series = coefficients[0]
    for i in range(1, 9):
        series += coefficients[i] / (z + i)
    t = z + 7.5
    return 0.5 * math.log(2 * math.pi) + (z + 0.5) * math.log(t) - t + math.log(series)


def _gamma_p_series(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) via the series expansion."""
    if x == 0:
        return 0.0
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(_ITMAX):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - _lngamma(a))


def _gamma_q_cf(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) via Lentz's continued fraction."""
    b = x + 1.0 - a
    c = 1.0 / _FPMIN
    d = 1.0 / b if b != 0 else 1.0 / _FPMIN
    h = d
    for i in range(1, _ITMAX):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = b + an / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - _lngamma(a)) * h


def gamma_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) = 1 - P(a, x)."""
    if x < 0 or a <= 0:
        raise ValueError("gamma_q requires a > 0 and x >= 0")
    if x == 0:
        return 1.0
    if x < a + 1.0:
        return 1.0 - _gamma_p_series(a, x)
    return _gamma_q_cf(a, x)


def _beta_cont_frac(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta continued fraction (Lentz)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, _ITMAX):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def beta_regularized(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b), 0 <= x <= 1."""
    if x == 0.0:
        return 0.0
    if x == 1.0:
        return 1.0
    bt = math.exp(
        _lngamma(a + b) - _lngamma(a) - _lngamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _beta_cont_frac(a, b, x) / a
    return 1.0 - bt * _beta_cont_frac(b, a, 1.0 - x) / b


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _student_t_two_tailed_p(t: float, df: int) -> float | None:
    """Two-tailed p-value of Student's t with ``df`` degrees of freedom."""
    if df < 1:
        return None
    x = df / (df + t * t)
    if x == 0.0:
        return 0.0
    return beta_regularized(df / 2.0, 0.5, x)


# ----------------------------------------------------------------------
# Chi-square test + Cramér's V
# ----------------------------------------------------------------------


def chi_square(table: list[list[int]], yates: bool = True) -> dict:
    """Pearson chi-square test on an r x c contingency table.

    ``table`` is a list of rows, each a list of integer counts. For 2 x 2
    tables the Yates continuity correction is applied (subtracting 0.5
    from each |observed - expected| before squaring). Returns the
    statistic, degrees of freedom, the p-value (via the incomplete gamma
    function: p = Q(df/2, chi2/2)) and the expected-cell counts.
    """
    rows = len(table)
    cols = len(table[0]) if table else 0
    if rows < 2 or cols < 2:
        raise ValueError("contingency table needs at least 2 rows and 2 columns")
    for row in table:
        if len(row) != cols:
            raise ValueError("contingency table rows must have equal length")

    row_totals = [sum(row) for row in table]
    col_totals = [sum(table[r][c] for r in range(rows)) for c in range(cols)]
    n = sum(row_totals)
    if n == 0:
        raise ValueError("contingency table is empty")

    expected = [[row_totals[r] * col_totals[c] / n for c in range(cols)] for r in range(rows)]
    use_yates = yates and rows == 2 and cols == 2
    chi2 = 0.0
    for r in range(rows):
        for c in range(cols):
            if expected[r][c] <= 0:
                raise ValueError("contingency table has a zero row or column total")
            diff = abs(table[r][c] - expected[r][c])
            if use_yates:
                diff = max(0.0, diff - 0.5)
            chi2 += diff * diff / expected[r][c]

    df = (rows - 1) * (cols - 1)
    p = gamma_q(df / 2.0, chi2 / 2.0)
    return {
        "chi2": chi2,
        "df": df,
        "p": p,
        "yates": use_yates,
        "expected": expected,
        "n": n,
    }


def cramers_v(table: list[list[int]], chi2: float | None = None) -> float | None:
    """Cramér's V for an r x c table; V = sqrt(chi2 / (n * min(r-1, c-1)))."""
    rows, cols = len(table), len(table[0]) if table else 0
    n = sum(sum(row) for row in table)
    if n == 0 or rows < 2 or cols < 2:
        return None
    if chi2 is None:
        chi2 = chi_square(table, yates=False)["chi2"]
    denom = n * min(rows - 1, cols - 1)
    if denom == 0:
        return None
    return min(1.0, math.sqrt(chi2 / denom))


# ----------------------------------------------------------------------
# Mann-Whitney U
# ----------------------------------------------------------------------


def _rank_values(values: list[float]) -> list[float]:
    """Average ranks (mid-ranks for ties) of a list of values."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1.0  # average of ranks (i+1)..(j+1)
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def _exact_u_distribution(nx: int, ny: int, ranks: list[float]) -> dict[int, int]:
    """Exact null distribution of U via subset-sum combinatorics.

    Counts, for every possible U value, the number of rank subsets of size
    ``nx`` (out of nx+ny ranks, mid-ranks included with their multiplicity)
    that produce it. A DP over the distinct rank values is used, so tied
    ranks are handled exactly: a value appearing ``m`` times contributes
    ``C(m, j) * (j * rank)`` to the sums for picking ``j`` of them.
    Mid-ranks are halves, so all sums are tracked in doubled units.
    """
    max_rank = nx + ny
    total_sum2 = 2 * max_rank * (max_rank + 1) // 2  # sum of doubled ranks
    base2 = nx * (nx + 1)  # 2 * nx(nx+1)/2
    max_u = nx * ny

    multiplicity: dict[int, int] = {}
    for rank in ranks:
        doubled = round(rank * 2)  # mid-ranks are always multiples of 0.5
        multiplicity[doubled] = multiplicity.get(doubled, 0) + 1

    # dp[k][s] = ways to pick k ranks summing to s (doubled units). Each
    # group (doubled rank with multiplicity m) is applied from a snapshot
    # of the pre-group state so choosing j of the m items never
    # double-counts.
    dp = [[0] * (total_sum2 + 1) for _ in range(nx + 1)]
    dp[0][0] = 1
    for doubled, count in multiplicity.items():
        new = [row[:] for row in dp]
        for j in range(1, min(count, nx) + 1):
            ways = math.comb(count, j)
            add = j * doubled
            for k in range(nx - j + 1):
                for s in range(total_sum2 - add + 1):
                    if dp[k][s]:
                        new[k + j][s + add] += ways * dp[k][s]
        dp = new

    distribution: dict[int, int] = {}
    for s in range(base2, base2 + 2 * max_u + 1, 2):
        if dp[nx][s]:
            distribution[(s - base2) // 2] = dp[nx][s]
    return distribution


def mann_whitney_u(x: list[float], y: list[float]) -> dict:
    """Mann-Whitney U test for two independent samples.

    Exact two-tailed p-value (combinatorial subset distribution) when both
    sample sizes are ≤ 10; otherwise the normal approximation with the
    continuity correction and, when ties are present, the tie correction.
    Returns both U statistics (u1 for ``x``, u2 for ``y``), the p-value and
    which method produced it.
    """
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        raise ValueError("both samples must be non-empty")

    ranks = _rank_values(list(x) + list(y))
    sum_x = sum(ranks[:nx])
    u1 = sum_x - nx * (nx + 1) / 2.0
    u2 = nx * ny - u1
    u_obs = min(u1, u2)
    n = nx + ny

    if nx <= 10 and ny <= 10:
        distribution = _exact_u_distribution(nx, ny, ranks)
        total = sum(distribution.values())
        p_lo = sum(count for u, count in distribution.items() if u <= u_obs) / total
        p_hi = sum(count for u, count in distribution.items() if u >= u_obs) / total
        p = min(1.0, 2.0 * min(p_lo, p_hi))
        method = "exact"
    else:
        mu = nx * ny / 2.0
        tie_terms: dict[float, int] = {}
        for rank in ranks:
            tie_terms[rank] = tie_terms.get(rank, 0) + 1
        tie_correction = sum(t * (t - 1) * (t + 1) for t in tie_terms.values())
        variance = nx * ny / 12.0 * (
            (n + 1.0) - tie_correction / (n * (n - 1.0))
        )
        sigma = math.sqrt(variance)
        z = (abs(u_obs - mu) - 0.5) / sigma if sigma > 0 else 0.0
        p = 2.0 * (1.0 - _normal_cdf(z))
        method = "normal-approx"

    return {
        "u1": u1,
        "u2": u2,
        "u": u_obs,
        "p": p,
        "method": method,
        "n1": nx,
        "n2": ny,
    }


# ----------------------------------------------------------------------
# Spearman rank correlation
# ----------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def spearman_rho(x: list[float], y: list[float]) -> dict:
    """Spearman rank correlation with a two-tailed p-value.

    Ties get average (mid-)ranks; rho is the Pearson correlation of the
    ranks, which is exact for tied data. The p-value comes from the t
    approximation t = rho * sqrt((n-2)/(1-rho^2)) with n-2 degrees of
    freedom, evaluated through the regularized incomplete beta function.
    """
    n = len(x)
    if n != len(y) or n < 2:
        raise ValueError("spearman_rho needs equal-length samples of size >= 2")
    rx = _rank_values(x)
    ry = _rank_values(y)

    mean_x = _mean(rx)
    mean_y = _mean(ry)
    cov = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
    var_x = sum((rx[i] - mean_x) ** 2 for i in range(n))
    var_y = sum((ry[i] - mean_y) ** 2 for i in range(n))
    denom = math.sqrt(var_x * var_y)
    rho = cov / denom if denom > 0 else 0.0

    if n < 3:
        return {"rho": rho, "t": None, "df": 0, "p": None}
    if abs(rho) >= 1.0:
        return {"rho": rho, "t": float("inf") if rho > 0 else float("-inf"), "df": n - 2, "p": 0.0}
    t = rho * math.sqrt((n - 2.0) / (1.0 - rho * rho))
    p = _student_t_two_tailed_p(t, n - 2)
    return {"rho": rho, "t": t, "df": n - 2, "p": p}


# ----------------------------------------------------------------------
# Group descriptives
# ----------------------------------------------------------------------


def group_descriptives(values: list[float]) -> dict:
    """Count, mean, median, sample sd, min, max of a numeric group."""
    n = len(values)
    if n == 0:
        return {"count": 0, "mean": None, "median": None, "sd": None, "min": None, "max": None}
    mean = _mean(values)
    sorted_values = sorted(values)
    median = sorted_values[n // 2] if n % 2 else (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2.0
    sd = (
        math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
        if n > 1 else 0.0
    )
    return {
        "count": n,
        "mean": mean,
        "median": median,
        "sd": sd,
        "min": min(values),
        "max": max(values),
    }
