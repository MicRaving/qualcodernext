"""Generate a small, ready-to-open Meta-analysis sample project for QCnext.

Creates `samples/meta/` with:
  imports/            raw search-result files (EBSCO XML, RIS, CSV)
  scheme.json         the coding scheme (codebook v2, role-based)
  criteria.json       the screening criteria
  meta-sample.qda/    a seeded QCnext project (hits, screening, scheme,
                      extractions with effect sizes and assigned PDFs)
  README.md           how to use it

Run with the backend venv (from anywhere):
  backend/.venv/Scripts/python.exe scripts/make-meta-sample.py

The project is regenerated from scratch on every run. It is intentionally
small (10 hits, 6 included) so the Analyze tab loads instantly.
"""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

SAMPLES = ROOT / "samples" / "meta"
PROJECT = SAMPLES / "meta-sample.qda"
IMPORTS = SAMPLES / "imports"

CODERS = ["anna", "bob"]

# ── sample records ────────────────────────────────────────────────────────
# Each record: title, authors, doi, year, source, design, country, sample_n,
# intervention, setting, open_data, plus its effect metrics.
STUDIES = [
    {
        "key": "Roozenbeek & van der Linden (2019)",
        "title": "Fake news game confers psychological resistance against online misinformation",
        "authors": "Roozenbeek, Jon; van der Linden, Sander",
        "doi": "10.1057/s41599-019-0279-9",
        "year": 2019, "design": "rct", "country": "NL", "sample_n": 1420,
        "intervention_type": "inoculation", "setting": "online", "open_data": "yes",
        "metrics": [
            {"dv": "Technique recognition", "domain": "technique_recognition", "primary": True,
             "m1": 0.62, "sd1": 0.21, "n1": 700, "m2": 0.54, "sd2": 0.22, "n2": 720},
        ],
    },
    {
        "key": "Pennycook et al. (2020)",
        "title": "The Implied Truth Effect: Attaching Warnings to a Subset of Fake News Headlines",
        "authors": "Pennycook, Gordon; Bear, Adam; Collins, Evan T.; Rand, David G.",
        "doi": "10.1287/mnsc.2019.3478",
        "year": 2020, "design": "rct", "country": "US", "sample_n": 560,
        "intervention_type": "accuracy_prompt", "setting": "online", "open_data": "yes",
        "metrics": [
            {"dv": "Perceived accuracy of true news", "domain": "credibility", "primary": True,
             "m1": 0.71, "sd1": 0.18, "n1": 280, "m2": 0.63, "sd2": 0.19, "n2": 280},
            {"dv": "Sharing intention for false news", "domain": "sharing_intention", "primary": True,
             "m1": 0.20, "sd1": 0.25, "n1": 280, "m2": 0.31, "sd2": 0.27, "n2": 280,
             "polarity": "higher_is_worse"},
        ],
    },
    {
        "key": "Guess et al. (2020)",
        "title": "A digital media literacy intervention increases discernment between mainstream and false news",
        "authors": "Guess, Andrew M.; Lerner, Michael; Lyons, Benjamin; Montgomery, Jacob M.; Nyhan, Brendan; Reifler, Jason; Sircar, Neelanjan",
        "doi": "10.1073/pnas.1920498117",
        "year": 2020, "design": "field", "country": "US", "sample_n": 2055,
        "intervention_type": "media_literacy", "setting": "field", "open_data": "no",
        "metrics": [
            {"dv": "Discernment index", "domain": "credibility", "primary": True,
             "m1": 0.38, "sd1": 0.24, "n1": 1024, "m2": 0.31, "sd2": 0.23, "n2": 1031},
        ],
    },
    {
        "key": "Vraga & Bode (2018)",
        "title": "I do not believe you: how providing a source corrects health misperceptions",
        "authors": "Vraga, Emily K.; Bode, Leticia",
        "doi": "10.1080/1369118X.2017.1363889",
        "year": 2018, "design": "rct", "country": "US", "sample_n": 731,
        "intervention_type": "correction", "setting": "online", "open_data": "no",
        "metrics": [
            {"dv": "Misperception belief", "domain": "credibility", "primary": True,
             "m1": 0.44, "sd1": 0.20, "n1": 366, "m2": 0.52, "sd2": 0.21, "n2": 365,
             "polarity": "higher_is_worse"},
        ],
    },
    {
        "key": "Maertens et al. (2021)",
        "title": "The Misinformation Susceptibility Test (MIST): a psychometrically validated measure",
        "authors": "Maertens, Rakoen; Götz, Friedrich M.; Golino, Hudson F.; Roozenbeek, Jon; Schneider, Claudia R.; Kyrychenko, Yara; Kerr, John R.; Stieger, Stefan; McClanahan, William P.; van der Linden, Sander",
        "doi": "10.3758/s13428-023-02147-9",
        "year": 2021, "design": "rct", "country": "DE", "sample_n": 876,
        "intervention_type": "lateral_reading", "setting": "online", "open_data": "yes",
        "metrics": [
            {"dv": "Sourcing behaviour", "domain": "technique_recognition", "primary": True,
             "m1": 0.55, "sd1": 0.26, "n1": 438, "m2": 0.41, "sd2": 0.25, "n2": 438},
        ],
    },
    {
        "key": "Lewandowsky & Yesilada (2021)",
        "title": "Inoculation and debunking reduce the impact of misinformation about climate change",
        "authors": "Lewandowsky, Stephan; Yesilada, Mert",
        "doi": "10.1038/s41558-021-01092-8",
        "year": 2021, "design": "rct", "country": "UK", "sample_n": 640,
        "intervention_type": "inoculation", "setting": "online", "open_data": "no",
        "metrics": [
            {"dv": "Sharing intention (true news)", "domain": "sharing_intention", "primary": True,
             "m1": 0.66, "sd1": 0.22, "n1": 320, "m2": 0.58, "sd2": 0.23, "n2": 320},
            {"dv": "Technique recognition", "domain": "technique_recognition", "primary": False,
             "m1": 0.49, "sd1": 0.24, "n1": 320, "m2": 0.45, "sd2": 0.24, "n2": 320},
        ],
    },
]

EXCLUDED = [
    ("Consumer attitudes toward advertising", "Lee, Mara", "10.1000/sample-ex1", 2017, "No misinformation intervention (C1)"),
    ("An observational study of news consumption", "Okafor, Chidi", "10.1000/sample-ex2", 2019, "No control/comparison group (C2)"),
    ("Impfen und Fehlinformation: eine Studie", "Schmidt, Lena", "10.1000/sample-ex3", 2020, "Not English (C3)"),
    ("A qualitative interview study of fact-checkers", "Rossi, Giulia", "10.1000/sample-ex4", 2022, "Not a primary experimental study (C4)"),
]


def _abstract(study: dict) -> str:
    return (
        f"Randomised experiment testing a {study['intervention_type'].replace('_', ' ')} "
        f"intervention against a control condition (N = {study['sample_n']}). "
        "Participants rated the accuracy of true and false news headlines and reported "
        "their sharing intentions; the intervention condition showed improved discernment."
    )


CRITERIA = [
    {"key": "c1", "label": "Misinformation intervention", "kind": "verdict", "pass_values": ["Yes"],
     "exclude_reason": "No misinformation intervention (C1)", "gating": 1,
     "prompt_text": "Does the study test a misinformation intervention (inoculation, media literacy, correction, accuracy prompt, labelling)?"},
    {"key": "c2", "label": "Control / comparison group", "kind": "verdict", "pass_values": ["Yes"],
     "exclude_reason": "No control/comparison group (C2)", "gating": 1,
     "prompt_text": "Does the study include a control or comparison condition?"},
    {"key": "c3", "label": "English language", "kind": "verdict", "pass_values": ["Yes"],
     "exclude_reason": "Not English (C3)", "gating": 1,
     "prompt_text": "Is the report written in English?"},
    {"key": "c4", "label": "Primary experimental study", "kind": "verdict", "pass_values": ["Yes"],
     "exclude_reason": "Not a primary experimental study (C4)", "gating": 1,
     "prompt_text": "Is this a primary experimental (randomised or quasi-experimental) study?"},
]

SCHEME = {
    "name": "inoculation-sample",
    "label": "Inoculation sample scheme",
    "description": "Sample coding scheme used by the QCnext meta-analysis demo project.",
    "codebook": {
        "version": 2,
        "category": "Meta",
        "groups": [
            {"name": "Study", "label": "Study"},
            {"name": "Sample", "label": "Sample"},
            {"name": "Intervention", "label": "Intervention"},
        ],
        "fields": [
            {"name": "study_id", "label": "Study ID", "group": "Study", "role": "study_id", "required": True},
            {"name": "title", "label": "Title", "group": "Study", "role": "title", "editor": "textarea"},
            {"name": "authors", "label": "Authors", "group": "Study", "role": "authors"},
            {"name": "year", "label": "Year", "group": "Study", "role": "year", "type": "integer", "editor": "number"},
            {"name": "design", "label": "Design", "group": "Study", "role": "design", "editor": "select",
             "options": ["rct", "quasi", "field"]},
            {"name": "open_data", "label": "Open data", "group": "Study", "editor": "select",
             "options": ["yes", "no"], "moderator": True},
            {"name": "internal_notes", "label": "Internal notes", "group": "Study", "editor": "textarea",
             "moderator": False, "description": "Shown here to demonstrate hiding a variable from the moderators."},
            {"name": "country", "label": "Country", "group": "Sample", "role": "country", "editor": "select",
             "options": ["US", "UK", "DE", "NL", "other"]},
            {"name": "sample_n", "label": "Sample size", "group": "Sample", "role": "sample_n",
             "type": "integer", "editor": "number"},
            {"name": "setting", "label": "Setting", "group": "Sample", "role": "setting", "editor": "select",
             "options": ["lab", "field", "online"]},
            {"name": "intervention_type", "label": "Intervention type", "group": "Intervention",
             "role": "intervention_type", "editor": "select",
             "options": ["inoculation", "accuracy_prompt", "media_literacy", "lateral_reading", "correction"]},
        ],
        "metrics": {
            "enabled": True,
            "group": "Outcome",
            "label": "Outcomes & effect sizes",
            "fields": [
                {"name": "dv_name", "label": "Outcome (DV)", "role": "dv_name", "required": True},
                {"name": "dv_domain", "label": "Domain", "role": "dv_domain", "editor": "select",
                 "options": ["credibility", "sharing_intention", "technique_recognition"]},
                {"name": "polarity", "label": "Polarity", "role": "polarity", "editor": "select",
                 "options": ["higher_is_better", "higher_is_worse"]},
                {"name": "contrast_type", "label": "Contrast type", "role": "contrast_type", "editor": "select",
                 "options": ["1", "2", "3"]},
                {"name": "timepoint_1", "label": "Timepoint", "role": "timepoint_1", "editor": "select",
                 "options": ["post", "followup"]},
                {"name": "eligible_primary", "label": "Primary contrast", "role": "eligible_primary", "type": "boolean"},
                {"name": "n1", "label": "n (group 1)", "role": "n1", "type": "integer", "editor": "number"},
                {"name": "m1", "label": "M (group 1)", "role": "m1", "type": "number", "editor": "number"},
                {"name": "sd1", "label": "SD (group 1)", "role": "sd1", "type": "number", "editor": "number"},
                {"name": "n2", "label": "n (group 2)", "role": "n2", "type": "integer", "editor": "number"},
                {"name": "m2", "label": "M (group 2)", "role": "m2", "type": "number", "editor": "number"},
                {"name": "sd2", "label": "SD (group 2)", "role": "sd2", "type": "number", "editor": "number"},
                {"name": "coder_confidence", "label": "Coder confidence", "editor": "select",
                 "options": ["high", "medium", "low"], "moderator": True},
            ],
        },
        "effect_families": ["descriptives"],
        "code_fields": [
            {"name": "notes", "label": "Coding notes", "instruction": "Free-text rationale for this coding."},
        ],
    },
}


def _hits() -> list[dict]:
    rows = []
    for s in STUDIES:
        rows.append({
            "title": s["title"], "authors": s["authors"], "doi": s["doi"], "year": str(s["year"]),
            "source": "Sample Journal", "abstract": _abstract(s),
        })
    for title, authors, doi, year, _reason in EXCLUDED:
        rows.append({
            "title": title, "authors": authors, "doi": doi, "year": str(year),
            "source": "Sample Journal", "abstract": "Sample record used to exercise the exclusion reasons.",
        })
    return rows


def write_imports() -> None:
    IMPORTS.mkdir(parents=True, exist_ok=True)
    hits = _hits()
    # CSV
    import csv

    with (IMPORTS / "search_results.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["title", "authors", "doi", "year", "source", "abstract"])
        writer.writeheader()
        writer.writerows(hits)
    # RIS
    ris_lines: list[str] = []
    for h in hits:
        ris_lines += ["TY  - JOUR", f"TI  - {h['title']}", f"AU  - {h['authors']}", f"DO  - {h['doi']}",
                      f"PY  - {h['year']}", f"JO  - {h['source']}", f"AB  - {h['abstract']}", "ER  - ", ""]
    (IMPORTS / "search_results.ris").write_text("\n".join(ris_lines), encoding="utf-8")
    # EBSCO-ish XML
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', "<records>"]
    for h in hits:
        xml += ["  <record>", f"    <title>{h['title']}</title>", f"    <abstract>{h['abstract']}</abstract>",
                f"    <contributors>{h['authors']}</contributors>", f"    <doi>{h['doi']}</doi>",
                f"    <publicationDate>{h['year']}-01-01</publicationDate>", f"    <source>{h['source']}</source>",
                "    <language>eng</language>", "  </record>"]
    xml.append("</records>")
    (IMPORTS / "search_results.xml").write_text("\n".join(xml), encoding="utf-8")

    (SAMPLES / "criteria.json").write_text(json.dumps(CRITERIA, indent=2), encoding="utf-8")
    (SAMPLES / "scheme.json").write_text(json.dumps(SCHEME, indent=2), encoding="utf-8")


def make_pdf(path: Path, title: str, body: str) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(img)
    draw.multiline_text((80, 90), title, fill="black", spacing=8)
    draw.multiline_text((80, 220), body, fill="black", spacing=6)
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    data = buf.getvalue()
    path.write_bytes(data)
    return data


async def seed() -> None:
    from httpx import ASGITransport, AsyncClient
    from qualcoder_api.main import app, service  # noqa: F401

    if PROJECT.exists():
        shutil.rmtree(PROJECT)
    PROJECT.parent.mkdir(parents=True, exist_ok=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://sample") as client:
        r = await client.post("/api/v1/projects", json={"project_path": str(PROJECT), "codername": CODERS[0]})
        r.raise_for_status()

        xml = (IMPORTS / "search_results.xml").read_bytes()
        r = await client.post("/api/v1/meta/hits/import",
                              files={"file": ("search_results.xml", xml, "text/xml")},
                              data={"search_run": "sample-search"})
        r.raise_for_status()
        hits = (await client.get("/api/v1/meta/hits", params={"limit": 1000})).json()["hits"]
        by_doi = {h.get("doi"): h for h in hits}

        r = await client.put("/api/v1/meta/criteria", json=CRITERIA)
        r.raise_for_status()
        r = await client.post("/api/v1/meta/schemes", json=SCHEME)
        r.raise_for_status()

        # screening: included studies pass all four criteria; excluded fail one.
        reasons = {
            "10.1000/sample-ex1": "c1", "10.1000/sample-ex2": "c2",
            "10.1000/sample-ex3": "c3", "10.1000/sample-ex4": "c4",
        }
        for doi, hit in by_doi.items():
            failing = reasons.get(doi)
            verdicts = {c["key"]: {"applies": "No" if c["key"] == failing else "Yes",
                                   "certainty": "High"} for c in CRITERIA}
            await client.put("/api/v1/meta/screening", json={
                "hit_id": hit["hit_id"], "run_id": "sample", "owner": CODERS[0],
                "stage": "abstract", "verdicts": verdicts,
            })

        # a second coder agrees on most; on two *already-excluded* studies they
        # disagree on C2, so the Agreement dialog has conflicts without changing
        # the included set (those records still fail their own criterion).
        conflicts_left = 2
        for doi, hit in by_doi.items():
            failing = reasons.get(doi)
            verdicts = {c["key"]: {"applies": "No" if c["key"] == failing else "Yes",
                                   "certainty": "Medium"} for c in CRITERIA}
            if failing and failing != "c2" and conflicts_left > 0:
                verdicts["c2"] = {"applies": "No", "certainty": "Low"}
                conflicts_left -= 1
            await client.put("/api/v1/meta/screening", json={
                "hit_id": hit["hit_id"], "run_id": "sample", "owner": CODERS[1],
                "stage": "abstract", "verdicts": verdicts,
            })

        # extractions + PDFs for the included studies
        for study in STUDIES:
            hit = by_doi.get(study["doi"])
            if hit is None:
                continue
            metrics = []
            for m in study["metrics"]:
                metrics.append({
                    "dv_name": m["dv"], "dv_domain": m["domain"], "polarity": m.get("polarity", "higher_is_better"),
                    "contrast_type": "1", "timepoint_1": "post", "eligible_primary": m.get("primary", True),
                    "n1": m["n1"], "m1": m["m1"], "sd1": m["sd1"], "n2": m["n2"], "m2": m["m2"], "sd2": m["sd2"],
                    "coder_confidence": "high",
                })
            record = {"study": {
                "study_id": study["key"], "title": study["title"], "authors": study["authors"],
                "year": study["year"], "design": study["design"], "country": study["country"],
                "sample_n": study["sample_n"], "setting": study["setting"],
                "intervention_type": study["intervention_type"], "open_data": study["open_data"],
                "internal_notes": "sample",
            }, "metrics": metrics}
            r = await client.put("/api/v1/meta/extractions", json={
                "hit_id": hit["hit_id"], "owner": CODERS[0], "scheme": SCHEME["name"],
                "study_vars": {"records": [record]},
            })
            r.raise_for_status()
            pdf_path = IMPORTS / f"{study['key'].split(' (')[0].replace(' & ', '_')}.pdf"
            data = make_pdf(pdf_path, study["title"], _abstract(study))
            r = await client.post(f"/api/v1/meta/downloads/assign/{hit['hit_id']}",
                                  files={"file": (pdf_path.name, data, "application/pdf")})
            r.raise_for_status()

        r = await client.get("/api/v1/meta/status")
        r.raise_for_status()
        print(json.dumps(r.json(), indent=2))


def write_readme() -> None:
    (SAMPLES / "README.md").write_text(
        "# Meta-analysis sample project\n\n"
        "A small, ready-to-open QCnext project for testing the Meta-analysis workspace.\n\n"
        "Open **`samples/meta/meta-sample.qda`** in QCnext (or copy it anywhere first).\n\n"
        "It contains 10 search hits (6 included, 4 excluded for the four criteria), four\n"
        "inclusion criteria, one role-based coding scheme, screening verdicts from two coders\n"
        "(with a couple of deliberate disagreements for the Agreement dialog), six coded\n"
        "extractions with descriptives-based effect sizes across three outcome domains, and a\n"
        "PDF per included study.\n\n"
        "Also here:\n\n"
        "- `imports/search_results.xml` / `.ris` / `.csv` — the same search results in three\n"
        "  formats, for testing the Import labeler.\n"
        "- `scheme.json` / `criteria.json` — the scheme and criteria, for reference/reuse.\n\n"
        "Regenerate everything with:\n\n"
        "```\n"
        "backend/.venv/Scripts/python.exe scripts/make-meta-sample.py\n"
        "```\n",
        encoding="utf-8",
    )


def main() -> int:
    write_imports()
    write_readme()
    asyncio.run(seed())
    print(f"\nSample project: {PROJECT}")
    print(f"Raw import files: {IMPORTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
