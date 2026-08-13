"""Unit tests for the pure-Python statistics module (stats_service.py).

Every expectation is hand-computed or drawn from standard textbook
examples — no scipy is used anywhere in the codebase.
"""

from __future__ import annotations

import math

import pytest

from qualcoder_api.services import stats_service

# ----------------------------------------------------------------------
# Chi-square (with Yates) + Cramér's V
# ----------------------------------------------------------------------


def test_chi_square_2x2_yates_known_example():
    # Agresti-style 2x2 with all marginals equal: [[8, 2], [2, 8]], n = 20.
    # Yates: chi2 = 4 * (2.5^2 / 5) = 5.0, df = 1.
    table = [[8, 2], [2, 8]]
    result = stats_service.chi_square(table, yates=True)
    assert result["chi2"] == pytest.approx(5.0, abs=1e-9)
    assert result["df"] == 1
    assert result["yates"] is True
    assert result["n"] == 20
    for row in result["expected"]:
        assert row == pytest.approx([5.0, 5.0], abs=1e-9)
    # p = Q(0.5, 2.5) = 0.025347... (textbook / scipy value).
    assert result["p"] == pytest.approx(0.0253473, abs=1e-6)


def test_chi_square_2x2_without_yates():
    table = [[8, 2], [2, 8]]
    result = stats_service.chi_square(table, yates=False)
    assert result["chi2"] == pytest.approx(7.2, abs=1e-9)
    assert result["yates"] is False
    # p = 1 - erf(sqrt(3.6)) = 0.00729036 (scipy reference).
    assert result["p"] == pytest.approx(0.00729036, abs=1e-8)


def test_chi_square_3x3_against_closed_form():
    # Hand-computed r x c example: expected counts from the marginals give
    # chi2 = 7.7111, df = 4. For df = 4 the survival function has the
    # closed form Q(2, chi2/2) = e^{-x}(1 + x), cross-checking the gamma
    # implementation independently of the series/continued-fraction code.
    table = [[43, 11, 6], [7, 8, 4], [12, 6, 3]]
    result = stats_service.chi_square(table, yates=True)
    assert result["chi2"] == pytest.approx(7.7111, abs=1e-3)
    assert result["df"] == 4
    assert result["yates"] is False  # correction only applies to 2x2
    x = result["chi2"] / 2.0
    expected_p = math.exp(-x) * (1.0 + x)
    assert result["p"] == pytest.approx(expected_p, rel=1e-9)


def test_chi_square_degenerate_inputs():
    with pytest.raises(ValueError, match="at least 2 rows"):
        stats_service.chi_square([[1, 2]])  # single row
    with pytest.raises(ValueError, match="empty"):
        stats_service.chi_square([[0, 0], [0, 0]])  # empty
    with pytest.raises(ValueError, match="zero row or column total"):
        stats_service.chi_square([[0, 5], [0, 5]])  # zero column total
    # A fully-offset 2x2 is fine (expected cells are all 2.5): chi2 = 10
    # uncorrected, 6.4 with Yates.
    assert stats_service.chi_square([[0, 5], [5, 0]], yates=False)["chi2"] == pytest.approx(10.0)
    assert stats_service.chi_square([[0, 5], [5, 0]], yates=True)["chi2"] == pytest.approx(6.4)


def test_cramers_v_known_value():
    table = [[8, 2], [2, 8]]
    chi2 = stats_service.chi_square(table, yates=False)["chi2"]  # 7.2
    # V = sqrt(7.2 / (20 * 1)) = 0.6
    assert stats_service.cramers_v(table, chi2) == pytest.approx(0.6, abs=1e-9)
    assert stats_service.cramers_v(table) == pytest.approx(0.6, abs=1e-9)


# ----------------------------------------------------------------------
# Mann-Whitney U
# ----------------------------------------------------------------------


def test_mann_whitney_exact_small_n():
    # x = [1, 4], y = [2, 3, 5]; ranks x: 1, 4 -> U1 = 2, U2 = 4.
    # Distribution of U (nx=2, ny=3) has counts {0:1, 1:1, 2:2, 3:2, 4:2,
    # 5:1, 6:1}; P(U<=2) = 0.4, P(U>=2) = 0.8 -> two-tailed p = 0.8.
    result = stats_service.mann_whitney_u([1.0, 4.0], [2.0, 3.0, 5.0])
    assert result["method"] == "exact"
    assert result["u1"] == pytest.approx(2.0, abs=1e-9)
    assert result["u2"] == pytest.approx(4.0, abs=1e-9)
    assert result["u"] == pytest.approx(2.0, abs=1e-9)
    assert result["p"] == pytest.approx(0.8, abs=1e-9)


def test_mann_whitney_exact_extreme():
    # Perfect separation: x all below y. U1 = 0 -> p = 2 / C(5,3) = 0.2.
    result = stats_service.mann_whitney_u([1.0, 2.0, 3.0], [4.0, 5.0])
    assert result["method"] == "exact"
    assert result["u1"] == pytest.approx(0.0, abs=1e-9)
    assert result["p"] == pytest.approx(0.2, abs=1e-9)


def test_mann_whitney_exact_matches_normal_for_large_n():
    # Perfect separation at the exact/approx boundary (n = 10 each):
    # U = 0 with P(U <= 0) = 1/C(20,10); two-tailed p = 2/184756.
    x = [float(i) for i in range(1, 11)]
    y = [float(i) for i in range(21, 31)]
    exact = stats_service.mann_whitney_u(x, y)
    assert exact["method"] == "exact"
    assert exact["u"] == pytest.approx(0.0, abs=1e-9)
    assert exact["p"] == pytest.approx(2 / math.comb(20, 10), rel=1e-9)


def test_mann_whitney_normal_approximation_known_z():
    # x = 1..15, y = 21..35: ranks split perfectly. U = 0 (min side),
    # mu = 112.5, sigma = sqrt(225*31/12) = 24.109. With continuity
    # correction z = (112.5 - 0.5)/24.109 = 4.6455.
    x = [float(i) for i in range(1, 16)]
    y = [float(i) for i in range(21, 36)]
    result = stats_service.mann_whitney_u(x, y)
    assert result["method"] == "normal-approx"
    assert result["u"] == pytest.approx(0.0, abs=1e-6)
    z = (112.5 - 0.5) / math.sqrt(225 * 31 / 12)
    p_expected = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
    assert result["p"] == pytest.approx(p_expected, rel=1e-9)
    assert result["p"] == pytest.approx(3.39e-6, rel=0.01)


def test_mann_whitney_ties():
    # Tied ranks use mid-ranks; U must remain in [0, n1*n2].
    result = stats_service.mann_whitney_u([1.0, 1.0, 2.0], [1.0, 3.0, 3.0])
    assert 0 <= result["u"] <= 9
    assert 0 <= result["p"] <= 1


def test_exact_u_distribution_totals():
    """The DP distribution must sum to C(nx+ny, nx), ties included."""
    for nx, ny in [(2, 3), (5, 5), (10, 10)]:
        ranks = stats_service._rank_values(list(range(1, nx + ny + 1)))
        dist = stats_service._exact_u_distribution(nx, ny, ranks)
        assert sum(dist.values()) == math.comb(nx + ny, nx)
        # Symmetry: count[U] == count[nx*ny - U].
        for u, count in dist.items():
            assert dist[nx * ny - u] == count
    # Tied mid-ranks (two 1.5s, one 3, two 5.5s across n = 5) still sum
    # to the binomial total: each position is a distinct pick.
    ranks = stats_service._rank_values([1.0, 1.0, 2.0, 1.0, 3.0])
    dist = stats_service._exact_u_distribution(2, 3, ranks)
    assert sum(dist.values()) == math.comb(5, 2)


# ----------------------------------------------------------------------
# Spearman rank correlation
# ----------------------------------------------------------------------


def test_spearman_known_values():
    # x ranks [3,5,1,4,2], y ranks [2,4,1,5,3]: sum d^2 = 4,
    # rho = 1 - 24/120 = 0.8; t = 0.8*sqrt(3/0.36) = 2.3094, df = 3.
    # Two-tailed p = I_0.36(3/2, 1/2) = 0.104097 (closed form).
    x = [3.0, 5.0, 1.0, 4.0, 2.0]
    y = [2.0, 4.0, 1.0, 5.0, 3.0]
    result = stats_service.spearman_rho(x, y)
    assert result["rho"] == pytest.approx(0.8, abs=1e-9)
    assert result["t"] == pytest.approx(2.3094, abs=1e-3)
    assert result["df"] == 3
    assert result["p"] == pytest.approx(0.104097, abs=1e-5)


def test_spearman_perfect_monotone():
    result = stats_service.spearman_rho([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
    assert result["rho"] == pytest.approx(1.0)
    assert result["p"] == 0.0
    inverse = stats_service.spearman_rho([1.0, 2.0, 3.0], [6.0, 5.0, 4.0])
    assert inverse["rho"] == pytest.approx(-1.0)


def test_spearman_with_ties():
    # Mid-ranks: rho computed as Pearson correlation on the ranks.
    x = [1.0, 1.0, 2.0, 3.0]
    y = [2.0, 2.0, 1.0, 4.0]
    result = stats_service.spearman_rho(x, y)
    assert -1.0 <= result["rho"] <= 1.0
    assert result["p"] is not None
    assert 0 <= result["p"] <= 1


def test_spearman_too_short():
    with pytest.raises(ValueError, match="equal-length"):
        stats_service.spearman_rho([1.0], [2.0])


# ----------------------------------------------------------------------
# Group descriptives
# ----------------------------------------------------------------------


def test_group_descriptives_known_values():
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    result = stats_service.group_descriptives(values)
    assert result["count"] == 8
    assert result["mean"] == pytest.approx(5.0)
    assert result["median"] == pytest.approx(4.5)
    assert result["min"] == 2.0
    assert result["max"] == 9.0
    # Sample sd: sum (x - 5)^2 = 9 + 1 + 1 + 1 + 0 + 0 + 4 + 16 = 32;
    # 32 / 7 = 4.5714...
    assert result["sd"] == pytest.approx(math.sqrt(32 / 7), abs=1e-9)


def test_group_descriptives_empty_and_single():
    empty = stats_service.group_descriptives([])
    assert empty["count"] == 0
    assert empty["mean"] is None
    single = stats_service.group_descriptives([3.5])
    assert single["count"] == 1
    assert single["mean"] == 3.5
    assert single["sd"] == 0.0
