"""APA-style methods/results report (contract §9).

Assembles a Markdown or DOCX document from the same numbers the Analyze tab
shows: the configured eligibility criteria, the PRISMA selection counts, the
extraction/effect-size method, the pooled estimate and heterogeneity, and the
inter-rater reliability. ``python-docx`` is available; no other new deps.
"""

from __future__ import annotations

import io
import json
import math
from collections import Counter
from datetime import datetime
from typing import Any

from qualcoder_api.persistence.repo.meta_repo import MetaRepository
from qualcoder_api.services import (
    meta_agreement,
    meta_analysis,
    meta_bayes,
    meta_multiverse,
    meta_prisma,
    meta_summary,
)
from qualcoder_api.services.meta_scheme import normalise_codebook


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(number):
        return "-"
    return f"{number:.{digits}f}"


def _fmt_p(value: Any) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(number):
        return "-"
    if number < 0.001:
        return "< .001"
    return f"{number:.3f}".lstrip("0")


def _ci(low: Any, high: Any, digits: int = 2) -> str:
    return f"[{_fmt(low, digits)}, {_fmt(high, digits)}]"


# ── context assembly ─────────────────────────────────────────────────────

async def _resolve_scheme(repo: MetaRepository, extractions: list[Any], scheme: str | None) -> tuple[str, Any]:
    if scheme:
        row = await repo.get_scheme(name=scheme)
        return scheme, row
    counts: Counter = Counter(
        str(_get(ext, "scheme", ""))
        for ext in extractions
        if str(_get(ext, "status", "")) == "extracted"
    )
    if not counts:
        return "", None
    name = counts.most_common(1)[0][0]
    return name, await repo.get_scheme(name=name)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _codebook_of(scheme_row: Any) -> dict[str, Any]:
    if scheme_row is None or not scheme_row.codebook:
        return {}
    try:
        return normalise_codebook(json.loads(scheme_row.codebook))
    except (TypeError, ValueError):
        return normalise_codebook({})


def _risk_paragraphs(criteria: list[Any]) -> list[str]:
    if not criteria:
        return ["No inclusion criteria were configured; records were included when "
                "every recorded verdict was affirmative."]
    gating = [c for c in criteria if int(_get(c, "gating", 1) or 0)]
    lines = []
    for index, criterion in enumerate(gating, start=1):
        label = str(_get(criterion, "label", "") or _get(criterion, "key", ""))
        prompt = str(_get(criterion, "prompt_text", "") or "")
        pass_values = ", ".join(str(v) for v in (_get(criterion, "pass_values", []) or ["yes"]))
        text = f"(C{index}) {label}"
        if prompt:
            text += f" — {prompt}"
        text += f"; passing value(s): {pass_values}."
        lines.append(text)
    return [" ".join(lines), "Records failing any gating criterion were excluded; "
            "non-gating criteria were recorded as informational."]


async def build_report(
    session: Any,
    *,
    title: str | None = None,
    scheme: str | None = None,
    primary: bool = True,
    owner: str | None = None,
) -> dict[str, Any]:
    """Gather the report context from the meta pipeline.

    ``owner`` scopes the extraction and screening numbers to one coder so a
    per-rater report never mixes in other coders' rows.
    """
    repo = MetaRepository(session)
    hits = await repo.list_hits()
    criteria = await repo.list_criteria()
    screenings = await repo.list_screening(owner=owner)
    documents = await repo.list_documents()
    extractions = await repo.list_extractions(owner=owner)
    scheme_name, scheme_row = await _resolve_scheme(repo, extractions, scheme)
    codebook = _codebook_of(scheme_row)

    prisma = meta_prisma.prisma_counts(
        hits, criteria, screenings, documents, extractions
    )
    selected = [
        ext
        for ext in extractions
        if str(_get(ext, "status", "")) == "extracted"
        and (not scheme_name or str(_get(ext, "scheme", "")) == scheme_name)
    ]
    consensus: dict[str, Any] | None = None
    if owner is None and selected:
        # Consensus synthesis: combine every coder's rows (minus unresolved
        # conflicts) instead of pooling one coder's rows. An explicit owner
        # keeps the per-rater report scope below.
        from qualcoder_api.services import meta_consensus

        merged: list[Any] = []
        consensus = {
            "n_hits": 0,
            "n_groups": 0,
            "n_single_owner": 0,
            "n_consensus_units": 0,
            "n_fields_unanimous": 0,
            "n_master_resolved": 0,
            "n_dropped_conflicts": 0,
            "n_dropped_metrics": 0,
        }
        by_scheme: dict[str, list[Any]] = {}
        for ext in selected:
            by_scheme.setdefault(str(_get(ext, "scheme", "")), []).append(ext)
        for group_scheme in sorted(by_scheme):
            group_book = _codebook_of(await repo.get_scheme(name=group_scheme))
            group_rows, group_report = meta_consensus.build_consensus_rows(
                by_scheme[group_scheme], group_book or None
            )
            for key, value in group_report.items():
                if isinstance(value, (int, float)):
                    consensus[key] = consensus.get(key, 0) + value
            merged.extend(group_rows)
        consensus["n_hits"] = len({str(_get(ext, "hit_id", "")) for ext in selected})
        selected = merged
    effects = meta_analysis.build_effects(selected, codebook or None)
    pooling_rows = meta_analysis.primary_effects(effects) if primary else effects
    pooled = meta_analysis.pool_dl(pooling_rows)
    two_level = meta_analysis.pool_two_level(pooling_rows)
    egger = meta_analysis.egger(pooling_rows)
    bias = meta_analysis.publication_bias(pooling_rows)
    bayes = meta_bayes.bayes_pool(pooling_rows)
    bayes["sensitivity"] = meta_bayes.bayes_sensitivity(pooling_rows)
    forest_data = meta_analysis.forest(pooling_rows)
    multiverse = meta_multiverse.multiverse(pooling_rows)
    summary = meta_summary.build_summary(selected, codebook or None)

    extraction_agreement = (
        meta_agreement.reliability(
            *meta_agreement.extraction_case_maps(extractions, codebook),
            reference="extraction",
        )
        if codebook
        else {"overall": {"ac1": None}, "fields": []}
    )
    screening_fields = meta_agreement._criterion_fields(criteria)
    screening_agreement = meta_agreement.reliability(
        screening_fields,
        meta_agreement.screening_case_maps(screenings, criteria),
        reference="screening",
    )

    label = scheme_row.label if scheme_row is not None and scheme_row.label else scheme_name or "meta-analysis"
    title = title or f"Methods and Results — {label}"

    methods: list[dict[str, Any]] = [
        {
            "heading": "Search strategy",
            "paragraphs": [
                f"{prisma['identification']['total']:,} records were identified and "
                "screened against the eligibility criteria below. No constraints beyond "
                "those criteria were applied."
            ],
        },
        {
            "heading": "Eligibility criteria",
            "paragraphs": _risk_paragraphs(criteria),
        },
        {
            "heading": "Selection process",
            "paragraphs": [
                f"{prisma['screening']['screened']:,} records were screened on title/abstract "
                f"({prisma['screening']['excluded']:,} excluded); "
                f"{prisma['fulltext']['assessed']:,} reports were assessed for eligibility, "
                f"of which {prisma['fulltext']['excluded']:,} were excluded. "
                f"{prisma['inclusion']['studies']:,} studies "
                f"({prisma['inclusion']['reports']:,} extractions) were included in the synthesis."
            ],
        },
        {
            "heading": "Data extraction and effect-size computation",
            "paragraphs": [
                "Each eligible study was coded against the scheme's study and metric fields. "
                "Reported statistics were converted to a common standardised effect size "
                "(Hedges' g / Fisher z / log odds ratio as appropriate) with the variance "
                "implied by the test statistic and the group sizes; the sign was oriented by "
                "the outcome's polarity, and the primary contrast was flagged with the "
                "eligible-primary role."
            ],
        },
        {
            "heading": "Statistical analysis",
            "paragraphs": [
                "Random-effects models were fitted with the DerSimonian-Laird estimator. "
                "Heterogeneity was quantified with Cochran's Q, I² and a two-level "
                "(effects nested in studies) variance decomposition; small-study effects "
                "were assessed with Egger's regression test."
            ],
        },
        {
            "heading": "Inter-rater reliability",
            "paragraphs": [
                "Reliability of the deterministic labels was quantified with Gwet's AC1 "
                "(nominal) and AC2 (linear weights for ordered labels), which accommodate "
                "coders who do not all rate the same items."
            ],
        },
    ]

    pool_table = {
        "title": "Pooled effect estimate",
        "columns": ["Model", "k", "Studies", "Estimate", "95% CI", "τ²", "I² (%)", "p"],
        "rows": [
            {
                "Model": "DerSimonian-Laird random effects",
                "k": pooled["k"],
                "Studies": pooled["n_studies"],
                "Estimate": _fmt(pooled["estimate"]),
                "95% CI": _ci(pooled["ci_low"], pooled["ci_high"]),
                "τ²": _fmt(pooled["tau2"], 3),
                "I² (%)": _fmt(pooled["i2"], 1),
                "p": _fmt_p(pooled["p"]),
            }
        ],
    }
    variance_table = {
        "title": "Variance decomposition (two-level model)",
        "columns": ["Level", "Component", "Variance", "Share of variance (%)"],
        "rows": [
            {
                "Level": "Level 1",
                "Component": "Sampling variance",
                "Variance": _fmt(two_level["vbar"], 4),
                "Share of variance (%)": _fmt(two_level["i2_sampling"], 1),
            },
            {
                "Level": "Level 2",
                "Component": "τ² (between effects within studies)",
                "Variance": _fmt(two_level["tau2_within"], 4),
                "Share of variance (%)": _fmt(two_level["i2_within_alloc"], 1),
            },
            {
                "Level": "Level 3",
                "Component": "σ² (between studies)",
                "Variance": _fmt(two_level["tau2_between"], 4),
                "Share of variance (%)": _fmt(two_level["i2_between_alloc"], 1),
            },
        ],
    }
    synthesis_paragraphs = [
        f"The pooled random-effects estimate was {_fmt(pooled['estimate'])} "
        f"(95% CI {_ci(pooled['ci_low'], pooled['ci_high'])}; k = {pooled['k']}, "
        f"{pooled['n_studies']} studies)."
    ]
    if consensus is not None and (
        consensus.get("n_dropped_conflicts") or consensus.get("n_dropped_metrics")
    ):
        synthesis_paragraphs.append(
            f"Effect rows combine every coder's extraction: "
            f"{consensus.get('n_consensus_units', 0)} consensus unit(s), "
            f"{consensus.get('n_master_resolved', 0)} field(s) settled by adjudication, "
            f"{consensus.get('n_dropped_conflicts', 0)} unresolved conflicting field(s) "
            f"excluded and {consensus.get('n_dropped_metrics', 0)} contrast(s) dropped "
            f"for lack of a derivable effect."
        )
    if pooled["k"] > 1:
        synthesis_paragraphs.append(
            f"Heterogeneity was Q({pooled['q_df']}) = {_fmt(pooled['q'])}, "
            f"p {_fmt_p(pooled['q_p'])}, I² = {_fmt(pooled['i2'], 1)}%, "
            f"τ² = {_fmt(pooled['tau2'], 3)}."
        )

    results: list[dict[str, Any]] = [
        {
            "heading": "Study selection",
            "paragraphs": [
                f"{prisma['identification']['total']:,} records were identified; "
                f"{prisma['screening']['screened']:,} were screened and "
                f"{prisma['screening']['excluded']:,} excluded on title/abstract. "
                f"{prisma['fulltext']['assessed']:,} reports were assessed in full text and "
                f"{prisma['fulltext']['excluded']:,} excluded, leaving "
                f"{prisma['inclusion']['studies']:,} included studies."
            ],
            "tables": [
                {
                    "title": "PRISMA 2020 selection counts",
                    "columns": ["Stage", "n"],
                    "rows": [
                        {"Stage": "Records identified", "n": prisma["identification"]["total"]},
                        {"Stage": "Records screened", "n": prisma["screening"]["screened"]},
                        {"Stage": "Records excluded (title/abstract)", "n": prisma["screening"]["excluded"]},
                        {"Stage": "Reports assessed for eligibility", "n": prisma["fulltext"]["assessed"]},
                        {"Stage": "Reports excluded", "n": prisma["fulltext"]["excluded"]},
                        {"Stage": "Studies included", "n": prisma["inclusion"]["studies"]},
                    ],
                }
            ],
        },
        {
            "heading": "Study characteristics",
            "paragraphs": [
                f"The synthesis comprised {summary['n_extractions']:,} extractions, "
                f"{summary['n_records']:,} experiment records and {summary['n_studies']:,} studies."
            ],
            "tables": _summary_tables(summary),
        },
        {
            "heading": "Synthesis of effects",
            "paragraphs": synthesis_paragraphs,
            "tables": [pool_table, variance_table],
        },
        _bias_section(bias),
        _bayes_section(bayes),
        {
            "heading": "Inter-rater reliability",
            "paragraphs": _reliability_paragraph(screening_agreement, extraction_agreement),
            "tables": _reliability_tables(screening_agreement, extraction_agreement),
        },
    ]

    return {
        "title": title,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scheme": scheme_name,
        "pooled": pooled,
        "consensus": consensus,
        "two_level": two_level,
        "egger": egger,
        "forest": forest_data,
        "publication_bias": bias,
        "bayes": bayes,
        "multiverse": multiverse,
        "methods": methods,
        "results": results,
    }


def _summary_tables(summary: dict[str, Any]) -> list[dict[str, Any]]:
    tables = []
    for field in summary.get("fields", [])[:8]:
        levels = field.get("levels") or []
        if not levels:
            continue
        tables.append(
            {
                "title": f"{field.get('label') or field['name']}",
                "columns": [field.get("label") or field["name"], "n", "Studies"],
                "rows": [
                    {
                        field.get("label") or field["name"]: level["value"],
                        "n": level["n"],
                        "Studies": level["n_studies"],
                    }
                    for level in levels
                ],
            }
        )
    return tables


def _reliability_paragraph(screening: dict[str, Any], extraction: dict[str, Any]) -> list[str]:
    parts = []
    for label, data in (("screening", screening), ("extraction", extraction)):
        overall = data.get("overall") or {}
        if overall.get("ac1") is None:
            parts.append(f"No {label} reliability could be computed (fewer than two coders).")
        else:
            parts.append(
                f"Across {overall['n_fields']} {label} labels "
                f"({overall['n_items_total']:,} overlapping item cells), the item-weighted "
                f"mean Gwet's AC1 was {_fmt(overall['ac1'], 3)}."
            )
    return parts


def _reliability_tables(screening: dict[str, Any], extraction: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for field in screening.get("fields", []):
        if field.get("ac1") is None:
            continue
        rows.append(
            {
                "Window": "Screening",
                "Field": field["label"],
                "AC1": _fmt(field["ac1"], 3),
                "Items": field["n_multi"],
            }
        )
    for field in extraction.get("fields", []):
        if field.get("ac1") is None:
            continue
        rows.append(
            {
                "Window": "Extraction",
                "Field": field["label"],
                "AC1": _fmt(field["ac1"], 3),
                "Items": field["n_multi"],
            }
        )
    if not rows:
        return []
    return [
        {
            "title": "Gwet's AC1 by deterministic label",
            "columns": ["Window", "Field", "AC1", "Items"],
            "rows": rows[:20],
        }
    ]


# ── bias / Bayesian sections ─────────────────────────────────────────────

def _bias_section(bias: dict[str, Any]) -> dict[str, Any]:
    """Publication-bias results section (Egger, PET-PEESE, trim-and-fill, p-curve)."""
    egger = bias.get("egger") or {}
    pet_peese = bias.get("pet_peese") or {}
    pet = pet_peese.get("pet") or {}
    peese = pet_peese.get("peese") or {}
    trim = bias.get("trim_and_fill") or {}
    curve = bias.get("p_curve") or {}
    preferred = pet_peese.get("recommended") or "-"
    chosen = peese if preferred == "PEESE" else pet
    chosen_est = chosen.get("intercept")
    chosen_se = chosen.get("se")
    if chosen_est is not None and chosen_se is not None:
        preferred_ci = _ci(chosen_est - 1.96 * chosen_se, chosen_est + 1.96 * chosen_se)
    else:
        preferred_ci = "-"
    preferred_est = chosen_est
    paragraphs = [
        f"Egger's regression intercept was {_fmt(egger.get('intercept'))} "
        f"(t = {_fmt(egger.get('t'))}, p {_fmt_p(egger.get('p'))}). "
        f"PET gave {_fmt(pet.get('intercept'))} (p {_fmt_p(pet.get('p'))}) and PEESE "
        f"{_fmt(peese.get('intercept'))} (p {_fmt_p(peese.get('p'))}); the preferred "
        f"estimator was {preferred} = {_fmt(preferred_est)} (95% CI {preferred_ci}).",
        f"Trim-and-fill imputed {trim.get('k0')} studies on the {trim.get('side') or '-'} "
        f"side, adjusting the pooled estimate from {_fmt(trim.get('estimate_raw'))} "
        f"to {_fmt(trim.get('estimate'))} (95% CI "
        f"{_ci(trim.get('ci_low'), trim.get('ci_high'))}).",
        f"The p-curve test considered {curve.get('n_significant')} significant effects "
        f"({curve.get('n_p_lt_025')} below .025); p = {_fmt_p(curve.get('p_half'))}. "
        f"{curve.get('note') or ''}".strip(),
    ]
    tables = [
        {
            "title": "Egger's regression test",
            "columns": ["k", "Intercept", "SE", "t", "p", "Slope", "Slope p"],
            "rows": [
                {
                    "k": egger.get("k"),
                    "Intercept": _fmt(egger.get("intercept")),
                    "SE": _fmt(egger.get("se")),
                    "t": _fmt(egger.get("t")),
                    "p": _fmt_p(egger.get("p")),
                    "Slope": _fmt(egger.get("slope")),
                    "Slope p": _fmt_p(egger.get("slope_p")),
                }
            ],
        },
        {
            "title": "PET-PEESE",
            "columns": ["Estimator", "Intercept", "SE", "t", "p"],
            "rows": [
                {
                    "Estimator": "PET (on SE)",
                    "Intercept": _fmt(pet.get("intercept")),
                    "SE": _fmt(pet.get("se")),
                    "t": _fmt(pet.get("t")),
                    "p": _fmt_p(pet.get("p")),
                },
                {
                    "Estimator": "PEESE (on variance)",
                    "Intercept": _fmt(peese.get("intercept")),
                    "SE": _fmt(peese.get("se")),
                    "t": _fmt(peese.get("t")),
                    "p": _fmt_p(peese.get("p")),
                },
            ],
        },
        {
            "title": "Trim-and-fill (Duval-Tweedie L0)",
            "columns": ["k", "Imputed (k0)", "Side", "Adjusted", "95% CI", "Observed"],
            "rows": [
                {
                    "k": trim.get("k"),
                    "Imputed (k0)": trim.get("k0"),
                    "Side": trim.get("side"),
                    "Adjusted": _fmt(trim.get("estimate")),
                    "95% CI": _ci(trim.get("ci_low"), trim.get("ci_high")),
                    "Observed": _fmt(trim.get("estimate_raw")),
                }
            ],
        },
        {
            "title": "p-curve right-skew test",
            "columns": ["n significant", "n < .025", "p (binomial)", "Evidential"],
            "rows": [
                {
                    "n significant": curve.get("n_significant"),
                    "n < .025": curve.get("n_p_lt_025"),
                    "p (binomial)": _fmt_p(curve.get("p_half")),
                    "Evidential": (
                        "yes" if curve.get("evidential") else ("no" if curve.get("evidential") is False else "-")
                    ),
                }
            ],
        },
    ]
    return {"heading": "Publication bias", "paragraphs": paragraphs, "tables": tables}


def _bayes_section(bayes: dict[str, Any]) -> dict[str, Any]:
    """Bayesian random-effects results section (posterior, tau, Bayes factors)."""
    mu = bayes.get("mu") or {}
    tau = bayes.get("tau") or {}
    paragraphs = [
        f"The Bayesian random-effects posterior mean was {_fmt(mu.get('mean'))} "
        f"(95% CrI {_ci(mu.get('ci_low'), mu.get('ci_high'))}); "
        f"P(μ > 0) = {_fmt(mu.get('p_gt0'), 3)} and the two-sided posterior tail "
        f"was {_fmt(mu.get('p_two_sided'), 3)}. The Savage-Dickey BF₁₀ for μ = 0 "
        f"was {_fmt(bayes.get('bf10'), 3)}.",
        f"The posterior between-study SD was τ = {_fmt(tau.get('mean'))} "
        f"(95% CrI {_ci(tau.get('ci_low'), tau.get('ci_high'))}); "
        f"BF₀₁ for τ = 0 was {_fmt(bayes.get('bf01_tau0'), 3)}.",
    ]
    tables = [
        {
            "title": "Bayesian random-effects model",
            "columns": ["Parameter", "Mean", "95% CrI", "P(> 0)"],
            "rows": [
                {
                    "Parameter": "μ (pooled effect)",
                    "Mean": _fmt(mu.get("mean")),
                    "95% CrI": _ci(mu.get("ci_low"), mu.get("ci_high")),
                    "P(> 0)": _fmt(mu.get("p_gt0"), 3),
                },
                {
                    "Parameter": "τ (between-study SD)",
                    "Mean": _fmt(tau.get("mean")),
                    "95% CrI": _ci(tau.get("ci_low"), tau.get("ci_high")),
                    "P(> 0)": "-",
                },
            ],
        },
        {
            "title": "Prior sensitivity",
            "columns": ["μ prior SD", "τ prior", "τ scale", "Posterior mean", "95% CrI", "BF₁₀"],
            "rows": [
                {
                    "μ prior SD": row.get("mu_sd"),
                    "τ prior": row.get("tau_prior"),
                    "τ scale": row.get("tau_scale"),
                    "Posterior mean": _fmt(row.get("mean")),
                    "95% CrI": _ci(row.get("ci_low"), row.get("ci_high")),
                    "BF₁₀": _fmt(row.get("bf10"), 3),
                }
                for row in (bayes.get("sensitivity") or [])
            ],
        },
    ]
    return {"heading": "Bayesian synthesis", "paragraphs": paragraphs, "tables": tables}


def _multiverse_section(multiverse: dict[str, Any]) -> dict[str, Any]:
    """Multiverse specification-curve summary (count, median, range, % positive)."""
    summary = multiverse.get("summary") or {}
    paragraphs = [
        f"The multiverse enumerated {summary.get('n_specs', 0)} specifications across "
        f"the primary/effect-set, estimator, outcome-domain and outlier choices; "
        f"{summary.get('n_ok', 0)} produced a pooled estimate. The median estimate was "
        f"{_fmt(summary.get('median'))} (range {_fmt(summary.get('min'))} to "
        f"{_fmt(summary.get('max'))}); {_fmt(summary.get('pct_positive'), 1)}% of "
        f"specifications were above zero and the 2.5th-97.5th percentile interval was "
        f"{_ci(summary.get('ci_low'), summary.get('ci_high'))}."
    ]
    return {
        "heading": "Multiverse / specification curve",
        "paragraphs": paragraphs,
        "tables": [
            {
                "title": "Specification-curve summary",
                "columns": ["Specifications", "With estimate", "Median", "Min", "Max", "% positive"],
                "rows": [
                    {
                        "Specifications": summary.get("n_specs"),
                        "With estimate": summary.get("n_ok"),
                        "Median": _fmt(summary.get("median")),
                        "Min": _fmt(summary.get("min")),
                        "Max": _fmt(summary.get("max")),
                        "% positive": _fmt(summary.get("pct_positive"), 1),
                    }
                ],
            }
        ],
    }


def _context_extra_sections(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Sections for top-level ``publication_bias`` / ``bayes`` context keys.

    Only emitted when the context carries the data and the section is not already
    present in ``results`` (so ``build_report`` output is never duplicated).
    """
    headings = {section.get("heading") for section in ctx.get("results", [])}
    extras: list[dict[str, Any]] = []
    if ctx.get("publication_bias") and "Publication bias" not in headings:
        extras.append(_bias_section(ctx["publication_bias"]))
    if ctx.get("bayes") and "Bayesian synthesis" not in headings:
        extras.append(_bayes_section(ctx["bayes"]))
    if (
        ctx.get("multiverse")
        and "Multiverse / specification curve" not in headings
        and (ctx["multiverse"].get("summary") or {}).get("n_specs")
    ):
        extras.append(_multiverse_section(ctx["multiverse"]))
    return extras


# ── rendering ────────────────────────────────────────────────────────────

def render_markdown(ctx: dict[str, Any]) -> str:
    lines = [
        f"# {ctx.get('title', 'Methods and Results')}",
        "",
        f"*Generated {ctx.get('generated', '')}.*",
        "",
        "# Method",
    ]
    for section in ctx.get("methods", []):
        lines.append(f"## {section['heading']}")
        lines.extend(section.get("paragraphs", []))
        lines.append("")
    lines.append("# Results")
    sections = [*ctx.get("results", []), *_context_extra_sections(ctx)]
    for section in sections:
        lines.append(f"## {section['heading']}")
        lines.extend(section.get("paragraphs", []))
        for table in section.get("tables", []):
            columns = [str(c) for c in table["columns"]]
            lines.append(f"**{table['title']}**")
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join("---" for _ in columns) + " |")
            lines.extend(
                "| "
                + " | ".join(
                    "" if row.get(column) is None else str(row.get(column))
                    for column in columns
                )
                + " |"
                for row in table["rows"]
            )
            lines.append("")
    return "\n".join(lines)


def render_docx_bytes(ctx: dict[str, Any]) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)

    title = doc.add_paragraph()
    run = title.add_run(ctx.get("title", "Methods and Results"))
    run.bold = True
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def heading(level: int, text: str) -> None:
        paragraph = doc.add_paragraph()
        run = paragraph.add_run(text)
        run.bold = True
        if level >= 2:
            run.italic = True

    def table_block(table: dict[str, Any]) -> None:
        doc.add_paragraph(table["title"]).runs[0].italic = True
        columns = [str(c) for c in table["columns"]]
        docx_table = doc.add_table(rows=1, cols=len(columns))
        for index, column in enumerate(columns):
            cell = docx_table.rows[0].cells[index]
            cell.text = column
            for paragraph_run in cell.paragraphs[0].runs:
                paragraph_run.bold = True
        for row in table["rows"]:
            cells = docx_table.add_row().cells
            for index, column in enumerate(columns):
                value = row.get(column)
                cells[index].text = "" if value is None else str(value)
        for row in docx_table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(10)

    heading(1, "Method")
    for section in ctx.get("methods", []):
        heading(2, section["heading"])
        for paragraph in section.get("paragraphs", []):
            doc.add_paragraph(paragraph)
    heading(1, "Results")
    for section in [*ctx.get("results", []), *_context_extra_sections(ctx)]:
        heading(2, section["heading"])
        for paragraph in section.get("paragraphs", []):
            doc.add_paragraph(paragraph)
        for table in section.get("tables", []):
            table_block(table)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# ── PowerPoint ───────────────────────────────────────────────────────────

def render_pptx_bytes(ctx: dict[str, Any]) -> bytes:
    """Assemble a slide deck: title, pooled/heterogeneity, forest table and the
    optional publication-bias / Bayesian slides."""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    def add_title_slide() -> None:
        slide = prs.slides.add_slide(blank)
        frame = slide.shapes.add_textbox(
            Inches(0.6), Inches(2.0), Inches(8.8), Inches(2.6)
        ).text_frame
        frame.word_wrap = True
        frame.text = ctx.get("title", "Methods and Results")
        frame.paragraphs[0].font.size = Pt(30)
        frame.paragraphs[0].font.bold = True
        sub = frame.add_paragraph()
        sub.text = f"Generated {ctx.get('generated', '')}"
        sub.font.size = Pt(14)
        if ctx.get("scheme"):
            line = frame.add_paragraph()
            line.text = f"Scheme: {ctx['scheme']}"
            line.font.size = Pt(14)

    def add_bullets(title: str, lines: list[str]) -> None:
        slide = prs.slides.add_slide(blank)
        frame = slide.shapes.add_textbox(
            Inches(0.5), Inches(0.3), Inches(9.0), Inches(6.9)
        ).text_frame
        frame.word_wrap = True
        frame.text = title
        frame.paragraphs[0].font.size = Pt(24)
        frame.paragraphs[0].font.bold = True
        for line in lines:
            paragraph = frame.add_paragraph()
            paragraph.text = str(line)
            paragraph.font.size = Pt(15)

    def add_table(title: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
        slide = prs.slides.add_slide(blank)
        slide.shapes.add_textbox(
            Inches(0.4), Inches(0.2), Inches(9.2), Inches(0.5)
        ).text_frame.text = title
        body = rows[:16]
        table = slide.shapes.add_table(
            len(body) + 1, len(columns), Inches(0.4), Inches(0.85), Inches(9.2),
            Inches(0.3) * (len(body) + 1),
        ).table
        for index, column in enumerate(columns):
            cell = table.cell(0, index)
            cell.text = str(column)
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.bold = True
                    run.font.size = Pt(11)
        for row_index, row in enumerate(body, start=1):
            for col_index, column in enumerate(columns):
                cell = table.cell(row_index, col_index)
                value = row.get(column)
                cell.text = "" if value is None else str(value)
                for paragraph in cell.text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(10)

    add_title_slide()

    pooled = ctx.get("pooled") or {}
    if pooled:
        add_bullets(
            "Pooled effect and heterogeneity",
            [
                f"Estimated effect: {_fmt(pooled.get('estimate'))} "
                f"(95% CI {_ci(pooled.get('ci_low'), pooled.get('ci_high'))})",
                f"k = {pooled.get('k')} effects across {pooled.get('n_studies')} studies",
                f"τ² = {_fmt(pooled.get('tau2'), 3)}; I² = {_fmt(pooled.get('i2'), 1)}%",
                f"Q({pooled.get('q_df')}) = {_fmt(pooled.get('q'))}, "
                f"p {_fmt_p(pooled.get('q_p'))}",
                f"Pooled effect p {_fmt_p(pooled.get('p'))}",
            ],
        )

    forest = ctx.get("forest") or {}
    if forest.get("rows"):
        rows = [
            {
                "Study": row.get("study_id"),
                "Outcome": row.get("dv_name") or "-",
                "Effect": _fmt(row.get("effect")),
                "95% CI": _ci(row.get("ci_low"), row.get("ci_high")),
                "Weight %": _fmt(row.get("weight"), 1),
            }
            for row in forest["rows"]
        ]
        add_table("Effects (forest table)", ["Study", "Outcome", "Effect", "95% CI", "Weight %"], rows)

    # NOTE: a moderator slide used to live here, reading ``ctx["moderator"]``
    # which ``build_report`` never sets — a dead code path. The report's
    # moderator model is already rendered in the Markdown/DOCX tables, so the
    # empty slide was removed rather than reading a permanently-absent key.

    bias = ctx.get("publication_bias")
    if bias:
        pet_peese = bias.get("pet_peese") or {}
        pet = pet_peese.get("pet") or {}
        peese = pet_peese.get("peese") or {}
        trim = bias.get("trim_and_fill") or {}
        curve = bias.get("p_curve") or {}
        add_table(
            "Publication bias",
            ["Test", "Estimate", "Statistic", "p"],
            [
                {
                    "Test": "Egger intercept",
                    "Estimate": _fmt((bias.get("egger") or {}).get("intercept")),
                    "Statistic": f"t = {_fmt((bias.get('egger') or {}).get('t'))}",
                    "p": _fmt_p((bias.get("egger") or {}).get("p")),
                },
                {"Test": "PET", "Estimate": _fmt(pet.get("intercept")),
                 "Statistic": "", "p": _fmt_p(pet.get("p"))},
                {"Test": "PEESE", "Estimate": _fmt(peese.get("intercept")),
                 "Statistic": "", "p": _fmt_p(peese.get("p"))},
                {"Test": "Trim-and-fill", "Estimate": _fmt(trim.get("estimate")),
                 "Statistic": f"k0 = {trim.get('k0')} ({trim.get('side')})",
                 "p": ""},
                {"Test": "p-curve", "Estimate": "",
                 "Statistic": f"n_sig = {curve.get('n_significant')}",
                 "p": _fmt_p(curve.get("p_half"))},
            ],
        )

    bayes = ctx.get("bayes")
    if bayes:
        mu = bayes.get("mu") or {}
        tau = bayes.get("tau") or {}
        add_bullets(
            "Bayesian random-effects model",
            [
                f"Posterior μ = {_fmt(mu.get('mean'))} "
                f"(95% CrI {_ci(mu.get('ci_low'), mu.get('ci_high'))})",
                f"P(μ > 0) = {_fmt(mu.get('p_gt0'), 3)}",
                f"BF₁₀ (μ = 0) = {_fmt(bayes.get('bf10'), 3)}; "
                f"BF₀₁ (τ = 0) = {_fmt(bayes.get('bf01_tau0'), 3)}",
                f"Posterior τ = {_fmt(tau.get('mean'))} "
                f"(95% CrI {_ci(tau.get('ci_low'), tau.get('ci_high'))})",
            ],
        )

    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()
