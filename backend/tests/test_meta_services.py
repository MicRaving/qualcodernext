"""Unit tests for the meta services (parsers, prompts, normalization)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from sqlalchemy import text

from qualcoder_api.core.models import MetaCriterion
from qualcoder_api.persistence.database import (
    create_all_tables,
    create_project_engine,
    create_session_factory,
    dispose_engine,
)
from qualcoder_api.persistence.repo.meta_repo import MetaRepository
from qualcoder_api.services import (
    meta_agreement,
    meta_analysis,
    meta_audit,
    meta_bayes,
    meta_consensus,
    meta_figures,
    meta_multiverse,
    meta_prisma,
    meta_report,
    meta_summary,
)
from qualcoder_api.services.meta_codingstudio import (
    DEFAULT_INTERVENTION_TYPES,
    MAX_ERRORS,
    import_codingstudio,
    preview_codingstudio,
    schema_codebook,
)
from qualcoder_api.services.meta_effects import (
    ALL_FAMILIES,
    derive_effect,
    metric_status,
)
from qualcoder_api.services.meta_eligibility import evaluate_criteria
from qualcoder_api.services.meta_extract import (
    derive_dv_metrics,
    metric_has_full_descriptives,
    metric_has_metafor_fallback,
    normalize_and_validate,
    normalize_metric,
    records_from_response,
)
from qualcoder_api.services.meta_import import parse_ebsco_xml, parse_hits_xlsx
from qualcoder_api.services.meta_prompt import (
    build_cluster_messages,
    build_extraction_messages,
    build_prescreen_messages,
    criteria_prompt_hash,
    extract_json,
)
from qualcoder_api.services.meta_roles import (
    metric_by_role,
    role_map,
    value_by_role,
)
from qualcoder_api.services.meta_scheme import (
    EFFECT_FAMILIES,
    enabled_families,
    field_by_role,
    metrics_group,
    normalise_codebook,
    study_fields,
)
from qualcoder_api.services.meta_screen import assign_entries, parse_verdicts


def _criterion(i: int) -> MetaCriterion:
    return MetaCriterion(
        position=i,
        key=f"criterion{i}",
        label=f"Criterion {i}",
        prompt_text=f"Criterion {i} description.",
    )


def test_extract_json_tolerates_prose_and_fences():
    assert extract_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert extract_json('prefix {"a": 1} suffix') == {"a": 1}
    assert extract_json("no json here") is None


def test_criteria_prompt_hash_is_deterministic():
    criteria = [_criterion(1), _criterion(2)]
    assert criteria_prompt_hash(criteria) == criteria_prompt_hash(criteria)
    assert criteria_prompt_hash(criteria) != criteria_prompt_hash(criteria[:1])


def test_cluster_messages_include_all_criteria():
    criteria = [_criterion(1), _criterion(2)]
    messages = build_cluster_messages(
        [(0, {"title": "T", "abstract": "A", "doi": "10.x/y"})], criteria
    )
    system = messages[0]["content"]
    assert "Criterion 1 description." in system
    assert "criterion1_applies" in system
    assert "criterion2_certainty" in system
    user = messages[1]["content"]
    assert "T" in user and "10.x/y" in user


def test_build_prescreen_messages_embeds_configured_prompt_and_paper():
    messages = build_prescreen_messages(
        "EXCLUDE if not a randomised trial.", "ABSTRACT BODY", title="My Paper"
    )
    assert len(messages) == 1
    content = messages[0]["content"]
    assert "EXCLUDE if not a randomised trial." in content
    assert "ABSTRACT BODY" in content
    assert "My Paper" in content
    # The configured prompt is no longer silently discarded.
    assert messages[0]["role"] == "user"


def test_build_extraction_messages_puts_coding_prompt_in_system():
    messages = build_extraction_messages(
        "CODE all DVs into the JSON schema.", "FULL TEXT BODY", title="My Paper"
    )
    assert messages[0]["role"] == "system"
    assert "CODE all DVs into the JSON schema." in messages[0]["content"]
    user = messages[1]["content"]
    assert "FULL TEXT BODY" in user and "My Paper" in user


def test_parse_ebsco_xml(tmp_path: Path):
    xml = """<?xml version="1.0"?><records>
    <record><title>One</title><abstract>abs</abstract>
    <contributors>Doe, J ; Roe, S</contributors><doi>10.1/a</doi>
    <publicationDate>2019-07-01</publicationDate><source>J</source></record>
    </records>"""
    path = tmp_path / "r.xml"
    path.write_text(xml, encoding="utf-8")
    hits = parse_ebsco_xml(str(path))
    assert len(hits) == 1
    hit = hits[0]
    assert hit["title"] == "One"
    assert hit["authors"] == "Doe, J, Roe, S"
    assert hit["year"] == "2019"
    assert hit["doi"] == "10.1/a"


def test_parse_hits_xlsx(tmp_path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["title", "abstract", "authors", "doi", "publication year"])
    ws.append(["Two", "abstract two", "A, B", "10.2/b", "2022"])
    ws.append(["No DOI", "x", "C", "", "2023"])
    path = tmp_path / "hits.xlsx"
    wb.save(path)
    hits = parse_hits_xlsx(str(path))
    assert len(hits) == 2
    assert hits[0]["doi"] == "10.2/b"
    assert hits[1]["doi"] is None


def test_parse_hits_xlsx_header_not_on_first_row(tmp_path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Search results export"])  # title line above the header
    ws.append([])
    ws.append(["Authors", "Title", "Year", "Abstract", "DOI"])
    ws.append(["Doe, J", "Study A", "2020", "abs a", "10.3/a"])
    ws.append(["Roe, S", "Study B", "2021", "abs b", "10.3/b"])
    path = tmp_path / "hits_offset.xlsx"
    wb.save(path)
    hits = parse_hits_xlsx(str(path))
    assert [h["title"] for h in hits] == ["Study A", "Study B"]
    assert hits[0]["authors"] == "Doe, J"
    assert hits[0]["year"] == "2020"


def test_parse_hits_xlsx_german_headers(tmp_path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Titel", "Zusammenfassung", "Autoren", "DOI", "Jahr"])
    ws.append(["Studie A", "Zusammenfassung A", "Doe, J", "10.4/a", "2020"])
    path = tmp_path / "hits_de.xlsx"
    wb.save(path)
    hits = parse_hits_xlsx(str(path))
    assert len(hits) == 1
    assert hits[0]["title"] == "Studie A"
    assert hits[0]["authors"] == "Doe, J"


def test_parse_hits_xlsx_publication_year_is_year_not_source(tmp_path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Title", "Authors", "DOI", "Publication Year", "Source"])
    ws.append(["T", "A", "10.5/a", "2019", "Journal X"])
    path = tmp_path / "hits_pub.xlsx"
    wb.save(path)
    hits = parse_hits_xlsx(str(path))
    assert hits[0]["year"] == "2019"
    assert hits[0]["source"] == "Journal X"


def test_normalize_metric_infers_vi_from_d():
    metric = normalize_metric({"d_val": 0.5, "n1i": 20, "n2i": 20})
    assert metric["yi"] == 0.5
    assert metric["vi"] is not None
    assert metric["sei"] is not None
    assert metric_has_metafor_fallback(metric)


def test_normalize_metric_splits_balanced_groups():
    metric = normalize_metric({"n_total": 40, "m1i": 5, "m2i": 6, "sd1i": 1, "sd2i": 1})
    assert metric["n1i"] == 20 and metric["n2i"] == 20
    assert metric_has_full_descriptives(metric)


def test_normalize_and_validate_reports_missing():
    records, missing = normalize_and_validate(
        [{"Study_ID": "X2020_Exp1", "DV_Metrics": [{"dv_name": "dv"}]}]
    )
    assert len(records) == 1
    assert len(missing) == 1
    assert missing[0]["dv_name"] == "dv"


def test_assign_entries_uses_array_order_when_lengths_match():
    parsed = [{"a": 1}, {"a": 2}, {"a": 3}]
    assigned = assign_entries(parsed, 3)
    assert assigned == {0: {"a": 1}, 1: {"a": 2}, 2: {"a": 3}}


def test_assign_entries_maps_one_based_index_when_lengths_differ():
    # Model dropped one study but numbered them 1..N: map by index, not order.
    parsed = [{"index": 1, "a": "first"}, {"index": 3, "a": "third"}]
    assigned = assign_entries(parsed, 3)
    assert assigned == {0: {"index": 1, "a": "first"}, 2: {"index": 3, "a": "third"}}


def test_assign_entries_handles_zero_index_and_out_of_range():
    # Lengths differ, so the index path runs. Index 0 is accepted (0-based) and
    # an out-of-range index falls back to the array position.
    parsed = [{"index": 0, "a": "first"}, {"index": 99, "a": "second"}]
    assigned = assign_entries(parsed, 3)
    assert assigned[0]["a"] == "first"
    assert assigned[1]["a"] == "second"


def test_assign_entries_single_object_cluster():
    assert assign_entries({"index": 1, "a": 1}, 1) == {0: {"index": 1, "a": 1}}


def test_parse_verdicts_normalizes_free_text():
    criteria = [_criterion(1), _criterion(2)]
    entry = {
        "criterion1_applies": "YES",
        "criterion1_certainty": "moderate",
        "criterion2_applies": "maybe",
        "criterion2_certainty": "LOW",
    }
    verdicts = parse_verdicts(entry, criteria)
    assert verdicts["criterion1"] == {"applies": "Yes", "certainty": "Medium"}
    assert verdicts["criterion2"] == {"applies": "Unsure", "certainty": "Low"}


def test_parse_verdicts_accepts_boolean_alt_key():
    criteria = [_criterion(1)]
    verdicts = parse_verdicts({criteria[0].key: True}, criteria)
    assert verdicts[criteria[0].key]["applies"] == "Yes"
    verdicts = parse_verdicts({criteria[0].key: {"applies": "No"}}, criteria)
    assert verdicts[criteria[0].key]["applies"] == "No"

def test_parse_hits_xlsx_skips_cover_sheet(tmp_path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    cover = wb.active
    cover.title = "Search"
    cover.append(["EBSCOhost search export"])
    cover.append(["Query", '"inoculation"'])
    results = wb.create_sheet("SearchResults")
    results.append(["Title", "Authors", "Abstract", "DOI"])
    results.append(["Study A", "Doe, J", "abs", "10.6/a"])
    path = tmp_path / "hits_sheets.xlsx"
    wb.save(path)
    hits = parse_hits_xlsx(str(path))
    assert [h["title"] for h in hits] == ["Study A"]


# ── roles (§2) ───────────────────────────────────────────────────────────


def test_role_map_and_value_by_role():
    fields = [
        {"name": "sid", "role": "study_id"},
        {"name": "outcome", "role": "dv_name"},
        {"name": "mystery", "role": "not_a_role"},
        {"name": "plain"},
    ]
    roles = role_map(fields)
    assert roles == {"sid": "study_id", "outcome": "dv_name"}
    assert value_by_role({"sid": "S1", "outcome": "x"}, roles, "study_id") == "S1"
    assert value_by_role({"sid": "S1"}, roles, "dv_name") is None


def test_metric_by_role_legacy_aliases():
    by = metric_by_role({"n1i": 20, "n_t": 30, "d_val": 0.5, "m1i": 4})
    assert by["n1"] == 20
    assert by["d"] == 0.5
    assert by["m1"] == 4


# ── codebook v1 → v2 (§3) ────────────────────────────────────────────────


def test_normalise_codebook_v1_to_v2():
    raw = {
        "category": "Meta",
        "groups": ["Study", "Sample"],
        "study_fields": [{"name": "Study_ID", "label": "Study id", "type": "string"}],
        "code_fields": ["Notes", "Rationale"],
    }
    book = normalise_codebook(raw)
    assert book["version"] == 2
    assert book["groups"] == [
        {"name": "Study", "label": "Study"},
        {"name": "Sample", "label": "Sample"},
    ]
    # ``study_fields`` survives as an alias of ``fields`` for the publish path.
    assert book["study_fields"] == book["fields"]
    assert book["fields"][0]["role"] is None
    assert book["metrics"]["enabled"] is False
    assert book["code_fields"][0] == {"name": "Notes", "label": "Notes", "instruction": ""}


def test_normalise_codebook_v2_roles_and_families():
    raw = {
        "version": 2,
        "groups": [{"name": "Study", "label": "Study"}],
        "fields": [{"name": "sid", "role": "study_id"}],
        "metrics": {
            "enabled": True,
            "group": "metrics",
            "fields": [{"name": "eff", "role": "yi"}, {"name": "var", "role": "vi"}],
        },
        "effect_families": ["yi", "bogus"],
    }
    book = normalise_codebook(raw)
    assert enabled_families(book) == ["yi"]
    assert metrics_group(book) == "metrics"
    assert field_by_role(book, "study_id")["name"] == "sid"
    assert [f["name"] for f in book["metrics"]["fields"]] == ["eff", "var"]


def test_normalise_codebook_moderator_flag_defaults_true_and_honours_false():
    raw = {
        "groups": ["Study"],
        # v1 shape: the upgrade must synthesise ``moderator`` for these.
        "study_fields": [
            {"name": "sid", "role": "study_id"},
            {"name": "hidden", "moderator": False},
        ],
        "metrics": {"fields": [{"name": "eff", "role": "yi"}]},
    }
    book = normalise_codebook(raw)
    by_name = {f["name"]: f for f in book["fields"]}
    assert by_name["sid"]["moderator"] is True
    assert by_name["hidden"]["moderator"] is False
    # Metric fields get the same default.
    assert book["metrics"]["fields"][0]["moderator"] is True


# ── evaluate_criteria (§2/§10) ───────────────────────────────────────────


def _verdict_criterion(key: str, **overrides) -> MetaCriterion:
    base = {"position": 0, "key": key, "label": key.upper(), "prompt_text": "p"}
    base.update(overrides)
    return MetaCriterion(**base)


def test_evaluate_criteria_respects_gating_and_classify():
    criteria = [
        _verdict_criterion("c1"),
        _verdict_criterion(
            "c2",
            kind="classify",
            options=["rct", "quasi"],
            pass_values=["rct", "quasi"],
            exclude_reason="Not controlled",
        ),
        _verdict_criterion("c3", gating=0),
    ]
    verdicts = {
        "c1": {"applies": "Yes"},
        "c2": {"applies": "RCT"},
        # Informational criterion fails: must not block inclusion.
        "c3": {"applies": "No"},
    }
    result = evaluate_criteria(criteria, verdicts)
    assert result["eligible"] is True
    assert result["failing"] == []

    verdicts["c2"] = {"applies": "observational"}
    result = evaluate_criteria(criteria, verdicts)
    assert result["eligible"] is False
    assert result["failing"] == ["c2"]
    assert result["reasons"] == ["Not controlled"]


def test_evaluate_criteria_legacy_no_criteria():
    assert evaluate_criteria([], {"c1": {"applies": "Yes"}})["eligible"] is True
    assert evaluate_criteria([], {"c1": {"applies": "No"}})["eligible"] is False
    assert evaluate_criteria([], {})["eligible"] is False


# ── effect derivation / completeness (§5) ────────────────────────────────


def test_derive_effect_reported_yi_and_polarity():
    effect = derive_effect({"yi": 0.5, "vi": 0.04})
    assert effect is not None
    assert effect["method"] == "reported_yi"
    assert effect["yi"] == 0.5
    assert effect["sei"] == pytest.approx(0.2)
    flipped = derive_effect({"yi": 0.5, "vi": 0.04, "polarity": "higher_is_worse"})
    assert flipped is not None
    assert flipped["yi"] == -0.5
    assert flipped["sign_flipped"] is True


def test_derive_effect_priority_and_families():
    def _effect(**metric):
        effect = derive_effect(metric)
        assert effect is not None
        return effect

    assert _effect(d=0.5, n1=20, n2=20)["method"] == "cohens_d"
    assert _effect(g=0.5, n1=20, n2=20)["method"] == "hedges_g"
    assert _effect(m1=5, m2=4, sd1=1, sd2=1, n1=20, n2=20)["method"] == "descriptives"
    assert _effect(t=2.0, n1=20, n2=20)["method"] == "t"
    assert _effect(F=4.0, n1=20, n2=20)["method"] == "F"
    effect = _effect(**{"or": 1.5, "or_ci_low": 1.1, "or_ci_high": 2.0})
    assert effect["method"] == "odds_ratio"
    assert _effect(beta=0.3, beta_se=0.1)["method"] == "beta"
    assert derive_effect({}) is None
    assert derive_effect({"beta": 0.3}) is None


def test_metric_status_complete_fallback_incomplete():
    complete = {"n1": 20, "m1": 5, "sd1": 1, "n2": 20, "m2": 4, "sd2": 1}
    assert metric_status(complete)[0] == "complete"
    status, reason = metric_status({"t": 2.0, "n1": 20, "n2": 20})
    assert status == "fallback" and "t" in reason
    assert metric_status({"dv_name": "x"})[0] == "incomplete"
    # A family the scheme did not enable does not count as a fallback.
    assert metric_status({"t": 2.0, "n1": 20, "n2": 20}, ["descriptives"])[0] == "incomplete"


def test_metric_status_mirrors_derive_effect_preconditions():
    # d/g with a reported SE (no group sizes) is derivable and must be fallback.
    for metric in (
        {"d": 0.5, "d_se": 0.1},
        {"g": 0.5, "g_se": 0.1},
        {"F": 4.0, "n1": 20, "n2": 20},  # no df_num/df_den required
    ):
        assert derive_effect(metric) is not None
        status, _ = metric_status(metric)
        assert status == "fallback", metric
    # A metric neither function can derive stays incomplete.
    assert metric_status({"F": 4.0})[0] == "incomplete"
    assert derive_effect({"F": 4.0}) is None


def test_derive_effect_risk_ratio_uses_rr_ci_and_keeps_or():
    rr = derive_effect({"rr": 1.5, "rr_ci_low": 1.1, "rr_ci_high": 2.0})
    assert rr is not None
    assert rr["method"] == "risk_ratio"
    assert rr["yi"] == pytest.approx(math.log(1.5))
    # The OR CI roles must not stand in for the RR CI.
    assert derive_effect({"rr": 1.5, "or_ci_low": 1.1, "or_ci_high": 2.0}) is None
    assert "risk_ratio" in EFFECT_FAMILIES
    assert "risk_ratio" in ALL_FAMILIES
    # OR behaviour is unchanged.
    assert derive_effect({"or": 1.5, "or_ci_low": 1.1, "or_ci_high": 2.0})["method"] == "odds_ratio"


def test_apply_polarity_accepts_synonyms_and_case():
    flipping = ("higher_is_worse", "higher is worse", "WORSE", " negative ", "-1", "-")
    no_flip = ("higher_is_better", "higher is better", "better", "positive", "+", "1")
    for value in flipping:
        effect = derive_effect({"yi": 0.5, "vi": 0.04, "polarity": value})
        assert effect is not None and effect["sign_flipped"] is True, value
        assert effect["yi"] == pytest.approx(-0.5)
    for value in no_flip:
        effect = derive_effect({"yi": 0.5, "vi": 0.04, "polarity": value})
        assert effect is not None and effect["sign_flipped"] is False, value
        assert effect["yi"] == pytest.approx(0.5)


def test_derive_effect_smd_labelling_and_hedges_correction():
    cohen = derive_effect({"d": 0.5, "n1": 20, "n2": 20})
    assert cohen is not None and cohen["method"] == "cohens_d"
    assert cohen["yi"] == pytest.approx(0.5)

    j = 1.0 - 3.0 / (4 * (20 + 20) - 9)
    hedges = derive_effect({"g": 0.5, "n1": 20, "n2": 20})
    assert hedges is not None and hedges["method"] == "hedges_g"
    assert hedges["yi"] == pytest.approx(j * 0.5)
    raw_var = (20 + 20) / (20 * 20) + (0.5**2) / (2 * (20 + 20))
    assert hedges["vi"] == pytest.approx(j * j * raw_var)

    r_effect = derive_effect({"r": 0.4, "n_total": 50})
    assert r_effect is not None and r_effect["method"] == "r_to_d"
    assert r_effect["yi"] == pytest.approx(2 * 0.4 / math.sqrt(1 - 0.4**2))
    assert r_effect["vi"] == pytest.approx(4 * (1 - 0.4**2) / (50 - 1))


# ── extraction record model (§4) ─────────────────────────────────────────


def test_records_from_response_and_derive_dv_metrics():
    codebook = {
        "groups": [{"name": "Study", "label": "Study"}],
        "fields": [{"name": "sid", "role": "study_id"}],
        "metrics": {
            "enabled": True,
            "group": "metrics",
            "fields": [
                {"name": "dv", "role": "dv_name"},
                {"name": "eff", "role": "yi"},
                {"name": "var", "role": "vi"},
            ],
        },
        "effect_families": ["yi"],
    }
    response = [{"sid": "S1", "metrics": [{"dv": "x", "eff": 0.2, "var": 0.01}]}]
    records, missing = records_from_response(response, codebook)
    assert missing == []
    assert records[0]["study"]["sid"] == "S1"
    assert records[0]["metrics"][0]["eff"] == 0.2
    flat = derive_dv_metrics(records, role_map(study_fields(codebook)))
    assert flat[0]["sid"] == "S1"
    assert flat[0]["eff"] == 0.2
    assert flat[0]["_record"] == 0


def test_records_from_response_flags_incomplete():
    codebook = {"fields": [{"name": "sid", "role": "study_id"}]}
    response = [{"sid": "S1", "DV_Metrics": [{"dv_name": "y"}]}]
    records, missing = records_from_response(response, codebook)
    assert len(records[0]["metrics"]) == 1
    assert len(missing) == 1
    assert records[0]["metrics"][0]["missing_metrics_reason"]


# ── multi-owner extraction storage (v38) ─────────────────────────────────


@pytest.fixture
async def session(tmp_path):
    engine = create_project_engine(tmp_path / "meta_repo.qda")
    await create_all_tables(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        await s.execute(
            text(
                "INSERT INTO project (databaseversion, date, memo, about, bookmarkfile, "
                "bookmarkpos, codername, recently_used_codes) "
                "VALUES ('v38', '2026-01-01', '', 'QualCoder 4.0-test', 0, 0, 'default', '')"
            )
        )
        await s.commit()
        yield s
    await dispose_engine(engine)


async def test_upsert_extraction_per_owner(session):
    repo = MetaRepository(session)
    anna = await repo.upsert_extraction(
        hit_id=1, owner="anna", scheme="s", study_vars={"records": []}, status="extracted"
    )
    bob = await repo.upsert_extraction(hit_id=1, owner="bob", scheme="s", status="extracted")
    assert anna.id != bob.id

    rows = await repo.list_extractions(hit_id=1)
    assert {r.owner for r in rows} == {"anna", "bob"}
    only_anna = await repo.list_extractions(hit_id=1, owner="anna")
    assert [r.owner for r in only_anna] == ["anna"]

    # Same owner updates in place rather than overwriting another coder.
    again = await repo.upsert_extraction(hit_id=1, owner="anna", scheme="s", status="extracted")
    assert again.id == anna.id
    assert len(await repo.list_extractions(hit_id=1)) == 2


async def test_list_extractions_filters_status_and_defers_dv_metrics(session):
    repo = MetaRepository(session)
    records = [{"study": {"sid": "S1"}, "metrics": [{"eff": 0.3}]}]
    await repo.upsert_extraction(
        hit_id=1, owner="anna", scheme="s",
        study_vars={"records": records}, dv_metrics=[{"eff": 0.3}], status="extracted",
    )
    await repo.upsert_extraction(
        hit_id=1, owner="bob", scheme="s",
        study_vars={"records": []}, dv_metrics=[{"eff": 9.9}], status="excluded",
    )

    extracted = await repo.list_extractions(status="extracted")
    assert [e.owner for e in extracted] == ["anna"]
    assert extracted[0].dv_metrics == [{"eff": 0.3}]

    # Analysis re-derives from study_vars, so the cached column is skipped.
    slim = await repo.list_extractions(status="extracted", include_dv_metrics=False)
    assert len(slim) == 1
    assert slim[0].dv_metrics == []
    assert slim[0].study_vars["records"][0]["study"]["sid"] == "S1"


async def test_list_hits_by_ids_returns_only_requested(session):
    repo = MetaRepository(session)
    first = await repo.add_hit(title="A", doi="10.1/a")
    second = await repo.add_hit(title="B", doi="10.1/b")
    await repo.add_hit(title="C", doi="10.1/c")

    got = await repo.list_hits_by_ids([first.hit_id, second.hit_id, 99999])
    assert {h.hit_id for h in got} == {first.hit_id, second.hit_id}
    # Duplicate ids do not duplicate rows.
    assert len(await repo.list_hits_by_ids([first.hit_id, first.hit_id])) == 1
    assert await repo.list_hits_by_ids([]) == []


def test_refresh_dv_metrics_rederives_from_records():
    from qualcoder_api.services.meta_extract import refresh_dv_metrics

    extraction = {
        "study_vars": {"records": [{"study": {"sid": "S1"}, "metrics": [{"eff": 0.3}]}]},
        "dv_metrics": [{"stale": True}],
    }
    codebook = {"fields": [{"name": "sid", "role": "study_id"}]}
    refreshed = refresh_dv_metrics(extraction, codebook)
    assert refreshed["dv_metrics"] == [{"sid": "S1", "eff": 0.3, "_record": 0}]
    # A missing scheme leaves the cached column untouched.
    assert refresh_dv_metrics(extraction, None) is extraction


# ── analysis (§6) ────────────────────────────────────────────────────────


def _effect(study: str, effect: float, variance: float, **extra) -> dict:
    row = {
        "study_id": study,
        "effect": effect,
        "variance": variance,
        "dv_name": extra.pop("dv_name", f"dv-{study}"),
    }
    row.update(extra)
    return row


def test_pool_dl_known_dataset():
    rows = [
        _effect("A", 0.2, 0.04),
        _effect("B", 0.5, 0.05),
        _effect("C", 0.8, 0.09),
    ]
    result = meta_analysis.pool_dl(rows)
    assert result["k"] == 3
    assert result["q_df"] == 2
    assert result["estimate"] == pytest.approx(0.4472, rel=1e-3)
    assert result["se"] == pytest.approx(0.1650, rel=1e-3)
    assert result["ci_low"] == pytest.approx(0.1238, rel=2e-3)
    assert result["ci_high"] == pytest.approx(0.7705, rel=2e-3)
    assert result["tau2"] == pytest.approx(0.02639, rel=1e-2)
    assert result["q"] == pytest.approx(2.9406, rel=1e-3)
    assert result["i2"] == pytest.approx(31.99, rel=1e-2)
    assert result["p"] == pytest.approx(0.0067, abs=2e-3)
    assert result["n_studies"] == 3


def test_pool_dl_single_and_empty():
    empty = meta_analysis.pool_dl([])
    assert empty["k"] == 0 and empty["estimate"] is None
    single = meta_analysis.pool_dl([_effect("A", 0.4, 0.04)])
    assert single["k"] == 1
    assert single["estimate"] == pytest.approx(0.4)
    assert single["tau2"] == 0.0


def test_pool_dl_n_studies_counts_cleaned_rows_only():
    rows = [
        _effect("A", 0.2, 0.04),
        _effect("B", 0.5, 0.05),
        # Study C contributes no usable effect and must not be counted.
        _effect("C", 0.8, 0.0),
    ]
    result = meta_analysis.pool_dl(rows)
    assert result["k"] == 2
    assert result["n_studies"] == 2


def test_pool_fixed_inverse_variance():
    rows = [_effect("A", 0.2, 0.04), _effect("B", 0.5, 0.05)]
    result = meta_analysis.pool_fixed(rows)
    w = [1.0 / 0.04, 1.0 / 0.05]
    estimate = (w[0] * 0.2 + w[1] * 0.5) / sum(w)
    assert result["k"] == 2
    assert result["estimate"] == pytest.approx(estimate)
    assert result["se"] == pytest.approx(math.sqrt(1.0 / sum(w)))
    assert result["tau2"] == 0.0
    assert result["ci_low"] < estimate < result["ci_high"]


def test_primary_effects_prefers_eligible_primary():
    rows = [
        _effect("A", 0.2, 0.04, eligible_primary=True),
        _effect("B", 0.9, 0.04, eligible_primary=False),
    ]
    assert [r["study_id"] for r in meta_analysis.primary_effects(rows)] == ["A"]
    assert len(meta_analysis.primary_effects([_effect("C", 0.1, 0.1)])) == 1


def test_filter_effects_by_domain_and_family():
    rows = [
        _effect("A", 0.2, 0.04, domain="cred", method="cohens_d"),
        _effect("B", 0.4, 0.05, domain="sharing", method="odds_ratio"),
        _effect("C", 0.6, 0.05, domain="cred", method="odds_ratio"),
    ]
    assert [r["study_id"] for r in meta_analysis.filter_effects(rows, domain="cred")] == [
        "A",
        "C",
    ]
    assert [
        r["study_id"]
        for r in meta_analysis.filter_effects(rows, families=["odds_ratio"])
    ] == ["B", "C"]
    assert [
        r["study_id"]
        for r in meta_analysis.filter_effects(
            rows, domain="cred", families=["odds_ratio"]
        )
    ] == ["C"]
    assert len(meta_analysis.filter_effects(rows)) == 3


def test_pool_two_level_decomposition():
    rows = [
        _effect("A", 0.2, 0.04),
        _effect("A", 0.4, 0.05),
        _effect("B", 0.7, 0.06),
        _effect("C", 0.1, 0.09),
    ]
    result = meta_analysis.pool_two_level(rows)
    assert result["k"] == 4
    assert result["n_studies"] == 3
    assert result["tau2_within"] >= 0
    assert result["tau2_between"] >= 0
    total = sum(result["shares"].values())
    assert total == pytest.approx(1.0, abs=1e-9)
    assert result["i2_sampling"] == pytest.approx(result["shares"]["sampling"] * 100)
    # Reference two-stage estimate is now part of the result.
    assert result["estimate"] is not None
    assert result["se"] is not None
    assert result["ci_low"] < result["estimate"] < result["ci_high"]
    assert meta_analysis.pool_two_level([])["estimate"] is None


def test_subgroup_pools_each_level():
    rows = [
        _effect("A", 0.2, 0.04, domain="x"),
        _effect("B", 0.4, 0.05, domain="x"),
        _effect("C", 0.9, 0.04, domain="y"),
    ]
    result = meta_analysis.subgroup(rows, "domain")
    assert result["k_groups"] == 2
    by_value = {g["value"]: g for g in result["groups"]}
    assert by_value["x"]["k"] == 2
    assert by_value["x"]["estimate"] == pytest.approx(
        meta_analysis.pool_dl([r for r in rows if r["domain"] == "x"])["estimate"]
    )
    assert by_value["y"]["k"] == 1
    assert result["qm"] is not None and result["qm_p"] is not None
    # The UI-facing q_between aliases mirror the qm fields.
    assert result["q_between"] == result["qm"]
    assert result["q_between_df"] == result["qm_df"]
    assert result["q_between_p"] == result["qm_p"]


def test_moderator_wald_and_r2():
    rows = [
        _effect("A", 0.1, 0.04, dv_name="x", domain="a"),
        _effect("B", 0.2, 0.05, dv_name="x", domain="a"),
        _effect("C", 0.9, 0.04, dv_name="y", domain="b"),
        _effect("D", 1.0, 0.05, dv_name="y", domain="b"),
    ]
    result = meta_analysis.moderator(rows, "domain", ["domain"])
    assert result["k"] == 4
    assert result["qm"] is not None
    assert result["qm_df"] == 1
    assert result["qm_p"] is not None
    assert result["r2"] is not None
    # The categorical split explains the between-group difference.
    assert result["qm"] > 2
    # Every coefficient carries an interval and CR1 cluster-robust SEs are used.
    assert all(
        c["ci_low"] is not None and c["ci_high"] is not None
        for c in result["coefficients"]
    )
    assert result["covariance"] == "CR1"
    assert result["n_clusters"] == 4


def test_moderator_numeric_term():
    rows = [_effect(f"S{i}", 0.1 * i, 0.04, delay=i) for i in range(1, 7)]
    result = meta_analysis.moderator(rows, "delay", ["delay"])
    assert result["k"] == 6
    assert result["qm"] is not None
    assert any(c["term"] == "delay" for c in result["coefficients"])


def test_moderator_drops_missing_terms_instead_of_zero_imputing():
    rows = [
        _effect("A", 0.1, 0.04, delay=1.0),
        _effect("B", 0.2, 0.05, delay=2.0),
        _effect("C", 0.4, 0.05),  # no delay value
        _effect("D", 0.8, 0.05, delay=4.0),
        _effect("E", 1.0, 0.05, delay=5.0),
    ]
    result = meta_analysis.moderator(rows, "delay", ["delay"])
    assert result["k"] == 4
    assert result["n_dropped"] == 1
    # The missing row is not silently treated as delay = 0.
    delay = next(c for c in result["coefficients"] if c["term"] == "delay")
    assert delay["ci_low"] < delay["estimate"] < delay["ci_high"]


def test_moderator_numeric_categorical_interaction():
    rows = [
        _effect("S1", 0.1, 0.04, fields={"delay": 1.0, "format": "print"}),
        _effect("S2", 0.2, 0.04, fields={"delay": 2.0, "format": "print"}),
        _effect("S3", 0.3, 0.04, fields={"delay": 3.0, "format": "print"}),
        _effect("S4", 0.6, 0.04, fields={"delay": 4.0, "format": "video"}),
        _effect("S5", 0.7, 0.04, fields={"delay": 5.0, "format": "video"}),
        _effect("S6", 0.8, 0.04, fields={"delay": 6.0, "format": "video"}),
    ]
    result = meta_analysis.moderator(
        rows, "delay", ["delay", "format"], [["delay", "format"]]
    )
    assert result["interactions"] == [["delay", "format"]]
    assert "delay" in result["names"]
    # ``print`` is the reference level, so one dummy and one product column.
    assert "format:video" in result["names"]
    assert "delay * format:video" in result["names"]
    assert sum(1 for name in result["names"] if " * " in name) == 1
    if result["qm"] is not None:
        assert math.isfinite(result["qm"])


def test_moderator_numeric_numeric_interaction():
    rows = [
        _effect("S1", 0.1, 0.04, fields={"a": 1.0, "b": 2.0}),
        _effect("S2", 0.2, 0.04, fields={"a": 2.0, "b": 4.0}),
        _effect("S3", 0.3, 0.04, fields={"a": 3.0, "b": 6.0}),
        _effect("S4", 0.6, 0.04, fields={"a": 4.0, "b": 1.0}),
        _effect("S5", 0.7, 0.04, fields={"a": 5.0, "b": 3.0}),
        _effect("S6", 0.8, 0.04, fields={"a": 6.0, "b": 5.0}),
    ]
    result = meta_analysis.moderator(rows, "a", ["a", "b"], [["a", "b"]])
    assert "a * b" in result["names"]
    assert sum(1 for name in result["names"] if " * " in name) == 1


def test_moderator_categorical_categorical_interaction():
    rows = [
        _effect("S1", 0.1, 0.04, fields={"format": "print", "region": "us"}),
        _effect("S2", 0.2, 0.04, fields={"format": "print", "region": "eu"}),
        _effect("S3", 0.3, 0.04, fields={"format": "print", "region": "apac"}),
        _effect("S4", 0.6, 0.04, fields={"format": "video", "region": "us"}),
        _effect("S5", 0.7, 0.04, fields={"format": "video", "region": "eu"}),
        _effect("S6", 0.8, 0.04, fields={"format": "video", "region": "apac"}),
    ]
    result = meta_analysis.moderator(
        rows, "format", ["format", "region"], [["format", "region"]]
    )
    # (levels_format - 1) x (levels_region - 1) = 1 x 2 cross dummies.
    crossed = {name for name in result["names"] if " * " in name}
    assert crossed == {
        "format:video * region:eu",
        "format:video * region:us",
    }


def test_moderator_drops_rows_missing_interaction_component():
    rows = [
        _effect("S1", 0.1, 0.04, fields={"delay": 1.0, "format": "print"}),
        _effect("S2", 0.2, 0.04, fields={"delay": 2.0, "format": "video"}),
        _effect("S3", 0.3, 0.04, fields={"delay": 3.0, "format": "print"}),
        _effect("S4", 0.4, 0.04, fields={"delay": 4.0, "format": "video"}),
        _effect("S5", 0.5, 0.04, fields={"delay": 5.0}),  # no format value
        _effect("S6", 0.6, 0.04, fields={"delay": 6.0, "format": "print"}),
    ]
    result = meta_analysis.moderator(
        rows, "delay", ["delay", "format"], [["delay", "format"]]
    )
    assert result["k"] == 5
    assert result["n_dropped"] == 1


def test_effects_from_metrics_exposes_scalar_fields():
    rows = meta_analysis.effects_from_metrics(
        [
            {"_record": 0, "dv_name": "x", "yi": 0.2, "vi": 0.04, "delay": 1, "flag": True},
            {"_record": 1, "dv_name": "y", "yi": 0.5, "vi": 0.05, "nested": {"a": 1}},
        ]
    )
    assert rows[0]["fields"]["delay"] == 1
    assert rows[0]["fields"]["flag"] is True
    assert rows[0]["fields"]["dv_name"] == "x"
    # The record index and nested structures are not variables.
    assert "_record" not in rows[0]["fields"]
    assert "nested" not in rows[1]["fields"]


def test_moderator_and_subgroup_accept_field_name():
    rows = meta_analysis.effects_from_metrics(
        [
            {"_record": 0, "dv_name": "x", "yi": 0.1, "vi": 0.04, "format": "print"},
            {"_record": 0, "dv_name": "x", "yi": 0.2, "vi": 0.05, "format": "print"},
            {"_record": 1, "dv_name": "y", "yi": 0.9, "vi": 0.04, "format": "video"},
            {"_record": 1, "dv_name": "y", "yi": 1.0, "vi": 0.05, "format": "video"},
        ]
    )
    # ``format`` is exposed only through the flattened field map, not as a row
    # key or a role.
    assert all("format" not in row for row in rows)

    result = meta_analysis.moderator(rows, "format", ["format"])
    assert result["k"] == 4
    assert result["field"] == "format"
    assert result["qm"] is not None and result["qm"] > 2
    assert any(c["term"] == "format:video" for c in result["coefficients"])

    grouped = meta_analysis.subgroup(rows, "format")
    assert grouped["key"] == "format"
    assert grouped["k_groups"] == 2
    assert {g["value"] for g in grouped["groups"]} == {"print", "video"}


def test_pool_two_level_exposes_var_share_aliases():
    rows = [
        _effect("A", 0.1, 0.04),
        _effect("A", 0.2, 0.05),
        _effect("B", 0.4, 0.05),
        _effect("B", 0.6, 0.06),
    ]
    result = meta_analysis.pool_two_level(rows)
    assert result["k"] == 4
    for key in ("var_sampling_share", "var_within_share", "var_between_share"):
        assert result[key] is not None
    total = (
        result["var_sampling_share"]
        + result["var_within_share"]
        + result["var_between_share"]
    )
    assert total == pytest.approx(1.0, abs=1e-6)


def test_moderator_rank_deficient_is_graceful():
    # Five intervention levels over seven effects: the dummy design is
    # rank-deficient, so the fit must degrade gracefully instead of returning
    # an overflowing QM and zero-width intervals.
    levels = ["a", "b", "c", "d", "e", "a", "b"]
    rows = [
        _effect(
            f"S{i}", 0.1 + 0.1 * i, 0.04, fields={"intervention_type": level}
        )
        for i, level in enumerate(levels)
    ]
    result = meta_analysis.moderator(rows, "intervention_type", ["intervention_type"])
    assert result["k"] == 7
    assert result["note"] != "Singular design matrix."
    if result["qm"] is not None:
        assert math.isfinite(result["qm"]) and result["qm"] < 1e6
    for coef in result["coefficients"]:
        assert coef["estimate"] is None or math.isfinite(coef["estimate"])
        se = coef["se"]
        assert se is None or (math.isfinite(se) and se >= 0)
        if se is not None and se > 0:
            assert coef["ci_low"] is not None and coef["ci_high"] is not None


def test_egger_matches_independent_wls():
    import numpy as np

    rows = [
        _effect("A", 0.1, 0.01),
        _effect("B", 0.4, 0.04),
        _effect("C", 0.2, 0.09),
        _effect("D", 0.9, 0.16),
        _effect("E", 0.5, 0.25),
    ]
    result = meta_analysis.egger(rows)
    y = np.array([0.1, 0.4, 0.2, 0.9, 0.5])
    w = np.array([1.0 / v for v in (0.01, 0.04, 0.09, 0.16, 0.25)])
    x = np.column_stack([np.ones(5), np.sqrt([0.01, 0.04, 0.09, 0.16, 0.25])])
    beta = np.linalg.solve(x.T @ (w[:, None] * x), x.T @ (w * y))
    assert result["k"] == 5
    assert result["intercept"] == pytest.approx(float(beta[0]), rel=1e-6)
    assert result["slope"] == pytest.approx(float(beta[1]), rel=1e-6)
    assert 0.0 <= result["p"] <= 1.0


def test_leave_one_out_flags_and_reports():
    rows = [
        _effect("A", 0.1, 0.04),
        _effect("B", 0.15, 0.04),
        _effect("C", 3.0, 0.04),
    ]
    result = meta_analysis.leave_one_out(rows)
    assert result["full"]["k"] == 3
    assert len(result["rows"]) == 3
    omitted = {r["omitted"].split(" ")[0] for r in result["rows"]}
    assert {"A", "B", "C"} <= omitted
    assert all("influential" in r for r in result["rows"])


def test_leave_one_out_by_study():
    rows = [
        _effect("A", 0.1, 0.04),
        _effect("A", 0.2, 0.04),
        _effect("B", 0.6, 0.04),
    ]
    result = meta_analysis.leave_one_out(rows, by="study")
    # Omitting study A leaves one effect (<2), so only B is reported.
    assert len(result["rows"]) == 1
    assert result["rows"][0]["omitted"] == "B"


def test_forest_weights_and_pooled():
    rows = [
        _effect("A", 0.2, 0.04, dv_name="x"),
        _effect("B", 0.5, 0.05, dv_name="y"),
    ]
    result = meta_analysis.forest(rows)
    assert result["k"] == 2
    assert sum(r["weight"] for r in result["rows"]) == pytest.approx(100.0, abs=1e-6)
    assert result["pooled"]["estimate"] is not None


# ── agreement (§7) ───────────────────────────────────────────────────────


def test_gwet_ac1_known_value():
    result = meta_agreement.gwet_ac(
        [["a", "a"], ["a", "b"], ["b", "b"]], ["a", "b"]
    )
    assert result is not None
    assert result["pa"] == pytest.approx(2.0 / 3.0)
    assert result["pe"] == pytest.approx(0.5)
    assert result["coeff"] == pytest.approx(1.0 / 3.0)
    assert result["n2"] == 3


def test_gwet_ac2_linear_weights_bounds():
    cases = [["1", "1"], ["1", "2"], ["2", "2"], ["2", "3"], ["3", "3"]]
    ac1 = meta_agreement.gwet_ac(cases, ["1", "2", "3"])
    ac2 = meta_agreement.gwet_ac(cases, ["1", "2", "3"], meta_agreement.linear_weights(3))
    assert ac1 is not None and ac2 is not None
    assert -1.0 <= ac2["coeff"] <= 1.0
    assert ac2["coeff"] >= ac1["coeff"]


def test_screening_reliability_and_conflicts():
    criteria = [_criterion(1), _criterion(2)]
    screenings = [
        {"id": 1, "hit_id": 1, "owner": "anna", "stage": "abstract",
         "verdicts": {"criterion1": {"applies": "Yes"}, "criterion2": {"applies": "No"}}},
        {"id": 2, "hit_id": 1, "owner": "bob", "stage": "abstract",
         "verdicts": {"criterion1": {"applies": "Yes"}, "criterion2": {"applies": "Yes"}}},
        {"id": 3, "hit_id": 2, "owner": "anna", "stage": "abstract",
         "verdicts": {"criterion1": {"applies": "No"}, "criterion2": {"applies": "No"}}},
        {"id": 4, "hit_id": 2, "owner": "bob", "stage": "abstract",
         "verdicts": {"criterion1": {"applies": "No"}, "criterion2": {"applies": "No"}}},
    ]
    fields = meta_agreement._criterion_fields(criteria)
    case_maps = meta_agreement.screening_case_maps(screenings, criteria)
    rel = meta_agreement.reliability(fields, case_maps)
    by_name = {row["name"]: row for row in rel["fields"]}
    assert by_name["criterion1"]["ac1"] == pytest.approx(1.0)
    assert by_name["criterion2"]["ac1"] == pytest.approx(0.3846, rel=1e-3)
    assert rel["overall"]["ac1"] is not None

    conflicts = meta_agreement.conflicts(fields, case_maps, master="")
    assert conflicts["total"] == 1
    row = conflicts["rows"][0]
    assert row["field"] == "criterion2"
    assert row["case"] == [1, "criterion2"]
    assert row["values"] == {"anna": "No", "bob": "Yes"}
    assert row["master_value"] is None


def test_extraction_units_use_stable_dv_key():
    codebook = {
        "fields": [{"name": "sid", "role": "study_id"}],
        "metrics": {
            "enabled": True,
            "fields": [
                {"name": "dv", "role": "dv_name"},
                {"name": "domain", "role": "dv_domain",
                 "options": ["a", "b"], "editor": "select"},
            ],
        },
    }
    records_a = [{"study": {"sid": "S1"}, "metrics": [
        {"dv": "X", "domain": "a"}, {"dv": "Y", "domain": "b"}]}]
    records_b = [{"study": {"sid": "S1"}, "metrics": [
        {"dv": "Y", "domain": "b"}, {"dv": "X", "domain": "a"}]}]
    extractions = [
        {"hit_id": 1, "owner": "anna", "status": "extracted", "study_vars": {"records": records_a}},
        {"hit_id": 1, "owner": "bob", "status": "extracted", "study_vars": {"records": records_b}},
    ]
    fields, case_maps = meta_agreement.extraction_case_maps(extractions, codebook)
    # Reordered metrics must NOT create conflicts.
    assert meta_agreement.conflicts(fields, case_maps, master="")["total"] == 0
    keys = set(case_maps["domain"])
    assert (1, 0, "X") in keys and (1, 0, "Y") in keys

    records_c = [{"study": {"sid": "S1"}, "metrics": [
        {"dv": "Y", "domain": "a"}, {"dv": "X", "domain": "a"}]}]
    extractions.append(
        {"hit_id": 1, "owner": "cara", "status": "extracted", "study_vars": {"records": records_c}}
    )
    fields, case_maps = meta_agreement.extraction_case_maps(extractions, codebook)
    disagreements = meta_agreement.conflicts(fields, case_maps, master="")
    assert disagreements["total"] == 1
    assert disagreements["rows"][0]["case"] == [1, 0, "Y"]


async def test_resolve_screening_writes_master_row(session):
    repo = MetaRepository(session)
    hit = await repo.add_hit(title="Paper")
    result = await meta_agreement.resolve_screening(
        session,
        hit_id=hit.hit_id,
        criterion_key="criterion1",
        value="Yes",
        master="master",
        run_id="r1",
    )
    assert result["ok"] and result["value"] == "Yes"
    row = await repo.screening_for_hit(hit.hit_id, "master", "r1")
    assert row is not None
    assert row.owner == "master"
    assert row.verdicts["criterion1"]["applies"] == "Yes"


async def test_resolve_extraction_writes_master_row(session):
    codebook = {
        "fields": [{"name": "sid", "role": "study_id"}],
        "metrics": {
            "enabled": True,
            "fields": [
                {"name": "dv", "role": "dv_name"},
                {"name": "domain", "role": "dv_domain",
                 "options": ["a", "b"], "editor": "select"},
            ],
        },
    }
    repo = MetaRepository(session)
    hit = await repo.add_hit(title="Paper")
    records = [{"study": {"sid": "S1"}, "metrics": [{"dv": "X", "domain": "a"}]}]
    await repo.upsert_extraction(
        hit_id=hit.hit_id, owner="anna", scheme="s",
        study_vars={"records": records}, status="extracted",
    )
    result = await meta_agreement.resolve_extraction(
        session,
        hit_id=hit.hit_id,
        field_name="domain",
        value="b",
        master="master",
        record_index=0,
        metric_key="X",
        scheme="s",
        codebook=codebook,
    )
    assert result["ok"] and result["value"] == "b"
    master = await repo.get_extraction_for_hit(hit.hit_id, "master")
    assert master is not None and master.owner == "master"
    assert master.study_vars["records"][0]["metrics"][0]["domain"] == "b"
    # The other coder's extraction is untouched.
    anna = await repo.get_extraction_for_hit(hit.hit_id, "anna")
    assert anna is not None
    assert anna.study_vars["records"][0]["metrics"][0]["domain"] == "a"


# ── PRISMA / summary / report (§8/§9) ────────────────────────────────────


def test_prisma_counts_flow():
    hits = [{"hit_id": 1}, {"hit_id": 2}, {"hit_id": 3}]
    criteria = [_verdict_criterion("c1")]
    screenings = [
        {"id": 1, "hit_id": 1, "owner": "a", "stage": "abstract",
         "verdicts": {"c1": {"applies": "Yes"}}, "reason": ""},
        {"id": 2, "hit_id": 2, "owner": "a", "stage": "abstract",
         "verdicts": {"c1": {"applies": "No"}}, "reason": "Not relevant"},
    ]
    documents = [{"hit_id": 1, "status": "done"}, {"hit_id": 2, "status": "failed"}]
    extractions = [
        {"hit_id": 1, "owner": "a", "status": "extracted", "scheme": "s",
         "study_vars": {"records": [{"study": {"Study_ID": "S1"}, "metrics": []}]}},
        {"hit_id": 2, "owner": "a", "status": "excluded", "scheme": "s",
         "prescreen": {"rationale": "No control group"}},
    ]
    result = meta_prisma.prisma_counts(hits, criteria, screenings, documents, extractions)
    assert result["identification"]["total"] == 3
    assert result["screening"]["screened"] == 2
    assert result["screening"]["excluded"] == 1
    assert result["screening"]["included"] == 1
    assert result["screening"]["reasons"] == [{"reason": "Not relevant", "n": 1}]
    assert result["fulltext"]["assessed"] == 1
    assert result["fulltext"]["included"] == 1
    assert result["inclusion"]["studies"] == 1
    assert result["inclusion"]["reports"] == 1
    assert {r["reason"] for r in result["exclusion_reasons"]} >= {
        "Not relevant", "No control group"
    }


def test_summary_counts_levels_and_studies():
    codebook = {
        "fields": [
            {"name": "design", "role": "design", "options": ["rct", "quasi"], "editor": "select"},
        ],
        "metrics": {
            "enabled": True,
            "fields": [
                {"name": "domain", "role": "dv_domain",
                 "options": ["credibility", "sharing"], "editor": "select"},
            ],
        },
    }
    records_a = [{"study": {"Study_ID": "S1", "design": "rct"},
                  "metrics": [{"domain": "credibility"}]}]
    records_b = [{"study": {"Study_ID": "S2", "design": "rct"},
                  "metrics": [{"domain": "sharing"}]}]
    extractions = [
        {"hit_id": 1, "owner": "a", "status": "extracted", "study_vars": {"records": records_a}},
        {"hit_id": 2, "owner": "a", "status": "extracted", "study_vars": {"records": records_b}},
    ]
    result = meta_summary.build_summary(extractions, codebook)
    assert result["n_studies"] == 2
    assert result["n_records"] == 2
    by_name = {f["name"]: f for f in result["fields"]}
    design_rct = next(lv for lv in by_name["design"]["levels"] if lv["value"] == "rct")
    assert design_rct["n"] == 2 and design_rct["n_studies"] == 2
    domain = {lv["value"]: lv["n"] for lv in by_name["domain"]["levels"]}
    assert domain == {"credibility": 1, "sharing": 1}
    # No duplicate role block when a scheme field already carries the role.
    assert "dv_domain" not in by_name


def test_report_renders_markdown_and_docx():
    context = {
        "title": "Methods and Results - test",
        "generated": "2026-01-01 00:00",
        "methods": [{"heading": "Eligibility criteria", "paragraphs": ["Criterion text."]}],
        "results": [
            {
                "heading": "Synthesis of effects",
                "paragraphs": ["The pooled estimate was 0.45."],
                "tables": [
                    {
                        "title": "Pooled",
                        "columns": ["Model", "Estimate"],
                        "rows": [{"Model": "DL", "Estimate": 0.45}],
                    }
                ],
            }
        ],
    }
    markdown = meta_report.render_markdown(context)
    assert "# Methods and Results - test" in markdown
    assert "## Synthesis of effects" in markdown
    assert "| Model | Estimate |" in markdown
    docx_bytes = meta_report.render_docx_bytes(context)
    assert docx_bytes.startswith(b"PK")
    assert len(docx_bytes) > 1000


# ── publication bias / Bayesian / figures (contract §6 additions) ────────


def test_pet_peese_matches_independent_wls():
    import numpy as np

    rows = [
        _effect("A", 0.1, 0.01),
        _effect("B", 0.4, 0.04),
        _effect("C", 0.2, 0.09),
        _effect("D", 0.9, 0.16),
        _effect("E", 0.5, 0.25),
    ]
    result = meta_analysis.pet_peese(rows)
    y = np.array([0.1, 0.4, 0.2, 0.9, 0.5])
    v = np.array([0.01, 0.04, 0.09, 0.16, 0.25])
    w = 1.0 / v
    for key, x in (("pet", np.sqrt(v)), ("peese", v)):
        design = np.column_stack([np.ones(5), x])
        beta = np.linalg.solve(design.T @ (w[:, None] * design), design.T @ (w * y))
        assert result[key]["intercept"] == pytest.approx(float(beta[0]), rel=1e-6)
        assert result[key]["se"] is not None and result[key]["se"] > 0
    assert result["recommended"] in ("PET", "PEESE")
    assert result["k"] == 5
    # Egger keeps its slope columns through the shared WLS helper.
    assert meta_analysis.egger(rows)["slope"] is not None


def test_pet_peese_too_few_effects():
    result = meta_analysis.pet_peese([_effect("A", 0.2, 0.04), _effect("B", 0.4, 0.05)])
    assert result["k"] == 2
    assert result["pet"]["intercept"] is None
    assert result["recommended"] == "PET"


def test_trim_and_fill_symmetric_leaves_estimate():
    # Zero-mean, balanced-sign effects with distinct magnitudes (so the L0
    # ranking has no ties) must leave k0 at zero and the estimate unchanged.
    rows = [
        _effect("A", -3.0, 0.04),
        _effect("B", -2.0, 0.04),
        _effect("C", 1.0, 0.04),
        _effect("D", 4.0, 0.04),
    ]
    result = meta_analysis.trim_and_fill(rows)
    assert result["k"] == 4
    assert result["k0"] == 0
    assert result["estimate"] == pytest.approx(result["estimate_raw"])
    assert result["ci_low"] < result["estimate"] < result["ci_high"]


def test_trim_and_fill_asymmetric_imputes_left():
    # Small precise studies are positive; the adjusted pooled estimate must move
    # down toward the centre once the missing left-side studies are imputed.
    rows = [
        _effect("A", 0.6775, 0.0338),
        _effect("B", 0.6335, 0.0797),
        _effect("C", 1.0976, 0.0511),
        _effect("D", 0.4179, 0.0612),
        _effect("E", 0.6252, 0.0117),
        _effect("F", 0.1584, 0.0656),
        _effect("G", -0.5212, 0.0651),
        _effect("H", 0.7614, 0.0655),
    ]
    result = meta_analysis.trim_and_fill(rows)
    assert result["k"] == 8
    assert result["k0"] >= 1
    assert result["side"] == "left"
    assert result["estimate"] < result["estimate_raw"]
    assert result["ci_low"] < result["estimate"] < result["ci_high"]


def test_trim_and_fill_too_few_studies():
    result = meta_analysis.trim_and_fill([_effect("A", 0.2, 0.04), _effect("B", 0.5, 0.05)])
    assert result["k"] == 2
    assert result["k0"] is None
    assert result["estimate"] is None


def test_p_curve_binomial_sign_test():
    right_skew = [
        _effect("A", 0.2, 0.04, p=0.001),
        _effect("B", 0.3, 0.04, p=0.005),
        _effect("C", 0.4, 0.04, p=0.01),
        _effect("D", 0.5, 0.04, p=0.020),
        _effect("E", 0.6, 0.04, p=0.024),
    ]
    result = meta_analysis.p_curve(right_skew)
    assert result["n_significant"] == 5
    assert result["n_p_lt_025"] == 5
    assert result["p_half"] == pytest.approx(1.0 / 32.0)
    assert result["evidential"] is True

    balanced = [
        _effect("A", 0.2, 0.04, p=0.01),
        _effect("B", 0.3, 0.04, p=0.02),
        _effect("C", 0.4, 0.04, p=0.03),
        _effect("D", 0.5, 0.04, p=0.20),
    ]
    result = meta_analysis.p_curve(balanced)
    assert result["n_significant"] == 3
    assert result["n_p_lt_025"] == 2
    assert result["p_half"] == pytest.approx(0.5)
    assert result["evidential"] is False

    none = meta_analysis.p_curve([_effect("A", 0.2, 0.04)])
    assert none["n_significant"] == 0
    assert none["evidential"] is None
    assert "note" in none


def test_publication_bias_combines_battery():
    rows = [_effect(f"S{i}", 0.1 * i, 0.02, p=0.01) for i in range(1, 6)]
    result = meta_analysis.publication_bias(rows)
    assert result["k"] == 5
    assert result["k_total"] == 5
    assert set(result) == {"k", "k_total", "egger", "pet_peese", "trim_and_fill", "p_curve"}
    assert set(result["pet_peese"]) == {"k", "pet", "peese", "recommended"}
    assert set(result["trim_and_fill"]) >= {"k0", "side", "estimate", "estimate_raw"}


def test_bayes_pool_posterior_and_bf():
    rows = [
        _effect("A", 0.2, 0.04),
        _effect("B", 0.5, 0.05),
        _effect("C", 0.8, 0.09),
    ]
    result = meta_bayes.bayes_pool(rows)
    mu = result["mu"]
    assert result["k"] == 3 and result["k_total"] == 3
    assert mu["ci_low"] < mu["mean"] < mu["ci_high"]
    assert mu["ci_low"] < mu["median"] < mu["ci_high"]
    assert 0.0 <= mu["p_gt0"] <= 1.0
    tau = result["tau"]
    assert tau["mean"] >= 0.0
    assert tau["ci_low"] <= tau["mean"] <= tau["ci_high"]
    assert result["bf10"] is not None and result["bf10"] > 0
    assert result["bf01_tau0"] is not None and result["bf01_tau0"] > 0
    assert result["prior"] == {"mu_sd": 1.0, "tau_prior": "half-normal", "tau_scale": 0.5}


def test_bayes_pool_prior_response_and_empty():
    rows = [_effect("A", 0.3, 0.04), _effect("B", 0.5, 0.05)]
    wide = meta_bayes.bayes_pool(rows, mu_sd=100.0)
    narrow = meta_bayes.bayes_pool(rows, mu_sd=1.0)
    assert wide["prior"]["mu_sd"] == 100.0
    assert narrow["prior"]["mu_sd"] == 1.0
    empty = meta_bayes.bayes_pool([])
    assert empty["k"] == 0 and empty["mu"]["mean"] is None and empty["bf10"] is None


def test_bayes_sensitivity_rows_cover_presets():
    rows = [_effect("A", 0.2, 0.04), _effect("B", 0.5, 0.05), _effect("C", 0.8, 0.09)]
    sensitivity = meta_bayes.bayes_sensitivity(rows)
    assert len(sensitivity) == 20
    assert {row["mu_sd"] for row in sensitivity} == {1.0, 5.0, 10.0, 100.0}
    assert {(row["tau_prior"], row["tau_scale"]) for row in sensitivity} == {
        ("half-normal", 0.25),
        ("half-normal", 0.5),
        ("half-normal", 1.0),
        ("half-cauchy", 0.5),
        ("half-cauchy", 1.0),
    }
    assert all(row["bf10"] is None or row["bf10"] > 0 for row in sensitivity)
    assert all(
        row["mean"] is None or row["ci_low"] <= row["mean"] <= row["ci_high"]
        for row in sensitivity
    )


def test_figures_png_magic_bytes():
    counts = {
        "identification": {"total": 40, "database": 40, "other": 0},
        "screening": {"screened": 30, "excluded": 10, "included": 20,
                      "reasons": [{"reason": "Not relevant", "n": 10}]},
        "fulltext": {"sought": 20, "retrieved": 18, "not_retrieved": 2,
                     "assessed": 16, "excluded": 4,
                     "reasons": [{"reason": "No control", "n": 4}]},
        "inclusion": {"included": 12, "studies": 12, "reports": 16},
        "exclusion_reasons": [],
    }
    prisma = meta_figures.prisma_png(counts)
    assert prisma.startswith(b"\x89PNG")
    assert len(prisma) > 1000

    rows = [_effect(f"S{i}", 0.1 * i, 0.04, dv_name="x") for i in range(1, 5)]
    forest = meta_figures.forest_png(meta_analysis.forest(rows))
    assert forest.startswith(b"\x89PNG")
    empty = meta_figures.forest_png(meta_analysis.forest([]))
    assert empty.startswith(b"\x89PNG")


def test_report_renders_publication_bias_bayes_and_pptx():
    rows = [_effect(f"S{i}", 0.1 * i, 0.02, p=0.01) for i in range(1, 6)]
    bayes = meta_bayes.bayes_pool(rows)
    bayes["sensitivity"] = meta_bayes.bayes_sensitivity(rows)
    context = {
        "title": "Methods and Results - extras",
        "generated": "2026-01-01 00:00",
        "methods": [],
        "results": [],
        "pooled": meta_analysis.pool_dl(rows),
        "two_level": meta_analysis.pool_two_level(rows),
        "forest": meta_analysis.forest(rows),
        "publication_bias": meta_analysis.publication_bias(rows),
        "bayes": bayes,
    }
    markdown = meta_report.render_markdown(context)
    assert "## Publication bias" in markdown
    assert "## Bayesian synthesis" in markdown
    assert "Trim-and-fill" in markdown

    docx_bytes = meta_report.render_docx_bytes(context)
    assert docx_bytes.startswith(b"PK")

    pptx_bytes = meta_report.render_pptx_bytes(context)
    assert pptx_bytes.startswith(b"PK")
    assert len(pptx_bytes) > 2000


# ── multiverse / audit / extra figures (tranche 3) ───────────────────────


def test_multiverse_enumerates_full_grid():
    rows = [
        _effect("A", 0.2, 0.04, dv_name="x", domain="a", eligible_primary=True),
        _effect("B", 0.4, 0.05, dv_name="y", domain="a", eligible_primary=True),
        _effect("C", 0.6, 0.04, dv_name="z", domain="b", eligible_primary=True),
        _effect("D", 0.8, 0.05, dv_name="w", domain="b", eligible_primary=True),
    ]
    result = meta_multiverse.multiverse(rows)
    assert set(result) == {"k_total", "n_specs", "dimensions", "specs", "summary"}
    assert result["k_total"] == 4
    assert result["n_specs"] == 36  # 2 primary x 3 estimators x 3 domains x 2 outlier
    assert [d["name"] for d in result["dimensions"]] == [
        "primary", "estimator", "domain", "exclude_outliers"
    ]
    assert result["dimensions"][1]["levels"] == ["dl", "two_level", "fixed"]
    assert result["dimensions"][2]["levels"] == ["all", "a", "b"]
    assert len(result["specs"]) == 36
    assert result["specs"][0]["choices"] == {
        "primary": "primary",
        "estimator": "dl",
        "domain": "all",
        "exclude_outliers": "keep",
    }
    assert all(
        spec["estimate"] is not None and spec["se"] is not None
        for spec in result["specs"]
    )
    summary = result["summary"]
    assert summary["n_specs"] == 36 and summary["n_ok"] == 36
    assert summary["min"] <= summary["median"] <= summary["max"]
    assert summary["ci_low"] < summary["ci_high"]
    assert 0.0 <= summary["pct_positive"] <= 100.0
    assert summary["sampled"] is False and summary["n_enumerated"] == 36


def test_multiverse_skips_thin_specs_and_caps():
    rows = [
        _effect("A", 0.2, 0.04, domain="a", eligible_primary=True),
        _effect("B", 0.4, 0.05, domain="a", eligible_primary=True),
        _effect("C", 0.6, 0.04, domain="solo", eligible_primary=True),
    ]
    result = meta_multiverse.multiverse(rows)
    assert result["n_specs"] > 0
    # A domain with a single effect cannot be pooled and must be skipped.
    assert all(spec["choices"]["domain"] != "solo" for spec in result["specs"])
    assert all(spec["k"] >= 2 for spec in result["specs"])

    capped = meta_multiverse.multiverse(rows, max_specs=5)
    assert capped["n_specs"] == 5
    assert [spec["id"] for spec in capped["specs"]] == [1, 2, 3, 4, 5]
    # Truncation samples the full deterministic grid rather than the head.
    assert capped["summary"]["sampled"] is True
    assert capped["summary"]["n_enumerated"] > capped["n_specs"]
    domains_seen = {spec["choices"]["domain"] for spec in capped["specs"]}
    estimators_seen = {spec["choices"]["estimator"] for spec in capped["specs"]}
    assert domains_seen and estimators_seen
    assert all(spec["choices"]["domain"] != "solo" for spec in capped["specs"])


def test_multiverse_outlier_dimension():
    rows = [
        _effect("A", 0.2, 0.04, domain="a", eligible_primary=True),
        _effect("B", 0.4, 0.05, domain="a", eligible_primary=True),
        _effect("C", 5.0, 0.04, domain="a", eligible_primary=True),
    ]
    result = meta_multiverse.multiverse(rows)
    keep = {
        spec["k"] for spec in result["specs"]
        if spec["choices"]["exclude_outliers"] == "keep"
    }
    drop = {
        spec["k"] for spec in result["specs"]
        if spec["choices"]["exclude_outliers"] == "drop"
    }
    assert keep == {3}
    assert drop == {2}


AUDIT_CODEBOOK = {
    "fields": [
        {"name": "sid", "role": "study_id"},
        {"name": "design", "role": "design"},
    ],
    "metrics": {
        "enabled": True,
        "group": "metrics",
        "fields": [
            {"name": "dv", "role": "dv_name"},
            {"name": "domain", "role": "dv_domain"},
            {"name": "flag", "role": "eligible_primary"},
            {"name": "m1", "role": "m1"},
            {"name": "sd1", "role": "sd1"},
            {"name": "n1", "role": "n1"},
            {"name": "m2", "role": "m2"},
            {"name": "sd2", "role": "sd2"},
            {"name": "n2", "role": "n2"},
            {"name": "yi", "role": "yi"},
            {"name": "vi", "role": "vi"},
            {"name": "reason", "role": "missing_reason"},
        ],
    },
    "effect_families": ["descriptives", "yi"],
}


def test_variable_audit_flags_incomplete_and_missing():
    records = [
        {
            "study": {"sid": "S1", "design": "rct"},
            "metrics": [
                {
                    "dv": "outcome", "domain": "a", "flag": True,
                    "m1": 1.0, "sd1": 1.0, "n1": 10,
                    "m2": 0.5, "sd2": 1.0, "n2": 10,
                }
            ],
        },
        {
            "study": {"sid": "S2"},
            "metrics": [
                # Missing dv_name; group-2 descriptives absent; no reason.
                {"m1": 1.0, "sd1": 1.0, "n1": 10},
                # yi without a variance/SE, no reason.
                {"dv": "y2", "domain": "b", "flag": False, "yi": 0.3},
            ],
        },
    ]
    extractions = [
        {
            "hit_id": 1,
            "owner": "a",
            "status": "extracted",
            "study_vars": {"records": records},
        }
    ]
    result = meta_audit.variable_audit(extractions, AUDIT_CODEBOOK)
    assert result["n_extractions"] == 1
    assert result["n_records"] == 2
    assert result["n_metrics"] == 3

    by_name = {field["name"]: field for field in result["fields"]}
    assert by_name["sid"]["kind"] == "study"
    assert by_name["dv"]["kind"] == "metric"
    assert by_name["dv"]["role"] == "dv_name"
    assert by_name["dv"]["set"] == 2 and by_name["dv"]["total"] == 3
    assert by_name["dv"]["coverage"] == pytest.approx(2.0 / 3.0)
    assert by_name["dv"]["issues"]

    fields = {issue["field"]: issue for issue in result["issues"]}
    assert fields["dv"]["severity"] == "warn"
    assert fields["m2"]["count"] == 1
    assert "n2/m2/sd2" in fields["m2"]["message"]
    assert fields["vi"]["count"] == 1
    assert "without a vi/sei" in fields["vi"]["message"]
    assert any(
        "incomplete metrics do not record a missing_reason" in issue["message"]
        for issue in result["issues"]
    )
    assert fields["flag"]["count"] == 1
    assert all(
        issue["severity"] in ("warn", "info") for issue in result["issues"]
    )


def test_variable_audit_empty_inputs():
    result = meta_audit.variable_audit([], {})
    assert result["n_extractions"] == 0
    assert result["n_records"] == 0
    assert result["n_metrics"] == 0
    assert result["fields"] == []
    assert result["issues"] == []


def test_bayes_pool_exports_marginal_posterior():
    rows = [_effect("A", 0.2, 0.04), _effect("B", 0.5, 0.05), _effect("C", 0.8, 0.09)]
    result = meta_bayes.bayes_pool(rows)
    posterior = result["posterior"]
    assert len(posterior["mu"]) == len(posterior["density"]) > 0
    assert posterior["mu"] == sorted(posterior["mu"])
    assert all(value >= 0.0 for value in posterior["density"])
    # The density is normalised to unit area (trapezoid).
    mu, density = posterior["mu"], posterior["density"]
    step = mu[1] - mu[0]
    area = step * (0.5 * density[0] + sum(density[1:-1]) + 0.5 * density[-1])
    assert area == pytest.approx(1.0, rel=1e-6)
    assert posterior["mu"][0] <= result["mu"]["ci_low"]
    assert posterior["mu"][-1] >= result["mu"]["ci_high"]


def test_figures_funnel_spec_curve_and_bayes_png():
    rows = [
        _effect(f"S{i}", 0.1 * i, 0.04, dv_name="x", domain="a") for i in range(1, 6)
    ]
    funnel = meta_figures.funnel_png(rows)
    assert funnel.startswith(b"\x89PNG")
    assert len(funnel) > 1000
    assert meta_figures.funnel_png([]).startswith(b"\x89PNG")

    multiverse = meta_multiverse.multiverse(rows)
    curve = meta_figures.spec_curve_png(multiverse)
    assert curve.startswith(b"\x89PNG")
    assert meta_figures.spec_curve_png({"specs": []}).startswith(b"\x89PNG")

    bayes = meta_bayes.bayes_pool(rows)
    image = meta_figures.bayes_png(bayes)
    assert image.startswith(b"\x89PNG")
    assert meta_figures.bayes_png(meta_bayes.bayes_pool([])).startswith(b"\x89PNG")


def test_report_renders_multiverse_section():
    rows = [_effect(f"S{i}", 0.1 * i, 0.04, domain="a") for i in range(1, 6)]
    context = {
        "title": "Methods and Results - multiverse",
        "generated": "2026-01-01 00:00",
        "methods": [],
        "results": [],
        "multiverse": meta_multiverse.multiverse(rows),
    }
    markdown = meta_report.render_markdown(context)
    assert "## Multiverse / specification curve" in markdown
    assert "Specification-curve summary" in markdown
    docx_bytes = meta_report.render_docx_bytes(context)
    assert docx_bytes.startswith(b"PK")


# ── consensus rows (multi-coder analysis without a coder picker) ──────────

_CONSENSUS_CODEBOOK = {
    "version": 2,
    "groups": [{"name": "Study", "label": "Study"}],
    "fields": [
        {"name": "sid", "label": "Study id", "role": "study_id"},
        {"name": "design", "label": "Design", "role": "design"},
    ],
    "metrics": {
        "enabled": True,
        "group": "metrics",
        "fields": [
            {"name": "dv", "label": "Outcome", "role": "dv_name"},
            {"name": "m1", "role": "m1"},
            {"name": "sd1", "role": "sd1"},
            {"name": "n1", "role": "n1"},
            {"name": "m2", "role": "m2"},
            {"name": "sd2", "role": "sd2"},
            {"name": "n2", "role": "n2"},
        ],
    },
    "effect_families": ["descriptives"],
}


def _consensus_ext(owner, m1, *, hit_id=1, dv="X", scheme="meta", ext_id=1):
    return {
        "id": ext_id,
        "hit_id": hit_id,
        "owner": owner,
        "scheme": scheme,
        "status": "extracted",
        "study_vars": {
            "records": [
                {
                    "study": {"sid": "S1", "design": "rct"},
                    "metrics": [
                        {
                            "dv": dv,
                            "m1": m1,
                            "sd1": 1.0,
                            "n1": 20,
                            "m2": 4.0,
                            "sd2": 1.0,
                            "n2": 20,
                        }
                    ],
                }
            ]
        },
        "dv_metrics": [],
    }


def test_consensus_unanimous_matches_single_coder():
    """Unanimous multi-coder rows derive the same effects as one coding."""
    from qualcoder_api.services.meta_extract import refresh_dv_metrics

    pair = [_consensus_ext("anna", 5.0), _consensus_ext("bob", 5.0)]
    rows, report = meta_consensus.build_consensus_rows(pair, _CONSENSUS_CODEBOOK)
    assert len(rows) == 1
    assert report["n_consensus_units"] == 1
    assert report["n_dropped_conflicts"] == 0
    assert report["n_dropped_metrics"] == 0
    solo = refresh_dv_metrics(_consensus_ext("anna", 5.0), _CONSENSUS_CODEBOOK)
    merged = meta_analysis.build_effects(rows, _CONSENSUS_CODEBOOK)
    solo_effects = meta_analysis.build_effects([solo], _CONSENSUS_CODEBOOK)
    assert [r["effect"] for r in merged] == [r["effect"] for r in solo_effects]
    assert [r["variance"] for r in merged] == [r["variance"] for r in solo_effects]


def test_consensus_disagreement_without_master_drops_metric():
    """A disagreeing effect-critical field with no settled value excludes the
    field; the metric left without a derivable effect is dropped + counted."""
    pair = [_consensus_ext("anna", 5.0), _consensus_ext("bob", 9.0)]
    rows, report = meta_consensus.build_consensus_rows(pair, _CONSENSUS_CODEBOOK)
    assert len(rows) == 1
    assert report["n_dropped_conflicts"] == 1
    assert report["n_dropped_metrics"] == 1
    assert rows[0]["study_vars"]["records"][0]["metrics"] == []
    assert meta_analysis.build_effects(rows, _CONSENSUS_CODEBOOK) == []


def test_consensus_disagreement_with_settled_master_uses_master_value():
    """A settled master value resolves the disagreement instead of dropping."""
    from qualcoder_api.services.meta_extract import refresh_dv_metrics

    master = _consensus_ext("master", 7.0, ext_id=9)
    rows, report = meta_consensus.build_consensus_rows(
        [_consensus_ext("anna", 5.0), _consensus_ext("bob", 9.0), master],
        _CONSENSUS_CODEBOOK,
    )
    assert len(rows) == 1
    assert report["n_master_resolved"] == 1
    assert report["n_dropped_conflicts"] == 0
    metrics = rows[0]["study_vars"]["records"][0]["metrics"]
    assert metrics[0]["m1"] == 7.0
    effects = meta_analysis.build_effects(rows, _CONSENSUS_CODEBOOK)
    solo = refresh_dv_metrics(_consensus_ext("anna", 7.0), _CONSENSUS_CODEBOOK)
    solo_effects = meta_analysis.build_effects([solo], _CONSENSUS_CODEBOOK)
    assert [r["effect"] for r in effects] == [r["effect"] for r in solo_effects]


def test_consensus_single_coder_passes_through_unchanged():
    """One coding is returned as-is (today's behaviour)."""
    solo = _consensus_ext("anna", 5.0)
    rows, report = meta_consensus.build_consensus_rows([solo], _CONSENSUS_CODEBOOK)
    assert rows == [solo]
    assert report["n_single_owner"] == 1
    assert report["n_consensus_units"] == 0


def test_consensus_single_coder_metric_survives_alignment():
    """A metric coded by only one of two coders is kept, not conflicted."""
    anna = _consensus_ext("anna", 5.0)
    bob = _consensus_ext("bob", 5.0)
    bob["study_vars"]["records"][0]["metrics"].append(
        {"dv": "Y", "m1": 6.0, "sd1": 1.0, "n1": 20, "m2": 4.0, "sd2": 1.0, "n2": 20}
    )
    rows, report = meta_consensus.build_consensus_rows([anna, bob], _CONSENSUS_CODEBOOK)
    assert len(rows) == 1
    assert report["n_dropped_conflicts"] == 0
    dvs = [m["dv"] for m in rows[0]["study_vars"]["records"][0]["metrics"]]
    assert dvs == ["X", "Y"]


# ── CodingStudio folder importer ─────────────────────────────────────────

_CODINGSTUDIO_SCHEMA = {
    "schema_version": "3.1",
    "groups": ["Metadata & Identification", "Sample"],
    "common_fields": [
        {"name": "Study_ID", "group": "Metadata & Identification", "type": "string", "editor": "text", "required": True},
        {"name": "Title", "group": "Metadata & Identification", "type": "string", "editor": "text"},
        {"name": "DOI", "group": "Metadata & Identification", "type": "string|null", "editor": "text"},
        {"name": "Authors", "group": "Metadata & Identification", "type": "string", "editor": "text"},
        {"name": "Year", "group": "Metadata & Identification", "type": "integer", "editor": "number"},
        {"name": "N_Analyzed", "group": "Sample", "type": "integer|null", "editor": "number"},
        {"name": "Study_Description", "group": "Sample", "type": "string|null", "editor": "textarea"},
        {"name": "data_url", "group": "Sample", "type": "string|null", "editor": "text"},
        {"name": "factor_levels", "group": "Sample", "type": "list", "editor": "chips"},
    ],
    "dv_fields": [
        {"name": "dv_name", "group": "Other", "type": "string", "editor": "text"},
        {"name": "n1i", "group": "Other", "type": "number", "editor": "number"},
        {"name": "n2i", "group": "Other", "type": "number", "editor": "number"},
        {"name": "m1i", "group": "Other", "type": "number", "editor": "number"},
        {"name": "m2i", "group": "Other", "type": "number", "editor": "number"},
        {"name": "sd1i", "group": "Other", "type": "number", "editor": "number"},
        {"name": "sd2i", "group": "Other", "type": "number", "editor": "number"},
        {"name": "yi", "group": "Other", "type": "number", "editor": "number"},
        {"name": "vi", "group": "Other", "type": "number", "editor": "number"},
        {"name": "d_val", "group": "Other", "type": "number", "editor": "number"},
    ],
    "modules": {},
    "intervention_type_modules": {},
    "vocabularies": {"intervention_types": ["inoculation", "lateral_reading", "other"]},
}

_WORKBOOK_HEADER = [
    "an", "title", "abstract", "authors", "doi", "year", "source", "language",
    "C1_verdict", "C1_certainty", "C1_rationale",
    "C2_verdict", "C3_verdict", "C4_verdict", "Intervention_verdict",
    "Fulltext_Verdict", "Fulltext_Exclusion_Criterion", "Fulltext_Reason",
]


def _cs_record(study_id: str, title: str, doi: str) -> dict:
    return {
        "Study_ID": study_id,
        "Title": title,
        "DOI": doi,
        "Authors": "Doe, J",
        "Year": 2020,
        "N_Analyzed": 62,
        "Study_Description": "A short study description.",
        "data_url": "https://osf.io/abcde",
        "factor_levels": [{"factor": "condition", "levels": ["treatment", "control"]}],
        "DV_Metrics": [
            {
                "dv_name": "Accuracy",
                "n1i": 30, "n2i": 32, "m1i": 0.8, "m2i": 0.5,
                "sd1i": 1.0, "sd2i": 1.1, "yi": 0.25, "vi": 0.02,
            }
        ],
    }


def _cs_screening() -> dict:
    def block(verdicts: dict) -> dict:
        criteria = {}
        for key, value in verdicts.items():
            criteria[key] = {"verdict": value, "certainty": "High", "rationale": ""}
        return {"coder": "MF", "criteria": criteria}

    return {
        "an-a": {"an": "an-a", **block({"C1": "Yes", "C2": "Yes", "C3": "Yes", "C4": "Yes", "Intervention": "inoculation"})},
        "an-b": {"an": "an-b", **block({"C1": "No", "C2": "Yes", "C3": "Yes", "C4": "No", "Intervention": "none"})},
    }


def _tiny_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Size 4/Root 1 0 R>>\n%%EOF\n"
    )


def _write_codingstudio_folder(root: Path, *, workbook: bool = True, schema: bool = True) -> Path:
    from openpyxl import Workbook

    for sub in ("Papers", "Text", "Extraction", "Screening", "Codings", "Scripts/coding_web"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    if schema:
        (root / "Scripts/coding_web/schema.json").write_text(
            json.dumps(_CODINGSTUDIO_SCHEMA), encoding="utf-8"
        )
    (root / "Extraction/Study A.json").write_text(
        json.dumps([_cs_record("A2020_Exp1", "Study A: inoculation", "10.1000/aaaa")]),
        encoding="utf-8",
    )
    (root / "Extraction/Study B.json").write_text(
        json.dumps([_cs_record("B2021_Exp1", "Study B: media literacy", "10.1000/bbbb")]),
        encoding="utf-8",
    )
    (root / "Screening/MF.json").write_text(json.dumps(_cs_screening()), encoding="utf-8")
    # Per-coder full-text decisions are keyed by **study key** (not ``an``).
    (root / "Screening/fulltext - MF.json").write_text(
        json.dumps(
            {
                "Study A": {"exclude": False, "criterion": "", "note": "kept"},
                "Study B": {
                    "exclude": True,
                    "criterion": "C4",
                    "criterion_label": "Not a primary experimental study (C4)",
                    "note": "observational",
                },
            }
        ),
        encoding="utf-8",
    )
    # A real extra coder plus files the importer must skip (harmonizer overrides
    # and Space-Bunny variant/route/restored drafts).
    (root / "Codings/Study A - MF.json").write_text(
        json.dumps([_cs_record("A2020_Exp1", "Study A: inoculation", "10.1000/aaaa")]),
        encoding="utf-8",
    )
    (root / "Codings/Study A - harmonizer - MF.json").write_text("{}", encoding="utf-8")
    (root / "Codings/Study A - SB (restored).json").write_text("[]", encoding="utf-8")
    (root / "Codings/Study A - SB (route 2).json").write_text("[]", encoding="utf-8")
    (root / "Papers/Study A.pdf").write_bytes(_tiny_pdf())
    (root / "Text/Study A.txt").write_text("full text", encoding="utf-8")

    if workbook:
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(_WORKBOOK_HEADER)
        ws.append(["an-a", "Study A: inoculation", "Abstract A.", "Doe, J", "10.1000/aaaa", 2020, "J. Test", "eng",
                   "Yes", "High", "", "Yes", "Yes", "Yes", "inoculation", "Include", "", ""])
        ws.append(["an-b", "Study B: media literacy", "Abstract B.", "Roe, S", "10.1000/bbbb", 2021, "J. Test", "eng",
                   "No", "High", "", "Yes", "Yes", "No", "none", "Exclude",
                   "Not a primary experimental study (C4)", "observational design"])
        ws.append(["an-c", "Study C: no extraction", "Abstract C.", "Poe, T", "10.1000/cccc", 2022, "J. Test", "eng",
                   "Yes", "High", "", "Yes", "Yes", "Yes", "generic", "Include", "", ""])
        wb.save(root / "master_dataset.xlsx")
    return root


async def _open_codingstudio_project(tmp_path: Path):
    project_dir = tmp_path / "project.qda"
    (project_dir / "documents").mkdir(parents=True)
    engine = create_project_engine(project_dir / "data.qda")
    await create_all_tables(engine)
    factory = create_session_factory(engine)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO project (databaseversion, date, memo, about, bookmarkfile, "
                "bookmarkpos, codername, recently_used_codes) "
                "VALUES ('v39', '2026-01-01', '', 'QualCoder 4.0-test', 0, 0, 'default', '')"
            )
        )
        await session.commit()
    return engine, factory, project_dir


def test_legacy_aliases_resolve_codingstudio_fields():
    resolved = metric_by_role(
        {"N_Analyzed": 1572, "Study_Description": "desc", "data_url": "https://osf.io/x"}
    )
    assert resolved["sample_n"] == 1572
    assert resolved["description"] == "desc"
    assert resolved["dataset_url"] == "https://osf.io/x"
    # ``N_Recruited`` falls back too, and a present ``N_Analyzed`` wins.
    assert metric_by_role({"N_Recruited": 30})["sample_n"] == 30
    assert metric_by_role({"N_Analyzed": 20, "N_Recruited": 30})["sample_n"] == 20


def test_new_roles_and_aliases_resolve():
    from qualcoder_api.services.meta_roles import METRIC_ROLES, STUDY_ROLES

    assert {"publication", "fully_within", "intervention_id"} <= STUDY_ROLES
    assert {
        "veracity", "contrast_role", "beta_ci_low", "beta_ci_high",
        "source_location", "source_quote",
    } <= METRIC_ROLES

    # ``Publication`` wins over the legacy fallbacks; either fallback resolves.
    assert metric_by_role({"Publication": "preprint"})["publication"] == "preprint"
    assert metric_by_role(
        {"Publication": "preprint", "Publication_Type": "paper"}
    )["publication"] == "preprint"
    assert metric_by_role({"Publication_Type": "thesis"})["publication"] == "thesis"
    assert metric_by_role({"Publication_Category": "report"})["publication"] == "report"
    assert metric_by_role({"Fully_Within": True})["fully_within"] is True
    assert metric_by_role({"Intervention_ID": "iv-1"})["intervention_id"] == "iv-1"

    by_role = metric_by_role(
        {
            "veracity": "false",
            "contrast_role": 3,
            "beta_ci_low": 0.1,
            "beta_ci_high": 0.4,
            "source_location": "Table 2",
            "source_quote": "p < .05",
        }
    )
    assert by_role["veracity"] == "false"
    assert by_role["contrast_role"] == 3
    assert by_role["beta_ci_low"] == 0.1
    assert by_role["beta_ci_high"] == 0.4
    assert by_role["source_location"] == "Table 2"
    assert by_role["source_quote"] == "p < .05"

    fields = [
        {"name": "Publication", "role": "publication"},
        {"name": "source_quote", "role": "source_quote"},
    ]
    assert role_map(fields) == {"Publication": "publication", "source_quote": "source_quote"}


def test_derive_dv_metrics_merges_all_scalar_study_fields():
    codebook = {
        "fields": [
            {"name": "sid", "role": "study_id"},
            {"name": "Publication", "role": "publication"},
            {"name": "Correction_Source"},           # module field, no role
            {"name": "WEIRD_Western"},               # module-ish field, no role
            {"name": "Country"},                     # multi-label: kept
        ],
        "metrics": {"enabled": True, "group": "metrics", "fields": [
            {"name": "eff", "role": "yi"},
        ]},
        "effect_families": ["yi"],
    }
    response = [
        {
            "sid": "S1",
            "Publication": "preprint",
            "Correction_Source": 1,
            "WEIRD_Western": 1,
            "Country": ["USA"],
            # A list of objects is a container, not a set of labels.
            "factor_levels": [{"factor": "condition", "levels": ["t", "c"]}],
            "metrics": [{"eff": 0.2}],
        }
    ]
    records, _ = records_from_response(response, codebook)
    flat = derive_dv_metrics(records, role_map(study_fields(codebook)))
    assert flat[0]["sid"] == "S1"
    assert flat[0]["Publication"] == "preprint"
    assert flat[0]["Correction_Source"] == 1
    assert flat[0]["WEIRD_Western"] == 1
    assert flat[0]["eff"] == 0.2
    # Multi-label study fields survive as lists so they can be moderators.
    assert flat[0]["Country"] == ["USA"]
    assert "factor_levels" not in flat[0]
    assert flat[0]["_record"] == 0


def test_effects_from_metrics_keeps_scalar_list_fields():
    rows = meta_analysis.effects_from_metrics(
        [
            {
                "_record": 0,
                "dv_name": "x",
                "yi": 0.2,
                "vi": 0.04,
                "Country": ["US", "UK"],
                "factor_levels": [{"factor": "condition"}],
            }
        ]
    )
    assert rows[0]["fields"]["Country"] == ["US", "UK"]
    # Nested containers are not label sets and stay out of the field map.
    assert "factor_levels" not in rows[0]["fields"]


def test_subgroup_multilabel_row_joins_every_label():
    rows = meta_analysis.effects_from_metrics(
        [
            {"_record": 0, "Study_ID": "S1", "dv_name": "x", "yi": 0.2, "vi": 0.04,
             "Intervention_Type": ["a", "b"]},
            {"_record": 1, "Study_ID": "S2", "dv_name": "y", "yi": 0.5, "vi": 0.05,
             "Intervention_Type": ["b"]},
            {"_record": 2, "Study_ID": "S3", "dv_name": "z", "yi": 0.8, "vi": 0.04,
             "Intervention_Type": ["a"]},
            {"_record": 3, "Study_ID": "S4", "dv_name": "w", "yi": 0.7, "vi": 0.04,
             "Intervention_Type": []},
        ]
    )
    result = meta_analysis.subgroup(rows, "Intervention_Type")
    by_value = {g["value"]: g for g in result["groups"]}
    # A row carrying ["a", "b"] counts toward both label pools.
    assert set(by_value) == {"a", "b"}
    assert by_value["a"]["k"] == 2
    assert by_value["a"]["n_studies"] == 2
    assert by_value["b"]["k"] == 2
    assert by_value["b"]["n_studies"] == 2
    assert result["k_groups"] == 2


def test_moderator_multilabel_expands_per_label_terms():
    rows = meta_analysis.effects_from_metrics(
        [
            {"_record": 0, "Study_ID": "S1", "dv_name": "x", "yi": 0.1, "vi": 0.04,
             "Intervention_Type": ["a"]},
            {"_record": 1, "Study_ID": "S2", "dv_name": "x", "yi": 0.2, "vi": 0.04,
             "Intervention_Type": ["a", "b"]},
            {"_record": 2, "Study_ID": "S3", "dv_name": "y", "yi": 0.9, "vi": 0.04,
             "Intervention_Type": ["b"]},
            {"_record": 3, "Study_ID": "S4", "dv_name": "y", "yi": 1.0, "vi": 0.04,
             "Intervention_Type": ["b"]},
            {"_record": 4, "Study_ID": "S5", "dv_name": "z", "yi": 0.5, "vi": 0.04,
             "Intervention_Type": []},
        ]
    )
    result = meta_analysis.moderator(
        rows, "Intervention_Type", ["Intervention_Type"]
    )
    # The empty-list row carries no label and is dropped from the model.
    assert result["k"] == 4
    assert result["n_dropped"] == 1
    terms = [c["term"] for c in result["coefficients"]]
    assert "Intervention_Type:a" in terms
    assert "Intervention_Type:b" in terms
    assert all(
        c["estimate"] is None or math.isfinite(c["estimate"])
        for c in result["coefficients"]
    )


def test_subgroup_and_moderator_scalar_behaviour_unchanged():
    rows = meta_analysis.effects_from_metrics(
        [
            {"_record": 0, "Study_ID": "S1", "dv_name": "x", "yi": 0.1, "vi": 0.04,
             "format": "print"},
            {"_record": 1, "Study_ID": "S2", "dv_name": "x", "yi": 0.2, "vi": 0.04,
             "format": "print"},
            {"_record": 2, "Study_ID": "S3", "dv_name": "y", "yi": 0.9, "vi": 0.04,
             "format": "video"},
            {"_record": 3, "Study_ID": "S4", "dv_name": "y", "yi": 1.0, "vi": 0.04,
             "format": "video"},
        ]
    )
    grouped = meta_analysis.subgroup(rows, "format")
    by_value = {g["value"]: g for g in grouped["groups"]}
    assert set(by_value) == {"print", "video"}
    assert by_value["print"]["k"] == 2
    assert by_value["video"]["k"] == 2

    fit = meta_analysis.moderator(rows, "format", ["format"])
    assert fit["k"] == 4
    # A scalar categorical term still contributes its dummies (most common
    # level is the reference), not per-label indicator columns for a list.
    assert any(c["term"].startswith("format:") for c in fit["coefficients"])


_CS_SCHEMA_V31 = {
    "schema_version": "3.1",
    "groups": ["Metadata & Identification", "Other"],
    "common_fields": [
        {"name": "Study_ID", "type": "string", "editor": "text"},
        {"name": "Title", "type": "string", "editor": "text"},
        {"name": "Author_1", "type": "string", "editor": "text"},
        {"name": "Rationale_Notes", "type": "string", "editor": "textarea"},
        {"name": "Publication", "type": "string|null", "editor": "select",
         "options": [{"value": "preprint", "label": "Preprint"},
                     {"value": "report", "label": "Report"}]},
    ],
    "dv_fields": [
        {"name": "dv_domain", "type": "list", "editor": "multiselect"},
        {"name": "contrast_type", "type": "integer|null", "editor": "select",
         "options": [{"value": 1, "label": "Primary treatment vs no-treatment control"}]},
        {"name": "source_quote", "type": "string", "editor": "text"},
    ],
    "modules": {
        "lateral_reading_and_verification": {"fields": [
            {"name": "Assessment_Paradigm", "module": "lateral_reading_and_verification",
             "type": "integer|null", "editor": "select",
             "options": [{"value": 1, "label": "Technique-adoption paradigm"}]},
        ]},
        "fact_checking_training": {"fields": [
            {"name": "Assessment_Paradigm", "module": "fact_checking_training",
             "type": "integer|null", "editor": "select",
             "options": [{"value": 1, "label": "Claim-verification accuracy task"}]},
        ]},
    },
    "intervention_type_modules": {"inoculation": ["inoculation"]},
    "vocabularies": {
        "dv_domains": ["technique_recognition", "credibility"],
        "contrast_types": {
            "1": "primary_treatment_vs_no_treatment",
            "2": "treatment_vs_active_or_placebo",
        },
        "publication_types": ["preprint", "report"],
        "intervention_types": ["inoculation", "other"],
        "module_field_levels": {"Assessment_Paradigm": {
            "lateral_reading_and_verification": {"1": "Technique-adoption paradigm"},
            "fact_checking_training": {
                "1": "Claim-verification accuracy task",
                "2": "Discernment (true vs false)",
            },
        }},
    },
}


def test_schema_codebook_reads_vocabularies_and_moderator_hygiene():
    book = schema_codebook(_CS_SCHEMA_V31)
    by_name = {f["name"]: f for f in book["fields"]}
    dv = {f["name"]: f for f in book["metrics"]["fields"]}

    # Vocabulary-driven editors/options.
    assert by_name["Publication"]["editor"] == "select"
    assert by_name["Publication"]["options"] == ["Preprint", "Report"]
    assert dv["dv_domain"]["editor"] == "multiselect"
    assert dv["dv_domain"]["options"] == ["technique_recognition", "credibility"]
    assert dv["contrast_type"]["options"] == [
        "Primary treatment vs no-treatment control",
        "treatment_vs_active_or_placebo",
    ]

    # Moderator hygiene: free text / identifiers are not moderators.
    for name in ("Study_ID", "Title", "Author_1", "Rationale_Notes"):
        assert by_name[name]["moderator"] is False, name
    assert by_name["Publication"]["moderator"] is True
    assert dv["source_quote"]["moderator"] is False

    # Retired intervention types are dropped.
    assert "none" not in DEFAULT_INTERVENTION_TYPES
    assert "generic" not in DEFAULT_INTERVENTION_TYPES
    assert "other" in DEFAULT_INTERVENTION_TYPES


def test_schema_codebook_module_collision_keeps_one_field_with_overrides():
    book = schema_codebook(_CS_SCHEMA_V31)
    names = [f["name"] for f in book["fields"]]
    assert names.count("Assessment_Paradigm") == 1
    par = next(f for f in book["fields"] if f["name"] == "Assessment_Paradigm")
    assert par["module"] == "lateral_reading_and_verification"
    assert par["options"] == ["Technique-adoption paradigm"]
    assert par["module_options"]["lateral_reading_and_verification"] == [
        "Technique-adoption paradigm"
    ]
    assert par["module_options"]["fact_checking_training"] == [
        "Claim-verification accuracy task",
        "Discernment (true vs false)",
    ]
    assert book["intervention_type_modules"] == {"inoculation": ["inoculation"]}


def test_schema_codebook_module_identity_survives_normalisation():
    book = normalise_codebook(schema_codebook(_CS_SCHEMA_V31))
    par = next(f for f in book["fields"] if f["name"] == "Assessment_Paradigm")
    assert par["module"] == "lateral_reading_and_verification"
    assert par["module_options"]["fact_checking_training"] == [
        "Claim-verification accuracy task",
        "Discernment (true vs false)",
    ]
    assert book["intervention_type_modules"] == {"inoculation": ["inoculation"]}


def test_codingstudio_preview_counts(tmp_path: Path):
    folder = _write_codingstudio_folder(tmp_path / "cs")
    preview = preview_codingstudio(str(folder))
    assert preview["exists"] is True
    assert preview["papers"] == 1
    assert preview["texts"] == 1
    assert preview["extraction_files"] == 2
    assert preview["study_count"] == 2
    assert preview["screenings"] == [
        {"coder": "MF", "rows": 2},
        {"coder": "MF", "rows": 2},
    ]
    assert preview["workbook"]["rows"] == 3
    assert preview["schema_version"] == "3.1"
    assert preview["sample_studies"][0]["key"] == "Study A"
    assert preview["errors"] == []

    missing = preview_codingstudio(str(tmp_path / "nope"))
    assert missing["exists"] is False


async def test_codingstudio_import_creates_and_is_idempotent(tmp_path: Path):
    folder = _write_codingstudio_folder(tmp_path / "cs")
    engine, factory, project_dir = await _open_codingstudio_project(tmp_path)
    try:
        first = await import_codingstudio(factory, str(project_dir), str(folder))
        assert first["ok"] is True
        assert first["hits_imported"] == 3
        assert first["hits_skipped"] == 0
        assert first["extractions_imported"] == 3
        assert first["pdfs_linked"] == 1
        assert first["screening_rows"] == 10
        assert first["screening_by_stage"] == {"abstract": 5, "fulltext": 5}
        assert first["errors"] == []

        async with factory() as session:
            repo = MetaRepository(session)
            assert len(await repo.list_hits()) == 3
            abstract = await repo.list_screening(stage="abstract")
            fulltext = await repo.list_screening(stage="fulltext")
            assert len(abstract) == 5
            assert len(fulltext) == 5
            assert {row.owner for row in abstract} == {"MF", "LLM/base"}
            # The workbook's C1..C4 columns import as the base rater, with its
            # explicit decision stored as the reason.
            base = next(
                row
                for row in abstract
                if row.owner == "LLM/base" and row.verdicts["C4"]["applies"] == "No"
            )
            assert base.reason == "Exclude"
            excluded = next(row for row in fulltext if row.owner == "codingstudio" and row.verdicts["C4"]["applies"] == "No")
            assert excluded.reason == "observational design"
            # Per-coder full text is keyed by study key and imported under MF.
            mf_fulltext = next(
                row
                for row in fulltext
                if row.owner == "MF" and row.verdicts["C4"]["applies"] == "No"
            )
            assert mf_fulltext.reason == "observational"

            extractions = await repo.list_extractions()
            assert len(extractions) == 3
            flat = extractions[0].dv_metrics[0]
            assert flat["yi"] == 0.25
            assert flat["vi"] == 0.02
            assert flat["n1i"] == 30
            assert flat["_record"] == 0
            assert extractions[0].status == "extracted"

            documents = await repo.list_documents()
            assert len(documents) == 1
            assert documents[0].source_id is not None

            scheme = await repo.get_scheme(name="codingstudio")
            assert scheme is not None
            book = json.loads(scheme.codebook)
            assert book["version"] == 2
            assert book["metrics"]["group"] == "DV_Metrics"
            assert {"descriptives", "yi", "d_g"} <= set(book["effect_families"])
            roles = {
                field["name"]: field["role"]
                for field in [*book["fields"], *book["metrics"]["fields"]]
            }
            assert roles["Study_ID"] == "study_id"
            assert roles["N_Analyzed"] == "sample_n"
            assert roles["data_url"] == "dataset_url"
            assert roles["yi"] == "yi"

        second = await import_codingstudio(factory, str(project_dir), str(folder))
        assert second["hits_imported"] == 0
        assert second["pdfs_linked"] == 0
        async with factory() as session:
            repo = MetaRepository(session)
            assert len(await repo.list_hits()) == 3
            assert await repo.count_screening() == 10
            assert len(await repo.list_extractions()) == 3
            assert len(await repo.list_documents()) == 1
    finally:
        await dispose_engine(engine)


async def test_codingstudio_import_without_workbook_falls_back_to_extractions(tmp_path: Path):
    folder = _write_codingstudio_folder(
        tmp_path / "cs_minimal", workbook=False, schema=False
    )
    engine, factory, project_dir = await _open_codingstudio_project(tmp_path)
    try:
        result = await import_codingstudio(factory, str(project_dir), str(folder))
        assert result["hits_imported"] == 2
        assert result["extractions_imported"] == 3
        async with factory() as session:
            repo = MetaRepository(session)
            hits = await repo.list_hits()
            assert {hit.doi for hit in hits} == {"10.1000/aaaa", "10.1000/bbbb"}
            scheme = await repo.get_scheme(name="codingstudio")
            assert scheme is not None
            book = json.loads(scheme.codebook)
            assert book["metrics"]["group"] == "DV_Metrics"
            roles = {
                field["name"]: field["role"]
                for field in [*book["fields"], *book["metrics"]["fields"]]
            }
            assert roles["N_Analyzed"] == "sample_n"
    finally:
        await dispose_engine(engine)


def _cs_simple_verdicts() -> dict:
    """C1..C4 all ``Yes`` for one abstract screening entry."""
    return {
        key: {"verdict": "Yes", "certainty": "High", "rationale": ""}
        for key in ("C1", "C2", "C3", "C4")
    }


def _write_workbook(root: Path, rows: list[list]) -> None:
    """Write a ``master_dataset.xlsx`` with ``rows`` after a fixed header."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(_WORKBOOK_HEADER)
    for row in rows:
        ws.append(row)
    wb.save(root / "master_dataset.xlsx")


async def test_codingstudio_workbook_row_key_resolves_blank_accession(tmp_path: Path):
    """A blank ``an`` keys its workbook row as ``row-<worksheet row>``.

    The reference's ``Screening/*.json`` stores such rows as ``row-N`` (N is
    the 1-based worksheet row: the header is row 1, so the first data row is
    2). Row 3 below has a blank ``an`` and must resolve for the ``row-3``
    screening entry.
    """
    folder = tmp_path / "cs_rowkey"
    (folder / "Screening").mkdir(parents=True)
    _write_workbook(
        folder,
        [
            # Worksheet row 2: has an accession.
            ["an-x", "Study X", "Abstract X", "Doe, J", "10.1000/xx", 2020, "J", "eng"],
            # Worksheet row 3: blank ``an`` -> keyed ``row-3``.
            ["", "Study Y", "Abstract Y", "Roe, S", "10.1000/yy", 2021, "J", "eng"],
        ],
    )
    (folder / "Screening/MF.json").write_text(
        json.dumps(
            {
                "an-x": {"an": "an-x", "criteria": _cs_simple_verdicts()},
                "row-3": {"an": "", "criteria": _cs_simple_verdicts()},
            }
        ),
        encoding="utf-8",
    )

    engine, factory, project_dir = await _open_codingstudio_project(tmp_path)
    try:
        result = await import_codingstudio(factory, str(project_dir), str(folder))
        assert result["errors"] == []
        assert result["hits_imported"] == 2
        # Both the an-keyed and the row-3 entry import (2 abstract rows).
        assert result["screening_rows"] == 2
        assert result["screening_by_stage"] == {"abstract": 2, "fulltext": 0}

        async with factory() as session:
            repo = MetaRepository(session)
            hits = {hit.title: hit for hit in await repo.list_hits()}
            screening = await repo.list_screening(stage="abstract")
            assert {row.hit_id for row in screening} == {
                hits["Study X"].hit_id,
                hits["Study Y"].hit_id,
            }

        # Re-importing stays stable (no duplicate screening rows).
        await import_codingstudio(factory, str(project_dir), str(folder))
        async with factory() as session:
            repo = MetaRepository(session)
            assert await repo.count_screening() == 2
    finally:
        await dispose_engine(engine)


async def test_codingstudio_title_only_hit_is_idempotent(tmp_path: Path):
    """A hit with neither DOI nor authors is not re-inserted on re-import.

    ``add_hits`` cannot dedupe such a row (no key), so the sidecar must keep
    the study from being imported twice.
    """
    folder = tmp_path / "cs_title_only"
    folder.mkdir()
    _write_workbook(
        folder,
        # No DOI, no authors: only the title would be there to dedupe on.
        [["an-a", "Title only", "Abstract", "", "", 2020, "J", "eng"]],
    )

    engine, factory, project_dir = await _open_codingstudio_project(tmp_path)
    try:
        first = await import_codingstudio(factory, str(project_dir), str(folder))
        assert first["hits_imported"] == 1
        second = await import_codingstudio(factory, str(project_dir), str(folder))
        assert second["hits_imported"] == 0
        async with factory() as session:
            repo = MetaRepository(session)
            assert len(await repo.list_hits()) == 1
    finally:
        await dispose_engine(engine)


async def test_codingstudio_stage_counts_match_stored_rows(tmp_path: Path):
    """``screening_by_stage`` reports stored (deduped) rows, not attempts.

    Two workbook rows share a DOI, so they dedupe to one hit and the base
    rater would attempt two identical abstract rows. The summary must report
    the single stored row so ``abstract + fulltext == screening_rows``.
    """
    folder = tmp_path / "cs_stage"
    folder.mkdir()
    _write_workbook(
        folder,
        [
            ["an-1", "Dup", "Abstract 1", "Doe, J", "10.1000/dup", 2020, "J", "eng",
             "Yes", "High", "", "Yes", "Yes", "Yes", "inoculation", "", "", ""],
            ["an-2", "Dup", "Abstract 2", "Doe, J", "10.1000/dup", 2020, "J", "eng",
             "Yes", "High", "", "Yes", "Yes", "Yes", "inoculation", "", "", ""],
            ["an-3", "Unique", "Abstract 3", "Roe, S", "10.1000/uniq", 2021, "J", "eng",
             "Yes", "High", "", "Yes", "Yes", "Yes", "inoculation", "", "", ""],
        ],
    )

    engine, factory, project_dir = await _open_codingstudio_project(tmp_path)
    try:
        result = await import_codingstudio(factory, str(project_dir), str(folder))
        # Two rows dedupe to one hit; the base rater's third row is distinct.
        assert result["hits_imported"] == 2
        assert result["screening_rows"] == 2
        assert result["screening_by_stage"] == {"abstract": 2, "fulltext": 0}
        assert (
            result["screening_by_stage"]["abstract"]
            + result["screening_by_stage"]["fulltext"]
            == result["screening_rows"]
        )
        async with factory() as session:
            repo = MetaRepository(session)
            assert await repo.count_screening() == result["screening_rows"]
    finally:
        await dispose_engine(engine)


async def test_codingstudio_pdf_matches_by_first_author_and_year(tmp_path: Path):
    """A PDF whose stem is not the study key falls back to first-author+year."""
    folder = tmp_path / "cs_pdf"
    (folder / "Papers").mkdir(parents=True)
    (folder / "Extraction").mkdir(parents=True)
    (folder / "Extraction/Paper A.json").write_text(
        json.dumps(
            [
                {
                    "Study_ID": "Smith2020",
                    "Title": "Workbook title for Smith",
                    "Authors": "Smith, John",
                    "Year": 2020,
                    "DOI": "",
                    "DV_Metrics": [{"dv_name": "Accuracy", "yi": 0.2, "vi": 0.04}],
                }
            ]
        ),
        encoding="utf-8",
    )
    _write_workbook(
        folder,
        [
            ["an-a", "Workbook title for Smith", "Abstract", "Smith, John", "", 2020, "J", "eng"],
        ],
    )
    (folder / "Papers/Smith (2020).pdf").write_bytes(_tiny_pdf())

    engine, factory, project_dir = await _open_codingstudio_project(tmp_path)
    try:
        result = await import_codingstudio(factory, str(project_dir), str(folder))
        assert result["pdfs_linked"] == 1
        assert result["pdfs_unmatched"] == 0
        assert result["errors"] == []
    finally:
        await dispose_engine(engine)


async def test_codingstudio_errors_are_capped(tmp_path: Path):
    """Unmatchable screening keys cannot flood ``errors``; the cap is reported."""
    folder = tmp_path / "cs_errors"
    (folder / "Screening").mkdir(parents=True)
    _write_workbook(
        folder,
        [["an-a", "Study A", "Abstract A", "Doe, J", "10.1000/aa", 2020, "J", "eng"]],
    )
    (folder / "Screening/MF.json").write_text(
        json.dumps(
            {
                f"missing-{i}": {"an": f"missing-{i}", "criteria": _cs_simple_verdicts()}
                for i in range(MAX_ERRORS + 10)
            }
        ),
        encoding="utf-8",
    )

    engine, factory, project_dir = await _open_codingstudio_project(tmp_path)
    try:
        result = await import_codingstudio(factory, str(project_dir), str(folder))
        assert len(result["errors"]) == MAX_ERRORS
        assert result["errors_truncated"] == 10
        assert all("no study for key" in line for line in result["errors"])
    finally:
        await dispose_engine(engine)

