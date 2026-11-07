"""Regression tests for the meta_* services audit fixes."""

from __future__ import annotations

import asyncio

import httpx
import numpy as np
import pytest

from qualcoder_api.services import meta_analysis, meta_download, meta_report
from qualcoder_api.services.meta_agreement import gwet_ac


def _row(study: str, effect: float, variance: float, mod: float) -> dict:
    return {
        "study_id": study,
        "effect": effect,
        "variance": variance,
        "fields": {"dose": mod},
    }


def test_gwet_ac_ignores_unrated_cases():
    rated = [["a", "a"], ["a", "b"], ["b", "b"], ["a", "a"]]
    base = gwet_ac(rated, ["a", "b"])
    padded = gwet_ac([*rated, [], []], ["a", "b"])
    assert base is not None and padded is not None
    # Cases nobody rated must not change the chance-agreement term.
    assert padded["pe"] == pytest.approx(base["pe"])
    assert padded["coeff"] == pytest.approx(base["coeff"])


def test_moderator_r2_tau_uses_dl_meta_regression_estimator():
    doses = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    effects = [0.05, 0.31, 0.38, 0.72, 0.81, 1.15, 1.18, 1.52]
    variances = [0.02, 0.03, 0.025, 0.04, 0.02, 0.03, 0.05, 0.03]
    rows = [
        _row(f"S{i}", y, v, d)
        for i, (y, v, d) in enumerate(zip(effects, variances, doses, strict=True))
    ]
    result = meta_analysis.moderator(rows, "dose")

    y, v, d = np.array(effects), np.array(variances), np.array(doses)
    w = 1.0 / v
    x = np.column_stack([np.ones(len(y)), d - d.mean()])
    cov = np.linalg.inv(x.T @ (w[:, None] * x))
    resid = y - x @ (cov @ (x.T @ (w * y)))
    q_e = float((w * resid**2).sum())
    c_e = float(w.sum() - np.trace(cov @ (x.T @ ((w * w)[:, None] * x))))
    tau2_res = max(0.0, (q_e - (len(y) - 2)) / c_e)
    tau2_null = meta_analysis.pool_dl(rows)["tau2"]
    assert tau2_null > 0
    assert result["r2_tau"] == pytest.approx(max(0.0, 1 - tau2_res / tau2_null))
    # A near-perfect linear moderator explains most between-study variance.
    assert result["r2_tau"] > 0.5


def test_report_egger_uses_slope_as_asymmetry_test():
    bias = {
        "egger": {"k": 5, "intercept": 0.111, "se": 0.2, "t": 0.5, "p": 0.6,
                  "slope": 1.234, "slope_se": 0.3, "slope_p": 0.01},
        "pet_peese": {"pet": {"intercept": 0.111, "p": 0.6}, "peese": {}, "recommended": "PET"},
        "trim_and_fill": {},
        "p_curve": {},
    }
    section = meta_report._bias_section(bias)
    egger_sentence = section["paragraphs"][0].split(". PET")[0]
    # The asymmetry test is the SE slope, not the intercept (= PET estimate).
    assert "1.23" in egger_sentence
    assert "0.11" not in egger_sentence


def test_resolve_crossref_non_json_body_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>captcha</html>")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await meta_download.resolve_crossref(client, "10.1/x")

    assert asyncio.run(run()) is None
