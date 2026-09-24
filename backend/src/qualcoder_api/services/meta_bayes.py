"""Bayesian normal-normal random-effects meta-analysis (contract §6).

Exact-up-to-grid random-effects model with an analytic ``mu`` integration and a
1-D grid over the between-study SD ``tau``::

    y_i ~ Normal(theta_i, v_i),  theta_i ~ Normal(mu, tau^2)
    mu  ~ Normal(0, mu_sd^2)
    tau ~ Half-Normal(0, tau_scale^2) or Half-Cauchy(0, tau_scale)

Because ``mu`` is integrated out analytically the posterior is exact up to the
``tau`` grid resolution, so no MCMC and no scipy are needed. Bayes factors use
the Savage-Dickey density ratio: ``BF10`` for ``mu = 0`` and ``BF01`` for
``tau = 0``. Only ``numpy``-free pure python is used (the model is scalar).
"""

from __future__ import annotations

import math
from typing import Any

from qualcoder_api.services.meta_analysis import _clean, _safe

#: Upper end of the tau grid (SD units) and number of grid points.
_TAU_MAX = 3.0
_GRID_N = 401

#: Number of grid points for the exported marginal mu posterior density.
_MU_GRID_N = 201

#: Constrained prior presets (free-form priors would invite prior hacking).
_MU_SD_PRESETS = (1.0, 5.0, 10.0, 100.0)
_TAU_PRESETS = (
    ("half-normal", 0.25),
    ("half-normal", 0.5),
    ("half-normal", 1.0),
    ("half-cauchy", 0.5),
    ("half-cauchy", 1.0),
)
_TAU_PRIOR_KINDS = ("half-normal", "half-cauchy")


def _tau_log_prior(tau: float, scale: float, kind: str) -> float:
    """Log prior density of ``tau`` up to a constant (constants cancel)."""
    if kind == "half-cauchy":
        return -math.log1p((tau / scale) ** 2)
    return -0.5 * (tau / scale) ** 2


def _tau_prior_density0(scale: float, kind: str) -> float:
    """Prior density at ``tau = 0`` (for the Savage-Dickey ratio)."""
    if kind == "half-cauchy":
        return 2.0 / (math.pi * scale)
    return 2.0 / (scale * math.sqrt(2.0 * math.pi))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _tau_grid(n: int = _GRID_N) -> list[float]:
    return [_TAU_MAX * i / (n - 1) for i in range(n)]


def _softmax(logpost: list[float]) -> list[float]:
    top = max(logpost)
    weights = [math.exp(value - top) for value in logpost]
    total = sum(weights)
    return [value / total for value in weights]


def _mixture_quantile(
    weights: list[float], means: list[float], sds: list[float], q: float
) -> float:
    """Quantile of the normal mixture by bisection on its CDF."""
    lo = min(m - 10.0 * s for m, s in zip(means, sds, strict=True)) - 1.0
    hi = max(m + 10.0 * s for m, s in zip(means, sds, strict=True)) + 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        cdf = sum(
            w * _norm_cdf((mid - m) / s)
            for w, m, s in zip(weights, means, sds, strict=True)
        )
        if cdf < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _weighted_quantile(values: list[float], weights: list[float], q: float) -> float | None:
    cum = 0.0
    for value, weight in zip(values, weights, strict=True):
        cum += weight
        if cum >= q:
            return value
    return values[-1] if values else None


def _mu_posterior(
    weights: list[float], means: list[float], sds: list[float], n: int = _MU_GRID_N
) -> dict[str, list[float]]:
    """Marginal posterior density of ``mu`` on a normalised grid.

    The posterior is a normal mixture ``sum_k w_k Normal(m_k, s_k^2)``; the grid
    spans the mixture support and the density is trapezoid-normalised to unit
    area so it can be plotted directly.
    """
    if not weights or not means or not sds or n < 2:
        return {"mu": [], "density": []}
    low = min(m - 4.0 * s for m, s in zip(means, sds, strict=True))
    high = max(m + 4.0 * s for m, s in zip(means, sds, strict=True))
    if high <= low:
        high = low + 1.0
    grid = [low + (high - low) * i / (n - 1) for i in range(n)]
    density: list[float] = [
        sum(
            w * _norm_pdf((x - m) / s) / s
            for w, m, s in zip(weights, means, sds, strict=True)
        )
        for x in grid
    ]
    step = grid[1] - grid[0]
    area = step * (0.5 * density[0] + sum(density[1:-1]) + 0.5 * density[-1])
    if area > 0:
        density = [value / area for value in density]
    return {"mu": grid, "density": density}


def bayes_pool(
    rows: list[dict[str, Any]],
    *,
    mu_sd: float = 1.0,
    tau_prior: str = "half-normal",
    tau_scale: float = 0.5,
) -> dict[str, Any]:
    """Bayesian random-effects posterior for the pooled effect and ``tau``.

    ``mu`` is integrated out analytically and ``tau`` is evaluated on a 1-D grid,
    so the posterior is exact up to grid resolution. Returns the posterior
    mean/median/95% credible interval, ``P(mu > 0)``, a two-sided posterior tail,
    the ``tau`` posterior summary and Savage-Dickey Bayes factors.
    """
    mu_sd = float(mu_sd) if mu_sd and float(mu_sd) > 0 else 1.0
    tau_scale = float(tau_scale) if tau_scale and float(tau_scale) > 0 else 0.5
    kind = str(tau_prior or "half-normal").strip().lower()
    if kind not in _TAU_PRIOR_KINDS:
        kind = "half-normal"
    prior = {"mu_sd": mu_sd, "tau_prior": kind, "tau_scale": tau_scale}

    y, v = _clean(rows)
    k = len(y)
    k_total = len(rows) if isinstance(rows, list) else 0
    empty: dict[str, Any] = {
        "k": k,
        "k_total": k_total,
        "mu": {
            "mean": None,
            "median": None,
            "ci_low": None,
            "ci_high": None,
            "p_gt0": None,
            "p_two_sided": None,
        },
        "tau": {"mean": None, "median": None, "ci_low": None, "ci_high": None},
        "bf10": None,
        "bf01_tau0": None,
        "prior": prior,
        "posterior": {"mu": [], "density": []},
    }
    if k == 0:
        return empty

    s2 = mu_sd * mu_sd
    grid = _tau_grid()
    logpost: list[float] = []
    means: list[float] = []
    sds: list[float] = []
    for tau in grid:
        t2 = tau * tau
        a = b = c = logdet = 0.0
        for yi, vi in zip(y, v, strict=True):
            d = vi + t2
            inv = 1.0 / d
            a += inv
            b += yi * inv
            c += yi * yi * inv
            logdet += math.log(d)
        logdet += math.log1p(s2 * a)
        quad = c - s2 * b * b / (1.0 + s2 * a)
        ll = -0.5 * (k * math.log(2.0 * math.pi) + logdet + quad)
        logpost.append(ll + _tau_log_prior(tau, tau_scale, kind))
        precision = a + 1.0 / s2
        means.append(b / precision)
        sds.append(math.sqrt(1.0 / precision))

    weights = _softmax(logpost)
    mu_mean = sum(w * m for w, m in zip(weights, means, strict=True))
    mu_median = _mixture_quantile(weights, means, sds, 0.5)
    ci_low = _mixture_quantile(weights, means, sds, 0.025)
    ci_high = _mixture_quantile(weights, means, sds, 0.975)
    cdf0 = sum(
        w * _norm_cdf((0.0 - m) / s)
        for w, m, s in zip(weights, means, sds, strict=True)
    )
    p_gt0 = 1.0 - cdf0
    p_two_sided = 2.0 * min(p_gt0, 1.0 - p_gt0)

    tau_mean = sum(w * t for w, t in zip(weights, grid, strict=True))
    tau_median = _weighted_quantile(grid, weights, 0.5)
    tau_low = _weighted_quantile(grid, weights, 0.025)
    tau_high = _weighted_quantile(grid, weights, 0.975)

    # Savage-Dickey Bayes factors at the point nulls (mu = 0, tau = 0).
    prior_mu0 = 1.0 / (mu_sd * math.sqrt(2.0 * math.pi))
    post_mu0 = sum(
        w * _norm_pdf((0.0 - m) / s) / s
        for w, m, s in zip(weights, means, sds, strict=True)
    )
    bf10 = prior_mu0 / post_mu0 if post_mu0 > 0 else None

    top = max(logpost)
    raw = [math.exp(value - top) for value in logpost]
    dtau = grid[1] - grid[0] if len(grid) > 1 else 1.0
    integral = dtau * (0.5 * raw[0] + sum(raw[1:-1]) + 0.5 * raw[-1])
    post_tau0 = raw[0] / integral if integral > 0 else 0.0
    prior_tau0 = _tau_prior_density0(tau_scale, kind)
    bf01_tau0 = post_tau0 / prior_tau0 if prior_tau0 > 0 else None

    posterior = _mu_posterior(weights, means, sds)

    return {
        "k": k,
        "k_total": k_total,
        "mu": {
            "mean": _safe(mu_mean),
            "median": _safe(mu_median),
            "ci_low": _safe(ci_low),
            "ci_high": _safe(ci_high),
            "p_gt0": _safe(p_gt0),
            "p_two_sided": _safe(p_two_sided),
        },
        "tau": {
            "mean": _safe(tau_mean),
            "median": _safe(tau_median),
            "ci_low": _safe(tau_low),
            "ci_high": _safe(tau_high),
        },
        "bf10": _safe(bf10),
        "bf01_tau0": _safe(bf01_tau0),
        "prior": prior,
        "posterior": posterior,
    }


def bayes_sensitivity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Posterior robustness across the constrained ``mu``/``tau`` prior presets.

    Every combination of ``mu_sd`` in ``{1, 5, 10, 100}`` and the ``tau`` prior
    presets is re-fitted, giving the pooled posterior and ``BF10`` for each.
    """
    out: list[dict[str, Any]] = []
    for mu_sd in _MU_SD_PRESETS:
        for kind, scale in _TAU_PRESETS:
            fit = bayes_pool(rows, mu_sd=mu_sd, tau_prior=kind, tau_scale=scale)
            out.append(
                {
                    "mu_sd": mu_sd,
                    "tau_prior": kind,
                    "tau_scale": scale,
                    "mean": fit["mu"]["mean"],
                    "ci_low": fit["mu"]["ci_low"],
                    "ci_high": fit["mu"]["ci_high"],
                    "bf10": fit["bf10"],
                }
            )
    return out
