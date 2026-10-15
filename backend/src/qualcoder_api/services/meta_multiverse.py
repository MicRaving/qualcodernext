"""Multiverse / specification-curve enumeration over the derived effect rows.

The meta-analysis pipeline makes several defensible analytic choices. Rather
than committing to a single one, :func:`multiverse` crosses them into a grid of
specifications and reports every pooled estimate, so a result that only holds
under one arbitrary combination is visible as such.

The four dimensions are:

* ``primary`` — the ``eligible_primary`` effects only vs. every effect.
* ``estimator`` — DerSimonian-Laird (``dl``), a two-level (effects nested in
  studies) random-effects estimate, or a fixed-effect (``fixed``) estimate.
* ``domain`` — all outcomes pooled vs. each observed ``dv_domain`` level.
* ``exclude_outliers`` — keep vs. drop effects with ``|effect| > 3``.

Specifications with fewer than two usable effects are skipped. Only the
existing role-driven effect rows are read, so no field name or schema is
assumed.
"""

from __future__ import annotations

from itertools import product
from typing import Any

from qualcoder_api.core.lazy_import import LazyModule
from qualcoder_api.services.meta_analysis import (
    _num,
    _safe,
    pool_dl,
    pool_fixed,
    pool_two_level,
    primary_effects,
)

# See meta_analysis: numpy loads on the first analysis, not at import.
np = LazyModule("numpy")

_ESTIMATORS = ("dl", "two_level", "fixed")
_PRIMARY_LEVELS = ("primary", "all")
_OUTLIER_LEVELS = ("keep", "drop")
_OUTLIER_ABS = 3.0


def _fixed_pool(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fixed-effect (inverse-variance) pooled estimate (delegates to analysis)."""
    return pool_fixed(rows)


def _two_level_pool(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reference two-stage estimate from the two-level variance decomposition."""
    components = pool_two_level(rows)
    k = int(components.get("k") or 0)
    if k == 0:
        return {
            "k": 0, "estimate": None, "se": None, "ci_low": None, "ci_high": None,
            "tau2": 0.0, "i2": 0.0,
        }
    tau2 = float(components.get("tau2_within") or 0.0) + float(
        components.get("tau2_between") or 0.0
    )
    return {
        "k": k,
        "estimate": components.get("estimate"),
        "se": components.get("se"),
        "ci_low": components.get("ci_low"),
        "ci_high": components.get("ci_high"),
        "tau2": _safe(tau2),
        "i2": components.get("i2_between"),
    }


def _estimator_pool(rows: list[dict[str, Any]], estimator: str) -> dict[str, Any]:
    if estimator == "two_level":
        return _two_level_pool(rows)
    if estimator == "fixed":
        return _fixed_pool(rows)
    pooled = pool_dl(rows)
    return {
        "k": pooled["k"],
        "estimate": pooled["estimate"],
        "se": pooled["se"],
        "ci_low": pooled["ci_low"],
        "ci_high": pooled["ci_high"],
        "tau2": pooled["tau2"],
        "i2": pooled["i2"],
    }


def _select(
    rows: list[dict[str, Any]], primary_level: str, domain_level: str, outlier: str
) -> list[dict[str, Any]]:
    selected = primary_effects(rows) if primary_level == "primary" else list(rows)
    if domain_level != "all":
        selected = [
            row for row in selected if str(row.get("domain") or "").strip() == domain_level
        ]
    if outlier == "drop":
        selected = [row for row in selected if not _is_outlier(row)]
    return selected


def _is_outlier(row: dict[str, Any]) -> bool:
    effect = _num(row.get("effect"))
    return effect is not None and abs(effect) > _OUTLIER_ABS


def multiverse(rows: list[dict[str, Any]], *, max_specs: int = 200) -> dict[str, Any]:
    """Enumerate the specification grid over ``rows`` and summarise the estimates.

    ``rows`` are the derived effect rows (``meta_analysis.build_effects`` output);
    ``max_specs`` caps how many specifications are returned. The output carries
    the grid dimensions, every retained specification, and a summary of the
    resulting estimate distribution (median, range, share above zero and the
    2.5th/97.5th percentile interval).
    """
    row_list = [
        row for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict)
    ]
    domains = sorted(
        {
            str(row.get("domain") or "").strip()
            for row in row_list
            if str(row.get("domain") or "").strip()
        }
    )
    domain_levels = ["all", *domains]
    dimensions = [
        {"name": "primary", "levels": list(_PRIMARY_LEVELS)},
        {"name": "estimator", "levels": list(_ESTIMATORS)},
        {"name": "domain", "levels": domain_levels},
        {"name": "exclude_outliers", "levels": list(_OUTLIER_LEVELS)},
    ]
    limit = max_specs if max_specs and max_specs > 0 else 1

    # Enumerate *all* valid specifications first (in a deterministic order);
    # truncating the raw product would bias the tail toward the first levels.
    enumerated: list[dict[str, Any]] = []
    combos = product(_PRIMARY_LEVELS, _ESTIMATORS, domain_levels, _OUTLIER_LEVELS)
    for primary_level, estimator, domain_level, outlier in combos:
        subset = _select(row_list, primary_level, domain_level, outlier)
        if len(subset) < 2:
            continue
        pooled = _estimator_pool(subset, estimator)
        if pooled["k"] < 2:
            continue
        enumerated.append(
            {
                "choices": {
                    "primary": primary_level,
                    "estimator": estimator,
                    "domain": domain_level,
                    "exclude_outliers": outlier,
                },
                "k": pooled["k"],
                "estimate": pooled["estimate"],
                "se": pooled["se"],
                "ci_low": pooled["ci_low"],
                "ci_high": pooled["ci_high"],
                "tau2": pooled["tau2"],
                "i2": pooled["i2"],
            }
        )
    n_enumerated = len(enumerated)
    sampled = n_enumerated > limit
    if sampled:
        enumerated.sort(
            key=lambda spec: (
                spec["choices"]["primary"],
                spec["choices"]["estimator"],
                spec["choices"]["domain"],
                spec["choices"]["exclude_outliers"],
            )
        )
        picked: list[dict[str, Any]] = []
        seen: set[int] = set()
        step = (n_enumerated - 1) / (limit - 1) if limit > 1 else 0.0
        for j in range(limit):
            index = round(step * j)
            if index not in seen:
                seen.add(index)
                picked.append(enumerated[index])
        enumerated = picked
    specs = [{"id": i + 1, **spec} for i, spec in enumerate(enumerated)]

    estimates = [
        float(spec["estimate"]) for spec in specs if spec["estimate"] is not None
    ]
    summary: dict[str, Any] = {
        "n_specs": len(specs),
        "n_enumerated": n_enumerated,
        "sampled": sampled,
        "n_ok": len(estimates),
        "median": None,
        "min": None,
        "max": None,
        "pct_positive": None,
        "ci_low": None,
        "ci_high": None,
    }
    if estimates:
        arr = np.asarray(estimates, dtype=float)
        summary.update(
            {
                "median": _safe(float(np.median(arr))),
                "min": _safe(float(np.min(arr))),
                "max": _safe(float(np.max(arr))),
                "pct_positive": _safe(float(np.mean(arr > 0) * 100.0)),
                "ci_low": _safe(float(np.percentile(arr, 2.5))),
                "ci_high": _safe(float(np.percentile(arr, 97.5))),
            }
        )

    return {
        "k_total": len(row_list),
        "n_specs": len(specs),
        "dimensions": dimensions,
        "specs": specs,
        "summary": summary,
    }
