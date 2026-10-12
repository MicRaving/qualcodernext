"""Meta-analysis statistics (contract §6).

Pure python/numpy random-effects pooling, heterogeneity decomposition,
subgroup analysis, weighted-least-squares meta-regression, Egger's regression,
leave-one-out influence diagnostics and forest-plot data.

Effects are derived from the flat ``dv_metrics`` rows through the field **roles**
(``meta_roles``) and ``meta_effects.derive_effect``; polarity is applied there,
so a positive ``effect`` always means the intervention moved the outcome the
good way. When any effect is flagged ``eligible_primary`` the primary pooling
uses those only (:func:`primary_effects`).

Only ``numpy`` is available (no scipy/statsmodels), so the chi-square and
Student-t tail probabilities are implemented with the regularized incomplete
gamma / beta functions.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from qualcoder_api.services.meta_effects import derive_effect
from qualcoder_api.services.meta_roles import metric_by_role, role_map
from qualcoder_api.services.meta_scheme import all_fields, normalise_codebook

_Z95 = 1.959963984540054
_MAX_MOD_LEVELS = 8

# ── numerics ─────────────────────────────────────────────────────────────

_EPS = 3e-16
_FPMIN = 1e-300
_ITMAX = 300


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if math.isfinite(out) else None
    if isinstance(value, str):
        try:
            out = float(value.strip())
        except ValueError:
            return None
        return out if math.isfinite(out) else None
    return None


def _safe(value: Any) -> float | None:
    """Float or ``None`` (never NaN/inf — the result must be JSON-safe)."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _gser(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) by series expansion."""
    total = 1.0 / a
    delta = total
    ap = a
    for _ in range(_ITMAX):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gcf(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) by continued fraction."""
    b = x + 1.0 - a
    c = 1.0 / _FPMIN
    d = 1.0 / b if abs(b) > _FPMIN else 1.0 / _FPMIN
    h = d
    for i in range(1, _ITMAX + 1):
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
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gammainc_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x)."""
    if a <= 0 or x < 0:
        return float("nan")
    if x == 0:
        return 1.0
    if x < a + 1.0:
        return 1.0 - _gser(a, x)
    return _gcf(a, x)


def chi2_sf(x: float, df: int) -> float | None:
    """Upper-tail chi-square probability ``P(X > x)``."""
    if df <= 0 or x < 0:
        return None
    if x == 0:
        return 1.0
    return _safe(gammainc_q(df / 2.0, x / 2.0))


def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, _ITMAX + 1):
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


def _betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def student_t_two_sided(t: float, df: int) -> float | None:
    """Two-sided Student-t tail probability."""
    if df <= 0:
        return None
    x = df / (df + t * t)
    return _safe(_betainc(df / 2.0, 0.5, x))


def _z_two_sided(z: float) -> float | None:
    return _safe(math.erfc(abs(z) / math.sqrt(2.0)))


# ── effect rows ──────────────────────────────────────────────────────────

def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "x", "primary")
    return False


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_scalar(value: Any) -> bool:
    """JSON scalar (bool/int/float/str) — the values a moderator may carry."""
    return isinstance(value, (bool, int, float, str))


def _is_scalar_list(value: Any) -> bool:
    """A list whose every entry is a JSON scalar (a multi-label value)."""
    return isinstance(value, list) and all(_is_scalar(item) for item in value)


def _json_roles(by_role: dict[str, Any]) -> dict[str, Any]:
    """Role values worth keeping on an effect row (JSON scalars/label lists)."""
    return {
        key: value
        for key, value in by_role.items()
        if _is_scalar(value) or _is_scalar_list(value)
    }


def _role_value(by_role: dict[str, Any], role: str) -> Any:
    value = by_role.get(role)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _scalar_fields(metric: dict[str, Any]) -> dict[str, Any]:
    """Scalar (or multi-label list) ``name → value`` pairs of a flat metric row.

    This is the by-field-name view the moderator resolver reads, so any coded
    variable (not just fields carrying a role) can act as a moderator. List
    values whose entries are all scalars are kept (multi-label moderators);
    nested structures (``roles``/``fields``/objects and lists of objects) and
    the ``_record`` index are excluded.
    """
    out: dict[str, Any] = {}
    for name, value in metric.items():
        if name in ("_record", "roles", "fields"):
            continue
        if _is_scalar(value) or _is_scalar_list(value):
            out[name] = value
    return out


def effects_from_metrics(
    metrics: Any,
    roles: dict[str, str] | None = None,
    *,
    hit_id: int = 0,
    owner: str = "",
    scheme: str = "",
) -> list[dict[str, Any]]:
    """Derive one effect row per metric that yields a usable effect size."""
    out: list[dict[str, Any]] = []
    for index, metric in enumerate(metrics if isinstance(metrics, list) else []):
        if not isinstance(metric, dict):
            continue
        by_role = metric_by_role(metric, roles)
        effect = derive_effect(by_role)
        if effect is None:
            continue
        study_id = _role_value(by_role, "study_id")
        out.append(
            {
                "hit_id": int(hit_id or 0),
                "owner": owner,
                "scheme": scheme,
                "study_id": str(study_id) if study_id not in (None, "") else str(hit_id or ""),
                "record": int(metric.get("_record", 0) or 0),
                "metric_index": index,
                "dv_name": str(_role_value(by_role, "dv_name") or ""),
                "domain": str(_role_value(by_role, "dv_domain") or ""),
                "contrast_type": str(_role_value(by_role, "contrast_type") or ""),
                "polarity": str(_role_value(by_role, "polarity") or ""),
                "eligible_primary": _truthy(_role_value(by_role, "eligible_primary")),
                "method": effect["method"],
                "sign_flipped": bool(effect["sign_flipped"]),
                "effect": float(effect["yi"]),
                "variance": float(effect["vi"]),
                "se": float(effect["sei"]),
                "roles": _json_roles(by_role),
                # Flattened metric/study scalars, so a field NAME can be used
                # as a moderator (see ``_moderator_value``).
                "fields": _scalar_fields(metric),
            }
        )
    return out


def build_effects(
    extractions: Any, codebook: Any = None
) -> list[dict[str, Any]]:
    """Flatten extractions to effect rows via the scheme's roles.

    ``extractions`` may be ``MetaExtraction`` models or plain dicts; ``codebook``
    is a raw or normalized v1/v2 codebook (``None`` falls back to the v1 role
    aliases). Only ``status == "extracted"`` rows contribute.
    """
    book = normalise_codebook(codebook) if codebook is not None else None
    roles = role_map(all_fields(book)) if book else None

    rows: list[dict[str, Any]] = []
    for ext in extractions if isinstance(extractions, list) else []:
        if str(_get(ext, "status", "extracted")) != "extracted":
            continue
        hit_id = int(_get(ext, "hit_id", 0) or 0)
        owner = str(_get(ext, "owner", "") or "")
        scheme = str(_get(ext, "scheme", "") or "")
        metrics = _get(ext, "dv_metrics", []) or []
        rows.extend(
            effects_from_metrics(
                metrics, roles, hit_id=hit_id, owner=owner, scheme=scheme
            )
        )
    return rows


def study_key(row: dict[str, Any]) -> str:
    value = row.get("study_id")
    if value not in (None, ""):
        return str(value)
    return str(row.get("hit_id", ""))


def primary_effects(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows flagged ``eligible_primary`` when any are flagged."""
    flagged = [r for r in rows if r.get("eligible_primary")]
    return flagged if flagged else list(rows)


def filter_effects(
    rows: list[dict[str, Any]],
    *,
    domain: str | None = None,
    families: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter derived effect rows by ``dv_domain`` and/or derivation method.

    ``domain`` matches the ``dv_domain`` role (the row's ``domain`` field).
    ``families`` matches the derivation ``method`` (e.g. ``cohens_d``,
    ``odds_ratio``), which the API exposes as the Analyze family filter.
    """
    out: list[dict[str, Any]] = []
    wanted = set(families) if families else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if domain is not None and str(row.get("domain") or "") != domain:
            continue
        if wanted is not None and row.get("method") not in wanted:
            continue
        out.append(row)
    return out


def _clean(rows: Any) -> tuple[list[float], list[float]]:
    y: list[float] = []
    v: list[float] = []
    for row in rows if isinstance(rows, list) else []:
        yi = _num(row.get("effect")) if isinstance(row, dict) else None
        vi = _num(row.get("variance")) if isinstance(row, dict) else None
        if yi is None or vi is None or vi <= 0:
            continue
        y.append(yi)
        v.append(vi)
    return y, v


# ── pooling ──────────────────────────────────────────────────────────────

def _empty_pool() -> dict[str, Any]:
    return {
        "k": 0,
        "estimate": None,
        "se": None,
        "ci_low": None,
        "ci_high": None,
        "tau2": 0.0,
        "q": 0.0,
        "q_df": 0,
        "q_p": None,
        "i2": 0.0,
        "p": None,
        "n_studies": 0,
    }


def pool_dl(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """DerSimonian-Laird random-effects pooled estimate."""
    clean_rows = [
        row
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
        and _num(row.get("effect")) is not None
        and (_num(row.get("variance")) or 0) > 0
    ]
    y, v = _clean(clean_rows)
    k = len(y)
    if k == 0:
        return _empty_pool()
    w = [1.0 / vi for vi in v]
    sw = sum(w)
    fe = sum(wi * yi for wi, yi in zip(w, y, strict=True)) / sw
    q = sum(wi * (yi - fe) ** 2 for wi, yi in zip(w, y, strict=True))
    df = k - 1
    c = sw - sum(wi * wi for wi in w) / sw
    tau2 = max(0.0, (q - df) / c) if c > 0 else 0.0
    ws = [1.0 / (vi + tau2) for vi in v]
    sws = sum(ws)
    estimate = sum(wi * yi for wi, yi in zip(ws, y, strict=True)) / sws
    se = math.sqrt(1.0 / sws) if sws > 0 else None
    i2 = max(0.0, (q - df) / q) * 100.0 if (q > 0 and df > 0) else 0.0
    q_p = chi2_sf(q, df)
    p = _z_two_sided(estimate / se) if se else None
    n_studies = len({study_key(r) for r in clean_rows})
    return {
        "k": k,
        "estimate": _safe(estimate),
        "se": _safe(se),
        "ci_low": _safe(estimate - _Z95 * se) if se else None,
        "ci_high": _safe(estimate + _Z95 * se) if se else None,
        "tau2": _safe(tau2),
        "q": _safe(q),
        "q_df": df,
        "q_p": q_p,
        "i2": _safe(i2),
        "p": p,
        "n_studies": n_studies,
    }


def _empty_fixed() -> dict[str, Any]:
    return {
        "k": 0,
        "estimate": None,
        "se": None,
        "ci_low": None,
        "ci_high": None,
        "tau2": 0.0,
        "q": 0.0,
        "q_df": 0,
        "q_p": None,
        "i2": 0.0,
        "p": None,
        "n_studies": 0,
    }


def pool_fixed(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fixed-effect (inverse-variance) pooled estimate.

    The ``tau2``/``i2`` fields are reported as ``0`` because the model assumes
    a common effect; the heterogeneity statistic ``q`` is still computed for the
    caller's reference.
    """
    clean_rows = [
        row
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
        and _num(row.get("effect")) is not None
        and (_num(row.get("variance")) or 0) > 0
    ]
    y, v = _clean(clean_rows)
    k = len(y)
    if k == 0:
        return _empty_fixed()
    w = [1.0 / vi for vi in v]
    sw = sum(w)
    estimate = sum(wi * yi for wi, yi in zip(w, y, strict=True)) / sw
    se = math.sqrt(1.0 / sw) if sw > 0 else None
    q = sum(wi * (yi - estimate) ** 2 for wi, yi in zip(w, y, strict=True))
    df = k - 1
    q_p = chi2_sf(q, df)
    p = _z_two_sided(estimate / se) if se else None
    return {
        "k": k,
        "estimate": _safe(estimate),
        "se": _safe(se),
        "ci_low": _safe(estimate - _Z95 * se) if se else None,
        "ci_high": _safe(estimate + _Z95 * se) if se else None,
        "tau2": 0.0,
        "q": _safe(q),
        "q_df": df,
        "q_p": q_p,
        "i2": 0.0,
        "p": p,
        "n_studies": len({study_key(r) for r in clean_rows}),
    }


def _study_blocks(rows: list[dict[str, Any]]) -> dict[str, list[int]]:
    blocks: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        blocks.setdefault(study_key(row), []).append(index)
    return blocks


def pool_two_level(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Two-level (effects nested in studies) variance components.

    Returns the method-of-moments within- and between-study tau-squared plus the
    three-level proportional variance decomposition (sampling / within / between).
    """
    y, v = _clean(rows)
    k = len(y)
    if k == 0:
        return {
            "k": 0,
            "n_studies": 0,
            "estimate": None,
            "se": None,
            "ci_low": None,
            "ci_high": None,
            "tau2_between": 0.0,
            "tau2_within": 0.0,
            "tau2_total": 0.0,
            "vbar": 0.0,
            "v_total": 0.0,
            "shares": {"sampling": 0.0, "within": 0.0, "between": 0.0},
            "var_sampling_share": 0.0,
            "var_within_share": 0.0,
            "var_between_share": 0.0,
            "i2_sampling": 0.0,
            "i2_within_alloc": 0.0,
            "i2_between_alloc": 0.0,
            "i2_between": 0.0,
            "i2_within": 0.0,
            "q_between": 0.0,
            "q_within": 0.0,
            "df_between": 0,
            "df_within": 0,
        }
    # Pair each cleaned (y, v) back to its row so the study grouping survives.
    clean_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and _num(row.get("effect")) is not None
        and _num(row.get("variance")) is not None
        and (_num(row.get("variance")) or 0) > 0
    ]
    blocks = _study_blocks(clean_rows)

    q_w = c_w = 0.0
    df_w = 0
    st_y: list[float] = []
    st_v: list[float] = []
    for idxs in blocks.values():
        ws = {i: 1.0 / v[i] for i in idxs}
        sw = sum(ws.values())
        ybar = sum(ws[i] * y[i] for i in idxs) / sw
        st_y.append(ybar)
        st_v.append(1.0 / sw)
        q_w += sum(ws[i] * (y[i] - ybar) ** 2 for i in idxs)
        c_w += sw - sum(wi * wi for wi in ws.values()) / sw
        df_w += max(0, len(idxs) - 1)
    tau2_w = max(0.0, (q_w - df_w) / c_w) if c_w > 0 else 0.0

    n_st = len(st_y)
    w = [1.0 / x for x in st_v]
    sw = sum(w)
    fe = sum(wi * yi for wi, yi in zip(w, st_y, strict=True)) / sw if sw else 0.0
    q_b = sum(wi * (yi - fe) ** 2 for wi, yi in zip(w, st_y, strict=True))
    c_b = sw - sum(wi * wi for wi in w) / sw
    tau2_b = max(0.0, (q_b - (n_st - 1)) / c_b) if c_b > 0 else 0.0

    # Reference two-stage model: stage 1 already fixed-effect aggregated each
    # study (st_y/st_v); stage 2 pools those with the between-study tau².
    stage2_w = [1.0 / (x + tau2_b) for x in st_v]
    sw2 = sum(stage2_w)
    if sw2 > 0:
        stage2_est = sum(wi * yi for wi, yi in zip(stage2_w, st_y, strict=True)) / sw2
        stage2_se: float | None = math.sqrt(1.0 / sw2)
    else:
        stage2_est = None
        stage2_se = None

    sv = sorted(v)
    nv = len(sv)
    vbar = (sv[nv // 2] if nv % 2 else 0.5 * (sv[nv // 2 - 1] + sv[nv // 2])) if nv else 0.0
    total = vbar + tau2_w + tau2_b
    shares = {
        "sampling": (vbar / total) if total > 0 else 0.0,
        "within": (tau2_w / total) if total > 0 else 0.0,
        "between": (tau2_b / total) if total > 0 else 0.0,
    }
    return {
        "k": k,
        "n_studies": n_st,
        "estimate": _safe(stage2_est),
        "se": _safe(stage2_se),
        "ci_low": _safe(stage2_est - _Z95 * stage2_se)
        if (stage2_est is not None and stage2_se is not None)
        else None,
        "ci_high": _safe(stage2_est + _Z95 * stage2_se)
        if (stage2_est is not None and stage2_se is not None)
        else None,
        "tau2_between": _safe(tau2_b),
        "tau2_within": _safe(tau2_w),
        "tau2_total": _safe(tau2_b + tau2_w),
        "vbar": _safe(vbar),
        "v_total": _safe(total),
        "shares": {key: _safe(val) for key, val in shares.items()},
        "var_sampling_share": _safe(shares["sampling"]),
        "var_within_share": _safe(shares["within"]),
        "var_between_share": _safe(shares["between"]),
        "i2_sampling": _safe(shares["sampling"] * 100.0),
        "i2_within_alloc": _safe(shares["within"] * 100.0),
        "i2_between_alloc": _safe(shares["between"] * 100.0),
        "i2_between": _safe(max(0.0, (q_b - (n_st - 1)) / q_b) * 100.0)
        if (q_b > 0 and n_st > 1)
        else 0.0,
        "i2_within": _safe(max(0.0, (q_w - df_w) / q_w) * 100.0)
        if (q_w > 0 and df_w > 0)
        else 0.0,
        "q_between": _safe(q_b),
        "q_within": _safe(q_w),
        "df_between": max(0, n_st - 1),
        "df_within": df_w,
    }


def _value_of(row: dict[str, Any], key: str) -> Any:
    if key in row and row.get(key) is not None:
        return row.get(key)
    roles = row.get("roles")
    if isinstance(roles, dict):
        return roles.get(key)
    return None


def _moderator_value(row: dict[str, Any], key: str) -> Any:
    """Resolve a moderator ``key`` that is either a field name or a role id.

    Lookup order: the effect row's flattened ``fields`` map (field name), then
    its ``roles`` map (role id), then the row's own keys (derived columns such
    as ``domain``/``dv_name`` or test-constructed rows). A stored list value
    (multi-label field) is passed through unchanged.
    """
    fields = row.get("fields")
    if isinstance(fields, dict) and key in fields:
        return fields.get(key)
    roles = row.get("roles")
    if isinstance(roles, dict) and key in roles:
        return roles.get(key)
    return row.get(key)


def _norm(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    return str(value or "").strip()


def _label_entries(value: Any) -> list[tuple[str, str]]:
    """``(normalised, display)`` label pairs a moderator value carries.

    A scalar yields one pair; a list is multi-label and yields one pair per
    distinct scalar entry (first-seen order, non-scalar entries ignored). An
    absent/empty value yields nothing.
    """
    items = value if isinstance(value, list) else [value]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not _is_scalar(item):
            continue
        label = _norm(item)
        if not label or label in seen:
            continue
        seen.add(label)
        out.append((label, str(item)))
    return out


def _is_missing(value: Any) -> bool:
    """True when a moderator value carries no usable label (None/""/[])."""
    if value is None or value == "":
        return True
    return not _label_entries(value)


def subgroup(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """Pool the effects separately at each level of ``key`` (role or column).

    A list-valued ``key`` is multi-label: the row joins **every** label's group
    so each label's statistics include all rows carrying it. Rows whose value
    is empty (``None``/``""``/``[]``) are skipped.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    labels: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        entries = _label_entries(_moderator_value(row, key))
        for value, label in entries:
            groups.setdefault(value, []).append(row)
            labels.setdefault(value, label)

    out = [
        {
            "value": value,
            "label": labels.get(value, value),
            "k": pool["k"],
            "n_studies": pool["n_studies"],
            "estimate": pool["estimate"],
            "se": pool["se"],
            "ci_low": pool["ci_low"],
            "ci_high": pool["ci_high"],
            "tau2": pool["tau2"],
            "i2": pool["i2"],
        }
        for value, group_rows in groups.items()
        for pool in [pool_dl(group_rows)]
    ]
    out.sort(key=lambda entry: (-(entry["k"] or 0), str(entry["label"]).lower()))

    qm = _between_group_q(out)
    return {
        "key": key,
        "groups": out,
        "qm": qm["qm"],
        "qm_df": qm["qm_df"],
        "qm_p": qm["qm_p"],
        # Aliases the UI reads; same values as the qm fields above.
        "q_between": qm["qm"],
        "q_between_df": qm["qm_df"],
        "q_between_p": qm["qm_p"],
        "k_groups": len(out),
    }


def _between_group_q(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Cochran's between-group Q over level-level pooled estimates."""
    usable = [
        entry
        for entry in entries
        if _num(entry.get("estimate")) is not None and (_num(entry.get("se")) or 0) > 0
    ]
    if len(usable) < 2:
        return {"qm": None, "qm_df": max(0, len(entries) - 1), "qm_p": None}
    weights = [1.0 / (float(entry["se"]) ** 2) for entry in usable]
    sw = sum(weights)
    mean = sum(
        wi * float(entry["estimate"]) for wi, entry in zip(weights, usable, strict=True)
    ) / sw
    qm = sum(
        wi * (float(entry["estimate"]) - mean) ** 2
        for wi, entry in zip(weights, usable, strict=True)
    )
    df = len(usable) - 1
    return {"qm": _safe(qm), "qm_df": df, "qm_p": chi2_sf(qm, df)}


# ── meta-regression ──────────────────────────────────────────────────────

def _design(
    rows: list[dict[str, Any]],
    terms: list[str],
    interactions: list[list[str]] | None = None,
) -> tuple[np.ndarray, list[str], list[str]]:
    """Design matrix ``X`` (intercept first) and column labels for ``terms``.

    Each term contributes its own base column(s) — a centred numeric column, a
    set of dummies whose most common level is the reference, or, for a
    list-valued (multi-label) term, one indicator column per distinct label
    (``1`` when the row's list contains it, else ``0``; labels sorted for a
    deterministic design). Each interaction pair ``[a, b]`` then contributes the
    elementwise product of every base column of ``a`` with every base column of
    ``b``, labelled ``"<col_a> * <col_b>"``. Pairs whose components produced no
    base column are skipped.
    """
    n = len(rows)
    columns: list[np.ndarray] = [np.ones(n, dtype=float)]
    names = ["Intercept"]
    used: list[str] = []
    term_columns: dict[str, list[int]] = {}
    for term in terms:
        base: list[int] = []
        raw = [_moderator_value(row, term) for row in rows]
        if any(isinstance(value, list) for value in raw):
            # Multi-label term: one indicator column per distinct label, so a
            # row carrying ["a", "b"] is 1 in both the ``a`` and ``b`` columns.
            row_labels = [
                {value for value, _ in _label_entries(item)} for item in raw
            ]
            levels = sorted({level for labels in row_labels for level in labels})
            if len(levels) < 2:
                term_columns[term] = base
                continue
            for level in levels:
                base.append(len(columns))
                columns.append(
                    np.array([1.0 if level in labels else 0.0 for labels in row_labels])
                )
                names.append(f"{term}:{level}")
            used.append(term)
            term_columns[term] = base
            continue
        clean = [value for value in raw if not _is_missing(value)]
        numeric = bool(clean) and all(_num(value) is not None for value in clean)
        if numeric and len({_num(value) for value in clean}) >= 2:
            xs = np.array([_num(value) if _num(value) is not None else 0.0 for value in raw])
            base.append(len(columns))
            columns.append(xs - xs.mean())
            names.append(term)
            used.append(term)
            term_columns[term] = base
            continue
        counts: dict[str, int] = {}
        for value in clean:
            counts[_norm(value)] = counts.get(_norm(value), 0) + 1
        if len(counts) < 2:
            term_columns[term] = base
            continue
        levels = sorted(counts, key=lambda lv: (-counts[lv], lv))
        for level in levels[1 : _MAX_MOD_LEVELS + 1]:
            base.append(len(columns))
            columns.append(
                np.array([1.0 if _norm(value) == level else 0.0 for value in raw])
            )
            names.append(f"{term}:{level}")
        used.append(term)
        term_columns[term] = base
    for pair in interactions or []:
        if len(pair) != 2:
            continue
        left, right = pair
        for i in term_columns.get(left, []):
            for j in term_columns.get(right, []):
                columns.append(columns[i] * columns[j])
                names.append(f"{names[i]} * {names[j]}")
    return np.column_stack(columns), names, used


def _cr1_cov(
    x: np.ndarray,
    weights: np.ndarray,
    resid: np.ndarray,
    clusters: list[str],
    cov_model: np.ndarray,
) -> np.ndarray | None:
    """Cluster-robust (CR1) sandwich covariance for a WLS fit.

    Clusters the score contributions by study so multiple effects from the same
    study are not treated as independent. Returns ``None`` when there are fewer
    than two clusters or the sample cannot support the correction.
    """
    n, p = x.shape
    groups: dict[str, list[int]] = {}
    for i, key in enumerate(clusters):
        groups.setdefault(key, []).append(i)
    g = len(groups)
    if g < 2 or g <= p or n <= p:
        return None
    meat = np.zeros((p, p), dtype=float)
    for idx in groups.values():
        score = x[idx].T @ (weights[idx] * resid[idx])
        meat += np.outer(score, score)
    correction = (g / (g - 1.0)) * ((n - 1.0) / (n - p))
    return correction * (cov_model @ meat @ cov_model)


def _full_rank_columns(x: np.ndarray, weights: np.ndarray) -> list[int]:
    """Indices of a maximal full-rank subset of design columns (keeps order)."""
    xw = np.sqrt(weights)[:, None] * x
    keep: list[int] = []
    rank = 0
    for j in range(xw.shape[1]):
        trial = xw[:, [*keep, j]]
        r = int(np.linalg.matrix_rank(trial, tol=1e-9))
        if r > rank:
            keep.append(j)
            rank = r
    return keep


def _covariance_ok(cov: np.ndarray | None) -> bool:
    """A usable covariance matrix is finite with a strictly positive diagonal."""
    if cov is None:
        return False
    diag = np.diag(cov)
    return bool(np.all(np.isfinite(cov)) and np.all(diag > 0))


def moderator(
    rows: list[dict[str, Any]],
    key: str,
    terms: list[str] | None = None,
    interactions: list[list[str]] | None = None,
) -> dict[str, Any]:
    """Weighted-least-squares meta-regression with a Wald (QM) omnibus test.

    ``key`` is either a field name or a role id (see :func:`_moderator_value`);
    it is the displayed label and joins the model when ``terms`` is empty.
    ``terms`` lists the moderator field names/roles/columns in the model. Categorical
    terms enter as dummies (most common level is the reference); numeric terms
    are mean-centred. ``interactions`` lists ``[a, b]`` pairs whose base columns
    multiply elementwise (numeric x numeric → one column, categorical x
    categorical → cross dummies, numeric x categorical → one column per
    dummy), labelled
    ``"<a> * <b>"``. Rows missing any moderator term or any interaction component
    are dropped (reported as ``n_dropped``) rather than silently imputed as zero,
    and the coefficient SEs use study-clustered CR1 robust covariance. R² is the
    proportional reduction in the between-study variance relative to the
    intercept-only DL model.
    """
    model_terms = [term for term in (terms or []) if term] or ([key] if key else [])
    pairs = [list(pair) for pair in (interactions or []) if len(pair) == 2]
    required = list(model_terms)
    for left, right in pairs:
        required.extend([left, right])
    clean_rows = [
        row
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
        and _num(row.get("effect")) is not None
        and (_num(row.get("variance")) or 0) > 0
    ]
    if required:
        kept_rows = [
            row
            for row in clean_rows
            if all(
                not _is_missing(_moderator_value(row, term)) for term in required
            )
        ]
    else:
        kept_rows = clean_rows
    n_dropped = len(clean_rows) - len(kept_rows)

    result: dict[str, Any] = {
        "role": key,
        "field": key,
        "terms": model_terms,
        "interactions": pairs,
        "names": [],
        "k": len(kept_rows),
        "n_dropped": n_dropped,
        "n_clusters": 0,
        "covariance": "model",
        "estimate": None,
        "se": None,
        "coefficients": [],
        "qm": None,
        "qm_df": 0,
        "qm_p": None,
        "r2": None,
        "r2_tau": None,
        "tau2": None,
        "note": "",
    }
    if n_dropped:
        result["note"] = (
            f"{n_dropped} effect(s) dropped for missing moderator values."
        )
    if len(kept_rows) < 3:
        if not n_dropped:
            result["note"] = "Too few effects for a moderator model."
        return result

    y = np.array([float(_num(row["effect"]) or 0.0) for row in kept_rows])
    v = np.array([float(_num(row["variance"]) or 0.0) for row in kept_rows])
    null = pool_dl(kept_rows)
    tau2 = float(null.get("tau2") or 0.0)
    weights = 1.0 / (v + tau2)
    x, names, used = _design(kept_rows, model_terms, pairs)
    # Rare moderator levels can make the dummy design collinear; keep a maximal
    # full-rank subset so an ill-conditioned inverse can never be returned.
    keep_cols = _full_rank_columns(x, weights)
    if len(keep_cols) < 2:
        result["note"] = "No moderator with two or more independent levels."
        return result
    if len(keep_cols) < x.shape[1]:
        x = x[:, keep_cols]
        names = [names[i] for i in keep_cols]
    result["names"] = names

    xtwx = x.T @ (weights[:, None] * x)
    xtwy = x.T @ (weights * y)
    cov_model = np.linalg.pinv(xtwx)
    if not _covariance_ok(cov_model):
        result["note"] = "Covariance is not estimable for this moderator."
        return result
    beta = cov_model @ xtwy
    resid = y - x @ beta

    clusters = [study_key(row) for row in kept_rows]
    n_clusters = len(set(clusters))
    cov_robust = (
        _cr1_cov(x, weights, resid, clusters, cov_model)
        if n_clusters > x.shape[1]
        else None
    )
    if cov_robust is not None and _covariance_ok(cov_robust):
        cov = cov_robust
        result["covariance"] = "CR1"
    else:
        cov = cov_model
        result["covariance"] = "model"
    result["n_clusters"] = n_clusters

    # Residual between-study variance (method of moments, same weights).
    sw = float(weights.sum())
    c = sw - float((weights * weights).sum()) / sw if sw > 0 else 0.0
    q_res = float((weights * resid * resid).sum())
    p = x.shape[1]
    tau2_res = max(0.0, (q_res - (len(y) - p)) / c) if c > 0 else 0.0
    mean_w = float((weights * y).sum()) / sw if sw > 0 else 0.0
    q_null = float((weights * (y - mean_w) ** 2).sum())
    tau2_null = max(0.0, (q_null - (len(y) - 1)) / c) if c > 0 else 0.0
    r2_tau = 1.0 - tau2_res / tau2_null if tau2_null > 0 else None
    r2 = 1.0 - q_res / q_null if q_null > 0 else None

    coefficients = []
    for i, name in enumerate(names):
        se_i = math.sqrt(max(float(cov[i, i]), 0.0))
        estimate_i = float(beta[i])
        z = estimate_i / se_i if se_i > 0 else None
        coefficients.append(
            {
                "term": name,
                "estimate": _safe(estimate_i),
                "se": _safe(se_i),
                "ci_low": _safe(estimate_i - _Z95 * se_i) if se_i > 0 else None,
                "ci_high": _safe(estimate_i + _Z95 * se_i) if se_i > 0 else None,
                "z": _safe(z),
                "p": _z_two_sided(z) if z is not None else None,
            }
        )

    qm = qm_df = qm_p = None
    if p > 1:
        idx = list(range(1, p))
        bt = beta[idx]
        vt = cov[np.ix_(idx, idx)]
        if _covariance_ok(vt):
            qm = float(bt @ np.linalg.pinv(vt) @ bt)
            if np.isfinite(qm):
                qm_df = len(idx)
                qm_p = chi2_sf(qm, qm_df)
            else:
                qm = None

    result.update(
        {
            "estimate": _safe(float(beta[0])),
            "se": _safe(math.sqrt(max(float(cov[0, 0]), 0.0))),
            "coefficients": coefficients,
            "qm": _safe(qm),
            "qm_df": qm_df or 0,
            "qm_p": qm_p,
            "r2": _safe(r2),
            "r2_tau": _safe(r2_tau),
            "tau2": _safe(tau2),
            "used_terms": used,
        }
    )
    return result


# ── publication bias / influence ─────────────────────────────────────────

def _wls_terms(y: list[float], x: list[float], w: list[float]) -> dict[str, Any]:
    """Weighted least squares ``y = intercept + slope * x`` with fixed weights.

    The coefficient covariance uses ``(X'WX)^-1`` (sampling variances treated as
    known — the Egger / PET-PEESE convention). Returns ``None`` terms when there
    are fewer than three effects or the design is singular.
    """
    k = len(y)
    out: dict[str, Any] = {
        "intercept": None,
        "se": None,
        "t": None,
        "p": None,
        "slope": None,
        "slope_se": None,
        "slope_p": None,
    }
    if k < 3:
        return out
    yy = np.asarray(y, dtype=float)
    xx = np.asarray(x, dtype=float)
    ww = np.asarray(w, dtype=float)
    design = np.column_stack([np.ones(k), xx])
    xtwx = design.T @ (ww[:, None] * design)
    try:
        cov = np.linalg.inv(xtwx)
    except np.linalg.LinAlgError:
        return out
    beta = cov @ (design.T @ (ww * yy))
    se_i = math.sqrt(max(float(cov[0, 0]), 0.0))
    se_s = math.sqrt(max(float(cov[1, 1]), 0.0))
    t_i = float(beta[0]) / se_i if se_i > 0 else None
    t_s = float(beta[1]) / se_s if se_s > 0 else None
    out.update(
        {
            "intercept": _safe(float(beta[0])),
            "se": _safe(se_i),
            "t": _safe(t_i),
            "p": student_t_two_sided(t_i, k - 2) if t_i is not None else None,
            "slope": _safe(float(beta[1])),
            "slope_se": _safe(se_s),
            "slope_p": student_t_two_sided(t_s, k - 2) if t_s is not None else None,
        }
    )
    return out


def egger(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Egger's regression test (WLS of effect on standard error, weights 1/vi)."""
    y, v = _clean(rows)
    return {
        "k": len(y),
        **_wls_terms(y, [math.sqrt(vi) for vi in v], [1.0 / vi for vi in v]),
    }


def pet_peese(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """PET-PEESE (Stanley & Doucouliagos) with weights ``1/vi``.

    PET regresses the effect on its standard error, PEESE on the variance. The
    intercept is the bias-adjusted estimate; PEESE is preferred when the PET
    intercept differs from zero (two-sided ``p < .05``), otherwise PET.
    """
    y, v = _clean(rows)
    se = [math.sqrt(vi) for vi in v]
    weights = [1.0 / vi for vi in v]
    pet = _wls_terms(y, se, weights)
    peese = _wls_terms(y, v, weights)
    pet_p = pet["p"]
    recommended = "PEESE" if (pet_p is not None and pet_p < 0.05) else "PET"
    return {
        "k": len(y),
        "pet": {key: pet[key] for key in ("intercept", "se", "t", "p")},
        "peese": {key: peese[key] for key in ("intercept", "se", "t", "p")},
        "recommended": recommended,
    }


# ── trim-and-fill ────────────────────────────────────────────────────────

def _dl_arrays(y: Any, v: Any) -> tuple[float | None, float | None]:
    """DL random-effects estimate/SE from raw effect and variance arrays."""
    k = len(y)
    if k == 0:
        return None, None
    w = [1.0 / float(vi) for vi in v]
    sw = sum(w)
    fe = sum(wi * float(yi) for wi, yi in zip(w, y, strict=True)) / sw
    q = sum(wi * (float(yi) - fe) ** 2 for wi, yi in zip(w, y, strict=True))
    c = sw - sum(wi * wi for wi in w) / sw
    tau2 = max(0.0, (q - (k - 1)) / c) if c > 0 else 0.0
    ws = [1.0 / (float(vi) + tau2) for vi in v]
    sws = sum(ws)
    if sws <= 0:
        return None, None
    est = sum(wi * float(yi) for wi, yi in zip(ws, y, strict=True)) / sws
    return est, math.sqrt(1.0 / sws)


def _ranks_first(values: Any) -> np.ndarray:
    """Ranks 1..n with ties broken by first occurrence (``ties.method="first"``)."""
    a = np.asarray(values, dtype=float)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=float)
    ranks[order] = np.arange(1, len(a) + 1, dtype=float)
    return ranks


def trim_and_fill(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Duval-Tweedie trim-and-fill (L0 estimator) with DL random effects.

    Metafor semantics: with ``k`` observed effects the truncated-set intercept
    ``theta`` (DL fit after trimming the most extreme ``k0`` effects on the
    over-represented side) centres the *full* set, whose ``|yi - theta|`` values
    are ranked with ties broken by first occurrence. The number of missing
    studies is ``L0 = round((4*Sr - k*(k+1)) / (2k - 1))`` with ``Sr`` the rank
    sum of the positively centred values; ``k0`` is iterated until it stabilises
    and a converged non-zero value is never discarded. Mirrors of the trimmed
    studies are then imputed about ``theta`` and everything is re-pooled. Both
    imputation sides are tried and the one with the larger ``k0`` is reported
    (ties follow the sign of the observed estimate).
    """
    y_list, v_list = _clean(rows)
    n = len(y_list)
    out: dict[str, Any] = {
        "k": n,
        "k0": None,
        "side": None,
        "estimate": None,
        "se": None,
        "ci_low": None,
        "ci_high": None,
        "estimate_raw": None,
        "se_raw": None,
    }
    if n == 0:
        return out
    y = np.asarray(y_list, dtype=float)
    v = np.asarray(v_list, dtype=float)
    raw_est, raw_se = _dl_arrays(y, v)
    out["estimate_raw"] = _safe(raw_est)
    out["se_raw"] = _safe(raw_se)
    if n < 4:
        return out

    def run(trim_side: str) -> tuple[int, float | None, float | None]:
        # ``trim_side`` is where the imputed studies are placed; orient the data
        # so the over-represented side is always the upper (trimmed) side.
        flip = trim_side == "right"
        z = -y if flip else y.copy()
        vz = v.copy()
        k = n
        k0 = 0
        for _ in range(100):
            order = np.argsort(z, kind="mergesort")
            keep = order[: k - k0] if k0 > 0 else np.arange(k)
            theta, _ = _dl_arrays(z[keep], vz[keep])
            if theta is None:
                break
            x = z - theta
            signed = np.sign(x) * _ranks_first(np.abs(x))
            rank_sum = float(np.sum(signed[signed > 0]))
            new_k0 = int(
                max(0, min(k - 1, round(float((4.0 * rank_sum - k * (k + 1)) / (2 * k - 1)))))
            )
            if new_k0 == k0:
                break
            k0 = new_k0
        # Recompute the intercept for the converged k0 (the loop's theta lags one
        # update when k0 changed on the final pass).
        order = np.argsort(z, kind="mergesort")
        keep = order[: k - k0] if k0 > 0 else np.arange(k)
        theta, _ = _dl_arrays(z[keep], vz[keep])
        if theta is None:
            theta = raw_est or 0.0
        if k0 > 0:
            trimmed = order[k - k0 :]
            all_z = np.concatenate([z, 2.0 * theta - z[trimmed]])
            all_v = np.concatenate([vz, vz[trimmed]])
        else:
            all_z, all_v = z, vz
        all_y = -all_z if flip else all_z
        est, se = _dl_arrays(all_y, all_v)
        return k0, est, se

    k_left, est_left, se_left = run("left")
    k_right, est_right, se_right = run("right")
    if k_right > k_left or (k_right == k_left and (raw_est or 0.0) < 0.0):
        k0, est, se, side = k_right, est_right, se_right, "right"
    else:
        k0, est, se, side = k_left, est_left, se_left, "left"
    out.update(
        {
            "k0": k0,
            "side": side,
            "estimate": _safe(est),
            "se": _safe(se),
            "ci_low": _safe(est - _Z95 * se) if (est is not None and se is not None) else None,
            "ci_high": _safe(est + _Z95 * se) if (est is not None and se is not None) else None,
        }
    )
    return out


def p_curve(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """p-curve right-skew test over the coded ``p`` role.

    Among the significant effects (``p < .05``), the proportion below ``.025`` is
    tested against the null of 0.5 with a one-sided binomial test: a significant
    excess of small p-values is evidence of evidential value (right skew).
    """
    values: list[float] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        p = _num(_value_of(row, "p"))
        if p is not None:
            values.append(p)
    significant = [p for p in values if p < 0.05]
    n = len(significant)
    k_low = sum(1 for p in significant if p < 0.025)
    out: dict[str, Any] = {
        "n_significant": n,
        "n_p_lt_025": k_low,
        "p_half": None,
        "evidential": None,
        "note": "",
    }
    if n == 0:
        out["note"] = "No coded p-values below .05; evidential value not assessable."
        return out
    p_half = 1.0 if k_low <= 0 else _safe(_betainc(float(k_low), float(n - k_low + 1), 0.5))
    out["p_half"] = p_half
    out["evidential"] = bool(p_half is not None and p_half < 0.05)
    out["note"] = (
        f"{k_low} of {n} significant p-values fell below .025 "
        f"(one-sided binomial p = {p_half:.4f})."
        if p_half is not None
        else f"{k_low} of {n} significant p-values fell below .025."
    )
    return out


def publication_bias(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Combined small-study / publication-bias battery for one effect set."""
    row_list = rows if isinstance(rows, list) else []
    y, _ = _clean(row_list)
    return {
        "k": len(y),
        "k_total": len(row_list),
        "egger": egger(row_list),
        "pet_peese": pet_peese(row_list),
        "trim_and_fill": trim_and_fill(row_list),
        "p_curve": p_curve(row_list),
    }


def leave_one_out(rows: list[dict[str, Any]], by: str = "effect") -> dict[str, Any]:
    """DL estimate omitting each effect (or study); flags influential units.

    A unit is influential when the leave-one-out 95% CI excludes the full-sample
    pooled estimate.
    """
    clean_rows = [
        row
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
        and _num(row.get("effect")) is not None
        and (_num(row.get("variance")) or 0) > 0
    ]
    full = pool_dl(clean_rows)
    groups: dict[str, list[int]] = {}
    if by == "study":
        for index, row in enumerate(clean_rows):
            groups.setdefault(study_key(row), []).append(index)
    else:
        for index, row in enumerate(clean_rows):
            dv = row.get("dv_name") or row.get("domain") or str(index)
            groups.setdefault(f"{study_key(row)} · {dv} · {index}", [index])

    out: list[dict[str, Any]] = []
    full_estimate = full.get("estimate")
    n_rows = len(clean_rows)
    group_items = list(groups.items())
    # Precompute the omitted-index sets so they are not rebuilt inside the
    # per-unit full-range scan (which made this O(n²) per unit).
    omit_sets = {name: set(idxs) for name, idxs in group_items}
    for name, _idxs in group_items:
        omit = omit_sets[name]
        keep = [i for i in range(n_rows) if i not in omit]
        if len(keep) < 2:
            continue
        res = pool_dl([clean_rows[i] for i in keep])
        lo, hi = res.get("ci_low"), res.get("ci_high")
        influential = bool(
            full_estimate is not None
            and lo is not None
            and hi is not None
            and (lo > full_estimate or hi < full_estimate)
        )
        out.append(
            {
                "omitted": name,
                "k": res["k"],
                "estimate": res["estimate"],
                "se": res["se"],
                "ci_low": lo,
                "ci_high": hi,
                "tau2": res["tau2"],
                "i2": res["i2"],
                "delta": _safe(res["estimate"] - full_estimate)
                if (res["estimate"] is not None and full_estimate is not None)
                else None,
                "influential": influential,
            }
        )
    return {"full": full, "by": by, "rows": out}


# ── forest plot data ─────────────────────────────────────────────────────

def forest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Forest-plot data: per-effect CIs + random-effects weights and the pool."""
    clean_rows = [
        row
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
        and _num(row.get("effect")) is not None
        and (_num(row.get("variance")) or 0) > 0
    ]
    pooled = pool_dl(clean_rows)
    tau2 = float(pooled.get("tau2") or 0.0)
    weights = [1.0 / (float(_num(row["variance"]) or 0.0) + tau2) for row in clean_rows]
    total = sum(weights)
    entries = []
    for row, weight in zip(clean_rows, weights, strict=True):
        effect = float(_num(row["effect"]) or 0.0)
        variance = float(_num(row["variance"]) or 0.0)
        se = math.sqrt(variance)
        study = study_key(row)
        dv = str(row.get("dv_name") or "")
        entries.append(
            {
                "study_id": study,
                "hit_id": row.get("hit_id"),
                "dv_name": dv,
                "label": f"{study} — {dv}" if dv else study,
                "domain": row.get("domain") or "",
                "effect": _safe(effect),
                "se": _safe(se),
                "ci_low": _safe(effect - _Z95 * se),
                "ci_high": _safe(effect + _Z95 * se),
                "weight": _safe(weight / total * 100.0 if total > 0 else 0.0),
                "method": row.get("method") or "",
                "eligible_primary": bool(row.get("eligible_primary")),
            }
        )
    return {"k": pooled["k"], "n_studies": pooled["n_studies"], "pooled": pooled, "rows": entries}
