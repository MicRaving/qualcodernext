"""Field roles — the single controlled vocabulary for meta scheme fields.

Contract (``docs/meta-port.md`` §2): a scheme field may carry
``role: <id> | null``. Semantics (prompting, validation, effect derivation,
analysis) are driven by the role, never by a hardcoded field name: field names
are user data.

This module must stay import-light — it is imported by ``meta_scheme``,
``meta_effects``, ``meta_prompt`` and ``meta_extract`` — so it deliberately
does NOT import ``meta_extract``/``meta_prompt`` (cycle guard).
"""

from __future__ import annotations

from typing import Any

# ── controlled vocabulary ────────────────────────────────────────────────

STUDY_ROLES = frozenset(
    {
        "study_id",
        "parent_study_id",
        "year",
        "doi",
        "authors",
        "title",
        "description",
        "notes",
        "design",
        "country",
        "setting",
        "sample_n",
        "intervention_type",
        "intervention_id",
        "dataset_url",
        "publication",
        "fully_within",
    }
)

METRIC_ROLES = frozenset(
    {
        "dv_name",
        "dv_domain",
        "score_types",
        "discernment",
        "polarity",
        "veracity",
        "scale_type",
        "scale_points",
        "scale_min",
        "scale_max",
        "contrast_type",
        "contrast_role",
        "eligible_primary",
        "comparison_label",
        "group1_label",
        "group2_label",
        "timepoint_1",
        "timepoint_2",
        "posttest_type",
        "delay_weeks",
        "n1",
        "n2",
        "n_total",
        "m1",
        "m2",
        "sd1",
        "sd2",
        "n1_pre",
        "m1_pre",
        "sd1_pre",
        "n2_pre",
        "m2_pre",
        "sd2_pre",
        "n1_post",
        "m1_post",
        "sd1_post",
        "n2_post",
        "m2_post",
        "sd2_post",
        "t",
        "df_num",
        "df_den",
        "F",
        "chi2",
        "z",
        "r",
        "p",
        "p_censored",
        "yi",
        "vi",
        "sei",
        "d",
        "g",
        "d_ci_low",
        "d_ci_high",
        "g_ci_low",
        "g_ci_high",
        "d_se",
        "g_se",
        "or",
        "or_ci_low",
        "or_ci_high",
        "log_odds",
        "rr",
        "rr_ci_low",
        "rr_ci_high",
        "beta",
        "beta_se",
        "beta_ci_low",
        "beta_ci_high",
        "eta2p",
        "eta2p_ci_low",
        "eta2p_ci_high",
        "effect_type_reported",
        "effect_favors",
        "effect_direction_meaning",
        "conversion_method",
        "conversion_inputs",
        "cell_descriptives",
        "source_location",
        "source_quote",
        "missing_reason",
    }
)

ALL_ROLES = STUDY_ROLES | METRIC_ROLES

#: ``polarity`` values (contract §2).
POLARITY_HIGHER_IS_BETTER = "higher_is_better"
POLARITY_HIGHER_IS_WORSE = "higher_is_worse"
POLARITY_VALUES = (POLARITY_HIGHER_IS_BETTER, POLARITY_HIGHER_IS_WORSE)

#: v1 reference compatibility: before roles existed the reference coder used
#: these field names. The bridge is only consulted for v1 codebooks whose
#: fields carry no role, so v1 projects keep normalising exactly as before.
#: It is metadata, not logic: every consumer still goes through a role id.
LEGACY_ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    # study
    "study_id": ("Study_ID", "study_id"),
    "parent_study_id": ("Parent_Study_ID", "parent_study_id"),
    "year": ("Year", "year"),
    "doi": ("DOI", "doi"),
    "authors": ("Authors", "authors"),
    "title": ("Title", "title"),
    "description": ("description", "Description", "Study_Description"),
    "notes": ("Rationale_Notes", "notes"),
    "design": ("within_between", "design"),
    "country": ("Country", "country"),
    "setting": ("Setting", "setting"),
    "sample_n": ("sample_n", "Sample_N", "N_Analyzed", "N_Recruited", "N"),
    "intervention_type": ("Intervention_Type", "intervention_type"),
    "intervention_id": ("Intervention_ID", "intervention_id"),
    "dataset_url": ("dataset_url", "Dataset_URL", "data_url"),
    "publication": ("Publication", "Publication_Type", "Publication_Category"),
    "fully_within": ("Fully_Within", "fully_within"),
    # metric identity / metadata
    "dv_name": ("dv_name",),
    "dv_domain": ("dv_domain",),
    "score_types": ("score_types",),
    "discernment": ("discernment_defined_as", "discernment"),
    "polarity": ("dv_polarity", "polarity"),
    "veracity": ("veracity",),
    "scale_type": ("scale_type",),
    "scale_points": ("scale_points",),
    "scale_min": ("scale_min",),
    "scale_max": ("scale_max",),
    "contrast_type": ("contrast_type",),
    "contrast_role": ("contrast_role",),
    "eligible_primary": ("eligible_primary",),
    "comparison_label": ("comparison_label",),
    "group1_label": ("group1_label",),
    "group2_label": ("group2_label",),
    "timepoint_1": ("timepoint_1",),
    "timepoint_2": ("timepoint_2",),
    "posttest_type": ("posttest_type",),
    "delay_weeks": ("delay_weeks",),
    # descriptives
    "n1": ("n1i", "n1", "n_t"),
    "n2": ("n2i", "n2", "n_c"),
    "n_total": ("n_total", "N", "n"),
    "m1": ("m1i", "m1", "m_t"),
    "m2": ("m2i", "m2", "m_c"),
    "sd1": ("sd1i", "sd1", "sd_t"),
    "sd2": ("sd2i", "sd2", "sd_c"),
    "n1_pre": ("n1i_pre", "n1_pre"),
    "m1_pre": ("m1i_pre", "m1_pre"),
    "sd1_pre": ("sd1i_pre", "sd1_pre"),
    "n2_pre": ("n2i_pre", "n2_pre"),
    "m2_pre": ("m2i_pre", "m2_pre"),
    "sd2_pre": ("sd2i_pre", "sd2_pre"),
    "n1_post": ("n1i_post", "n1_post"),
    "m1_post": ("m1i_post", "m1_post"),
    "sd1_post": ("sd1i_post", "sd1_post"),
    "n2_post": ("n2i_post", "n2_post"),
    "m2_post": ("m2i_post", "m2_post"),
    "sd2_post": ("sd2i_post", "sd2_post"),
    # inferential statistics
    "t": ("t_val", "t"),
    "df_num": ("df_num",),
    "df_den": ("df_den",),
    "F": ("F_val", "F", "f"),
    "chi2": ("chi2_val", "chi2"),
    "z": ("z_val", "z"),
    "r": ("r_val", "r"),
    "p": ("p_val", "p"),
    "p_censored": ("p_censored",),
    # effect sizes
    "yi": ("yi",),
    "vi": ("vi",),
    "sei": ("sei",),
    "d": ("d_val", "d"),
    "g": ("g_val", "g"),
    "d_ci_low": ("d_ci_low",),
    "d_ci_high": ("d_ci_high",),
    "g_ci_low": ("g_ci_low",),
    "g_ci_high": ("g_ci_high",),
    "d_se": ("d_se",),
    "g_se": ("g_se",),
    "or": ("odds_ratio", "or"),
    "or_ci_low": ("or_ci_low",),
    "or_ci_high": ("or_ci_high",),
    "log_odds": ("log_odds",),
    "rr": ("risk_ratio", "rr"),
    "rr_ci_low": ("rr_ci_low",),
    "rr_ci_high": ("rr_ci_high",),
    "beta": ("beta_val", "beta"),
    "beta_se": ("beta_se",),
    "beta_ci_low": ("beta_ci_low",),
    "beta_ci_high": ("beta_ci_high",),
    "eta2p": ("eta2_p", "eta2p"),
    "eta2p_ci_low": ("eta2_p_ci_low", "eta2p_ci_low"),
    "eta2p_ci_high": ("eta2_p_ci_high", "eta2p_ci_high"),
    # provenance
    "effect_type_reported": ("effect_size_type_reported", "effect_type_reported"),
    "effect_favors": ("effect_favors",),
    "effect_direction_meaning": ("effect_direction_meaning",),
    "conversion_method": ("conversion_method",),
    "conversion_inputs": ("conversion_inputs",),
    "cell_descriptives": ("cell_descriptives",),
    "source_location": ("source_location",),
    "source_quote": ("source_quote",),
    "missing_reason": ("missing_metrics_reason", "missing_reason"),
}

#: Canonical write-back name per role when no role map is available (v1 path).
CANONICAL_FIELD: dict[str, str] = {
    role: aliases[0] for role, aliases in LEGACY_ROLE_ALIASES.items()
}


# ── helpers ──────────────────────────────────────────────────────────────

def normalise_role(role: object) -> str | None:
    """Return a valid role id or ``None``."""
    if not isinstance(role, str):
        return None
    role = role.strip()
    return role if role in ALL_ROLES else None


def role_map(fields: object) -> dict[str, str]:
    """Map ``{field_name: role}`` for every field that carries a valid role.

    ``fields`` is a list of field dicts (or a single field dict). Fields
    without a role, without a name, or with an unknown role are skipped.
    """
    if isinstance(fields, dict):
        fields = [fields]
    if not isinstance(fields, list):
        return {}
    out: dict[str, str] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        role = normalise_role(field.get("role"))
        if isinstance(name, str) and name and role:
            out[name] = role
    return out


def value_by_role(record: object, roles: dict[str, str], role: str) -> Any:
    """Value of the field whose role is ``role`` (``None`` when absent)."""
    if not isinstance(record, dict):
        return None
    for name, mapped in roles.items():
        if mapped == role:
            return record.get(name)
    return None


def record_by_role(record: object, roles: dict[str, str]) -> dict[str, Any]:
    """Role-keyed view of a record using an explicit ``{name: role}`` map."""
    out: dict[str, Any] = {}
    if not isinstance(record, dict):
        return out
    for name, role in roles.items():
        if name in record and record[name] is not None:
            out[role] = record[name]
    return out


def metric_by_role(record: object, roles: dict[str, str] | None = None) -> dict[str, Any]:
    """Collapse a raw metric/record to ``{role: value}``.

    When ``roles`` is given (a ``role_map``), only mapped fields are used.
    Otherwise the v1 reference aliases are consulted so legacy extractions
    keep normalising without hardcoded logic in the consumers.
    """
    if not isinstance(record, dict):
        return {}
    if roles:
        return record_by_role(record, roles)
    out: dict[str, Any] = {}
    for role, aliases in LEGACY_ROLE_ALIASES.items():
        for alias in aliases:
            if record.get(alias) is not None:
                out[role] = record[alias]
                break
    return out


def write_role_value(
    metric: dict[str, Any], roles: dict[str, str] | None, role: str, value: Any
) -> bool:
    """Write a derived value back to its field name (roles) or canonical name.

    Returns ``True`` when a field was written. A role-mapped write returns
    ``False`` when the scheme defines no field for that role, so callers can
    fall back to a canonical column.
    """
    if roles:
        for name, mapped in roles.items():
            if mapped == role:
                metric[name] = value
                return True
        return False
    canonical = CANONICAL_FIELD.get(role)
    if canonical:
        metric[canonical] = value
        return True
    return False
