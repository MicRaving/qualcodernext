"""REFI-QDA (.qdp XML) project export and import.

Pure async module: no FastAPI imports. ``session_factory`` is an
``async_sessionmaker`` bound to the open project's engine. The XML uses the
REFI-QDA project namespace ``urn:QDA-XML:project:1.0``; text content is
escaped by ElementTree, never assembled by string concatenation.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as etree

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import (
    CaseRepository,
    CodeRepository,
    CodingRepository,
    SourceRepository,
)

QDA_NS = "urn:QDA-XML:project:1.0"


def _q(tag: str) -> str:
    """Return ``tag`` qualified with the QDA-XML namespace."""
    return f"{{{QDA_NS}}}{tag}"


def local_name(tag: str) -> str:
    """Strip the namespace prefix from an element tag (helper, import side)."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children(elem: etree.Element, tag: str) -> list[etree.Element]:
    """Direct children of ``elem`` whose local name matches ``tag``."""
    return [child for child in elem if local_name(child.tag) == tag]


def _descendant_text(elem: etree.Element, tag: str) -> str:
    """Text of the first descendant whose local name matches ``tag``."""
    for node in elem.iter():
        if local_name(node.tag) == tag and node.text:
            return node.text
    return ""


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------

async def export_refi_qdp(session_factory: async_sessionmaker, project_name: str) -> str:
    """Build a REFI-QDA .qdp XML string for the open project."""
    etree.register_namespace("", QDA_NS)

    code_guid: dict[int, str] = {}
    cat_guid: dict[int, str] = {}
    source_guid: dict[int, str] = {}

    async with session_factory() as session:
        code_rows = (
            await session.execute(
                select(
                    tables.code_name.c.cid,
                    tables.code_name.c.name,
                    tables.code_name.c.color,
                    tables.code_name.c.catid,
                )
            )
        ).all()
        cat_rows = (
            await session.execute(
                select(tables.code_cat.c.catid, tables.code_cat.c.name, tables.code_cat.c.supercatid)
            )
        ).all()
        source_rows = (
            await session.execute(
                select(
                    tables.source.c.id,
                    tables.source.c.name,
                    tables.source.c.fulltext,
                    tables.source.c.mediapath,
                )
            )
        ).all()
        coding_rows = (
            await session.execute(
                select(
                    tables.code_text.c.fid,
                    tables.code_text.c.pos0,
                    tables.code_text.c.pos1,
                    tables.code_text.c.cid,
                )
            )
        ).all()
        case_rows = (
            await session.execute(
                select(tables.cases.c.caseid, tables.cases.c.name, tables.cases.c.memo)
            )
        ).all()

    for row in code_rows:
        code_guid[row[0]] = str(uuid.uuid4())
    for row in cat_rows:
        cat_guid[row[0]] = str(uuid.uuid4())
    text_sources = [
        row
        for row in source_rows
        if row[3] is None or row[3].startswith("/docs/") or row[3].startswith("docs:")
    ]
    for row in text_sources:
        source_guid[row[0]] = str(uuid.uuid4())

    root = etree.Element(_q("QDAProject"))

    # -- CodeBook ------------------------------------------------------
    codebook = etree.SubElement(root, _q("CodeBook"))
    top_codes = etree.SubElement(codebook, _q("Codes"))
    top_categories = etree.SubElement(codebook, _q("Categories"))

    codes_by_cat: dict[int | None, list] = {}
    for row in code_rows:
        codes_by_cat.setdefault(row[3], []).append(row)
    cats_by_super: dict[int | None, list] = {}
    for row in cat_rows:
        cats_by_super.setdefault(row[2], []).append(row)

    def add_code(parent: etree.Element, row) -> None:
        etree.SubElement(
            parent,
            _q("Code"),
            guid=code_guid[row[0]],
            name=row[1] or "",
            color=row[2] or "#FFFFFF",
        )

    def add_category(parent: etree.Element, row) -> None:
        catid = row[0]
        category = etree.SubElement(
            parent, _q("Category"), guid=cat_guid[catid], name=row[1] or ""
        )
        nested = etree.SubElement(category, _q("Categories"))
        codes = etree.SubElement(category, _q("Codes"))
        for child in cats_by_super.get(catid, []):
            add_category(nested, child)
        for code_row in codes_by_cat.get(catid, []):
            add_code(codes, code_row)

    for row in codes_by_cat.get(None, []):
        add_code(top_codes, row)
    for row in cats_by_super.get(None, []):
        add_category(top_categories, row)

    # -- Sources -------------------------------------------------------
    sources = etree.SubElement(root, _q("Sources"))
    for row in text_sources:
        source = etree.SubElement(
            sources,
            _q("TextSource"),
            guid=source_guid[row[0]],
            name=row[1] or "",
            mediaType="TEXT",
        )
        description = etree.SubElement(source, _q("Description"))
        fulltext = etree.SubElement(description, _q("FullText"))
        fulltext.text = row[2] or ""

    # -- CodedTexts ----------------------------------------------------
    coded_texts = etree.SubElement(root, _q("CodedTexts"))
    for row in coding_rows:
        fid, pos0, pos1, cid = row
        if fid not in source_guid or cid not in code_guid:
            continue
        coded = etree.SubElement(coded_texts, _q("CodedText"), guid=str(uuid.uuid4()))
        description = etree.SubElement(coded, _q("Description"))
        selection = etree.SubElement(description, _q("CodedSelection"))
        etree.SubElement(selection, _q("SourceRef"), targetGUID=source_guid[fid])
        etree.SubElement(selection, _q("TextRef"), start=str(pos0), end=str(pos1))
        etree.SubElement(description, _q("CodeRef"), targetGUID=code_guid[cid])

    # -- Cases ---------------------------------------------------------
    cases = etree.SubElement(root, _q("Cases"))
    for row in case_rows:
        case = etree.SubElement(cases, _q("Case"), guid=str(uuid.uuid4()), name=row[1] or "")
        description = etree.SubElement(case, _q("Description"))
        memo = etree.SubElement(description, _q("Memo"))
        memo.text = row[2] or ""

    etree.indent(root)
    return etree.tostring(root, encoding="unicode", xml_declaration=True)


# ----------------------------------------------------------------------
# Import
# ----------------------------------------------------------------------

async def import_refi_qdp(
    session_factory: async_sessionmaker, xml_bytes: bytes, codername: str
) -> dict:
    """Parse a QDP XML document and write it into the project DB.

    Returns ``{"ok": True, "message": ..., "codes": n, "categories": n,
    "sources": n, "codings": n, "cases": n}``. Raises ``ValueError`` for
    malformed XML (the API layer converts that to 422).
    """
    try:
        root = etree.fromstring(xml_bytes)
    except etree.ParseError as err:
        raise ValueError("Invalid QDP file") from err
    if local_name(root.tag) != "QDAProject":
        raise ValueError("Invalid QDP file")

    code_guid: dict[str, int] = {}
    cat_guid: dict[str, int] = {}
    source_guid: dict[str, int] = {}
    case_guid: dict[str, int] = {}
    source_fulltext: dict[int, str] = {}
    counts = {"codes": 0, "categories": 0, "sources": 0, "codings": 0, "cases": 0}

    async with session_factory() as session:
        code_repo = CodeRepository(session)
        cat_repo = CodeRepository(session)
        source_repo = SourceRepository(session)
        coding_repo = CodingRepository(session)
        case_repo = CaseRepository(session)

        async def find_code_cid(name: str) -> int | None:
            row = (
                await session.execute(
                    select(tables.code_name.c.cid).where(tables.code_name.c.name == name)
                )
            ).first()
            return row[0] if row else None

        async def find_catid(name: str) -> int | None:
            row = (
                await session.execute(
                    select(tables.code_cat.c.catid).where(tables.code_cat.c.name == name)
                )
            ).first()
            return row[0] if row else None

        async def import_code(elem: etree.Element, catid: int | None) -> None:
            name = elem.get("name") or ""
            guid = elem.get("guid")
            cid = await find_code_cid(name)
            if cid is None:
                code = await code_repo.add_code(
                    name=name,
                    owner=codername,
                    catid=catid,
                    color=elem.get("color") or "#FFFFFF",
                )
                cid = code.cid if code is not None else None
                counts["codes"] += 1
            if guid and cid is not None:
                code_guid[guid] = cid

        async def import_category(elem: etree.Element, supercatid: int | None) -> None:
            name = elem.get("name") or ""
            guid = elem.get("guid")
            catid = await find_catid(name)
            if catid is None:
                category = await cat_repo.add_category(
                    name=name, owner=codername, supercatid=supercatid
                )
                catid = category.catid if category is not None else None
                counts["categories"] += 1
            if guid and catid is not None:
                cat_guid[guid] = catid
            for categories_elem in _children(elem, "Categories"):
                for child in _children(categories_elem, "Category"):
                    await import_category(child, catid)
            for codes_elem in _children(elem, "Codes"):
                for code_elem in _children(codes_elem, "Code"):
                    await import_code(code_elem, catid)

        for section in _children(root, "CodeBook"):
            for categories_elem in _children(section, "Categories"):
                for category_elem in _children(categories_elem, "Category"):
                    await import_category(category_elem, None)
            for codes_elem in _children(section, "Codes"):
                for code_elem in _children(codes_elem, "Code"):
                    await import_code(code_elem, None)

        for section in _children(root, "Sources"):
            for source_elem in _children(section, "TextSource"):
                name = source_elem.get("name") or ""
                fulltext = _descendant_text(source_elem, "FullText")
                row = (
                    await session.execute(
                        select(tables.source.c.id, tables.source.c.fulltext).where(
                            tables.source.c.name == name
                        )
                    )
                ).first()
                if row is not None:
                    fid = row[0]
                    source_fulltext[fid] = row[1] or ""
                else:
                    source = await source_repo.add_source(
                        name=name, mediapath=None, fulltext=fulltext, owner=codername
                    )
                    fid = source.id
                    source_fulltext[fid] = fulltext
                    counts["sources"] += 1
                guid = source_elem.get("guid")
                if guid:
                    source_guid[guid] = fid

        for section in _children(root, "CodedTexts"):
            for coded_elem in _children(section, "CodedText"):
                source_ref: str | None = None
                code_ref: str | None = None
                start, end = 0, 0
                for description in _children(coded_elem, "Description"):
                    for selection in _children(description, "CodedSelection"):
                        for ref in _children(selection, "SourceRef"):
                            source_ref = ref.get("targetGUID")
                        for ref in _children(selection, "TextRef"):
                            try:
                                start = int(ref.get("start") or 0)
                                end = int(ref.get("end") or 0)
                            except ValueError:
                                start = end = 0
                    for ref in _children(description, "CodeRef"):
                        code_ref = ref.get("targetGUID")
                if source_ref is None or code_ref is None:
                    continue
                fid = source_guid.get(source_ref)
                cid = code_guid.get(code_ref)
                if fid is None or cid is None:
                    continue
                try:
                    await coding_repo.add_text_coding(
                        cid=cid,
                        fid=fid,
                        seltext=source_fulltext.get(fid, "")[start:end],
                        pos0=start,
                        pos1=end,
                        owner=codername,
                    )
                    counts["codings"] += 1
                except IntegrityError:
                    await session.rollback()

        for section in _children(root, "Cases"):
            for case_elem in _children(section, "Case"):
                name = case_elem.get("name") or ""
                memo = _descendant_text(case_elem, "Memo")
                row = (
                    await session.execute(
                        select(tables.cases.c.caseid).where(tables.cases.c.name == name)
                    )
                ).first()
                if row is not None:
                    continue
                case = await case_repo.add_case(name=name, owner=codername, memo=memo)
                if case is None:  # pragma: no cover - name was just verified absent
                    continue
                counts["cases"] += 1
                guid = case_elem.get("guid")
                if guid:
                    case_guid[guid] = case.caseid

    message = (
        f"Imported {counts['codes']} codes, {counts['categories']} categories, "
        f"{counts['sources']} sources, {counts['codings']} codings, {counts['cases']} cases"
    )
    return {"ok": True, "message": message, **counts}
