"""NVivo (``.nvpx``) project importer — best-effort.

An ``.nvpx`` file is the NVivo-for-Mac / NVivo 12+ Windows cross-platform
project container: a plain ZIP that holds the project as XML. Two layouts
are seen in the wild (community reverse-engineering notes + QSR's NVivo
XML project family, NVivo 9-15):

* a single ``NvivoProject.xml`` at the archive root, or
* a ``__nvivo`` archive folder with the project split across XML files
  (``Sources.xml``, ``Nodes.xml``, ``Coding.xml``, ...).

The XML follows the NVivo project format family: a root ``NvivoProject``
element (namespace prefixes differ between versions, so all matching is by
local element name) with a ``Content`` section holding:

* ``Sources`` > ``Documents`` > ``Document`` — ``guid``/``id`` and ``name``
  attributes; the ``Content`` child holds the document text (HTML-ish
  markup), ``Description`` the memo. Audio/video/image documents carry a
  ``type`` attribute and no text.
* ``Nodes`` > ``Node`` — ``guid``/``id`` and ``name`` attributes; tree
  nodes nest ``Node`` children; ``Description`` is the node memo.
* ``Coding`` > ``Coding`` — ``source`` and ``node`` attributes (the GUIDs
  of the document and node), ``Position`` children with ``Start``/``End``
  character offsets (``Begin`` accepted as an alias for ``Start``).

What the importer covers (best-effort; no section failure aborts the rest):

* Documents with text content -> text sources (markup unwrapped to plain
  text, block elements become newlines).
* Named nodes -> codes; node folders (nodes with children) -> categories
  built from the node tree, so the classic ``category >> code`` structure
  survives; a folder that is itself coded is imported as both a category
  and a code.
* Codings with parseable positions -> text codings (positions clamped to
  the source text; the coded segment text is the slice). Codings that are
  unparseable or reference a missing document/node are counted in
  ``skipped_codings`` — never an import failure.

Raises ``ValueError`` when the archive carries no NVivo marker.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as etree
import zipfile
from contextlib import suppress
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import (
    CodeRepository,
    CodingRepository,
    SourceRepository,
)

# Archive paths containing this fragment mark a split NVivo project bundle.
_NVIVO_BUNDLE_FRAGMENT = "__nvivo"
# Root tag of the NVivo project document (optional namespace prefix).
_NVIVO_ROOT_RE = re.compile(rb"<(?:\w[\w.-]*:)?NvivoProject[\s>/]", re.IGNORECASE)

# Block-level markup inside document <Content> — unwrapped to newlines.
_BLOCK_TAGS = frozenset(
    {"p", "br", "div", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
)
# Media kinds whose documents carry no text to import.
_NON_TEXT_DOC_TYPES = frozenset(
    {"audio", "video", "image", "picture", "dataset", "external", "movie", "sound"}
)

_MAX_XML_MEMBERS_PROBED = 20


def local_name(tag: str) -> str:
    """Strip any namespace URI from an element tag."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children(elem: etree.Element, name: str) -> list[etree.Element]:
    """Direct children of ``elem`` whose local name matches ``name``."""
    return [child for child in elem if local_name(child.tag) == name]


def _descendant_text(elem: etree.Element, name: str) -> str:
    """Text of the first descendant whose local name matches ``name``."""
    for node in elem.iter():
        if node is not elem and local_name(node.tag) == name and node.text:
            return node.text
    return ""


def _attr(elem: etree.Element, *candidates: str) -> str | None:
    """The first present attribute among ``candidates``."""
    for candidate in candidates:
        value = elem.get(candidate)
        if value:
            return value
    return None


def _name_of(elem: etree.Element) -> str:
    """Element name from the ``name`` attribute or a ``Name`` child."""
    return (_attr(elem, "name", "Name") or _descendant_text(elem, "Name")).strip()


def _element_text(elem: etree.Element, block_tags: frozenset[str]) -> list[str]:
    """Plain-text pieces of ``elem`` and its descendants (blocks -> newlines)."""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if local_name(child.tag) in block_tags:
            parts.append("\n")
        parts.extend(_element_text(child, block_tags))
        if child.tail:
            parts.append(child.tail)
    return parts


def _unwrap_text(elem: etree.Element) -> str:
    """Unwrap HTML-ish NVivo document content to flat plain text."""
    text = "".join(_element_text(elem, _BLOCK_TAGS))
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def archive_has_nvivo_marker(archive: zipfile.ZipFile) -> bool:
    """True when the ZIP archive carries an NVivo marker.

    Markers: a ``__nvivo`` archive path (split project bundle) or an XML
    member whose root element is ``NvivoProject`` (namespace prefixes
    allowed). Probes only the first few kilobytes of up to
    ``_MAX_XML_MEMBERS_PROBED`` XML members so detection stays cheap on
    large archives.
    """
    names = archive.namelist()
    if any(_NVIVO_BUNDLE_FRAGMENT in name.lower() for name in names):
        return True
    xml_members = [name for name in names if name.lower().endswith(".xml")]
    for member in xml_members[:_MAX_XML_MEMBERS_PROBED]:
        try:
            with archive.open(member) as fh:
                head = fh.read(4096)
        except (KeyError, OSError):
            continue
        if _NVIVO_ROOT_RE.search(head):
            return True
    return False


# ----------------------------------------------------------------------
# XML extraction
# ----------------------------------------------------------------------

def _collect_xml(
    archive: zipfile.ZipFile,
) -> tuple[list[etree.Element], list[etree.Element], list[etree.Element]]:
    """Documents, nodes and codings from every XML member of the archive.

    Split bundles keep each section in its own XML file; a single
    ``NvivoProject.xml`` holds them all. One unparseable member only loses
    that member's section — the rest of the archive still imports.
    """
    documents: list[etree.Element] = []
    nodes: list[etree.Element] = []
    codings: list[etree.Element] = []
    for member in archive.namelist():
        if not member.lower().endswith(".xml"):
            continue
        try:
            with archive.open(member) as fh:
                root = etree.parse(fh).getroot()
        except (etree.ParseError, OSError, zipfile.BadZipFile):
            continue
        for elem in root.iter():
            if elem is root:
                continue
            name = local_name(elem.tag)
            if name == "Document" and _attr(elem, "name", "guid", "id", "ID"):
                documents.append(elem)
            elif name == "Node" and _attr(elem, "name", "guid", "id", "ID"):
                nodes.append(elem)
            elif name == "Coding" and _attr(elem, "source", "node"):
                codings.append(elem)
    return documents, nodes, codings


@dataclass
class _NodeRec:
    """One NVivo node: a code, or a folder (category) when it has children."""

    key: int
    guid: str | None
    name: str
    memo: str
    parent: int | None = None
    children: list[int] = field(default_factory=list)


def _build_node_tree(node_elems: list[etree.Element]) -> list[_NodeRec]:
    """Flatten nested ``Node`` elements into records with parent/child keys.

    Anonymous wrapper elements (the top-level ``Nodes`` container) are
    skipped; their children become roots. Repeated declarations of the same
    GUID across split files keep the first occurrence.
    """
    recs: list[_NodeRec] = []
    by_key: dict[int, _NodeRec] = {}
    by_guid: dict[str, _NodeRec] = {}
    counter = 0

    def visit(elem: etree.Element, parent: int | None) -> int | None:
        nonlocal counter
        name = _name_of(elem)
        if not name:
            for child in _children(elem, "Node"):
                visit(child, parent)
            return None
        guid = _attr(elem, "guid", "id", "ID")
        if guid and guid in by_guid:
            return by_guid[guid].key
        counter += 1
        rec = _NodeRec(
            key=counter,
            guid=guid,
            name=name,
            memo=_descendant_text(elem, "Description"),
            parent=parent,
        )
        recs.append(rec)
        by_key[counter] = rec
        if guid:
            by_guid[guid] = rec
        for child in _children(elem, "Node"):
            child_key = visit(child, rec.key)
            if child_key is not None and child_key not in rec.children:
                rec.children.append(child_key)
        return rec.key

    for elem in node_elems:
        visit(elem, None)
    return recs


def _parse_positions(elem: etree.Element) -> list[tuple[int, int]]:
    """Character offsets of a coding: ``Position``/``Start``-``End`` children.

    ``Begin`` is accepted as an alias for ``Start``; ``start``/``end``
    attributes on the ``Coding`` element are the fallback. Returns an empty
    list when nothing parses (the caller counts the coding as skipped).
    """
    positions: list[tuple[int, int]] = []
    for position in _children(elem, "Position"):
        start_text = _descendant_text(position, "Start") or _descendant_text(position, "Begin")
        end_text = _descendant_text(position, "End")
        if not start_text or not end_text:
            continue
        try:
            positions.append((int(float(start_text)), int(float(end_text))))
        except ValueError:
            continue
    if not positions:
        start = _attr(elem, "start", "Start", "begin")
        end = _attr(elem, "end", "End")
        if start and end:
            with suppress(ValueError):
                positions.append((int(float(start)), int(float(end))))
    return positions


def _clamp_offsets(pos0: int, pos1: int, length: int) -> tuple[int, int]:
    """Clamp an offset pair into ``[0, length]``."""
    return max(0, min(pos0, length)), max(0, min(pos1, length))


# ----------------------------------------------------------------------
# Import
# ----------------------------------------------------------------------

async def import_nvivo(session_factory: async_sessionmaker, nvpx_path: str, codername: str) -> dict:
    """Import an NVivo ``.nvpx`` project ZIP into the open project.

    Documents with text content become text sources, named nodes become
    codes (node folders become categories, built from the node tree) and
    codings with parseable character positions become text codings. Every
    opaque section is skipped and counted — the import only fails when the
    archive carries no NVivo marker at all. Rows whose name already exists
    in the project are skipped (deduplication like the other importers).

    Returns ``{"ok": True, "message": ..., "sources": n, "categories": n,
    "codes": n, "codings": n, "skipped_codings": n}``. Raises
    ``ValueError`` when the file is not an NVivo project.
    """
    counts: dict[str, int] = {
        "sources": 0,
        "categories": 0,
        "codes": 0,
        "codings": 0,
        "skipped_codings": 0,
    }
    try:
        with zipfile.ZipFile(nvpx_path) as archive:
            if not archive_has_nvivo_marker(archive):
                raise ValueError(
                    "not an NVivo project — expected a .nvpx ZIP with an "
                    "NvivoProject.xml (or __nvivo bundle) inside"
                )
            documents, node_elems, coding_elems = _collect_xml(archive)
    except zipfile.BadZipFile as err:
        raise ValueError("not a valid zip archive") from err

    node_recs = _build_node_tree(node_elems)
    coded_guids = {
        guid
        for elem in coding_elems
        if (guid := _attr(elem, "node", "nodeID", "nodeGuid"))
    }

    async with session_factory() as session:
        source_repo = SourceRepository(session)
        code_repo = CodeRepository(session)
        coding_repo = CodingRepository(session)

        async def existing_names(table) -> set[str]:
            rows = await session.execute(select(table.c.name))
            return {row[0] for row in rows if row[0] is not None}

        # -- documents -> text sources -----------------------------------
        source_guid_map: dict[str, int] = {}
        fulltext_by_fid: dict[int, str] = {}
        existing_sources = await existing_names(tables.source)
        for elem in documents:
            name = _name_of(elem)
            doc_type = (_attr(elem, "type") or "").lower()
            if not name or name in existing_sources:
                continue
            if doc_type in _NON_TEXT_DOC_TYPES:
                continue
            content_elem = next(
                (
                    node
                    for node in elem.iter()
                    if node is not elem and local_name(node.tag) == "Content"
                ),
                None,
            )
            fulltext = _unwrap_text(content_elem) if content_elem is not None else ""
            source = await source_repo.add_source(
                name=name,
                mediapath=None,
                fulltext=fulltext or None,
                memo=_descendant_text(elem, "Description"),
                owner=codername,
            )
            guid = _attr(elem, "guid", "id", "ID")
            if guid:
                source_guid_map[guid] = source.id
            fulltext_by_fid[source.id] = fulltext
            existing_sources.add(name)
            counts["sources"] += 1

        # -- nodes -> categories (folders) then codes ---------------------
        catid_by_key: dict[int, int | None] = {}
        existing_cats = await existing_names(tables.code_cat)

        async def import_category(rec: _NodeRec, supercatid: int | None) -> None:
            catid = None
            if rec.children:
                if rec.name and rec.name not in existing_cats:
                    category = await code_repo.add_category(
                        name=rec.name, owner=codername, supercatid=supercatid
                    )
                    if category is not None:
                        catid = category.catid
                        existing_cats.add(rec.name)
                        counts["categories"] += 1
                elif rec.name:
                    row = (
                        await session.execute(
                            select(tables.code_cat.c.catid).where(
                                tables.code_cat.c.name == rec.name
                            )
                        )
                    ).first()
                    catid = row[0] if row else None
            catid_by_key[rec.key] = catid
            for child_key in rec.children:
                await import_category(next(r for r in node_recs if r.key == child_key), catid)

        child_keys = {child_key for rec in node_recs for child_key in rec.children}
        for rec in node_recs:
            if rec.children and rec.key not in child_keys:
                await import_category(rec, None)

        existing_codes = await existing_names(tables.code_name)
        code_guid_map: dict[str, int] = {}
        for rec in node_recs:
            if not rec.name or rec.name in existing_codes:
                continue
            if rec.children and (rec.guid is None or rec.guid not in coded_guids):
                continue  # plain folder — already imported as a category
            code = await code_repo.add_code(
                name=rec.name,
                owner=codername,
                catid=catid_by_key.get(rec.parent) if rec.parent is not None else None,
                memo=rec.memo,
            )
            if code is not None:
                if rec.guid:
                    code_guid_map[rec.guid] = code.cid
                existing_codes.add(rec.name)
                counts["codes"] += 1

        # -- codings -> text codings ---------------------------------------
        for elem in coding_elems:
            source_guid = _attr(elem, "source", "sourceID", "sourceGuid")
            node_guid = _attr(elem, "node", "nodeID", "nodeGuid")
            if not source_guid or not node_guid:
                counts["skipped_codings"] += 1
                continue
            fid = source_guid_map.get(source_guid)
            cid = code_guid_map.get(node_guid)
            if fid is None or cid is None:
                counts["skipped_codings"] += 1
                continue
            text = fulltext_by_fid.get(fid, "")
            positions = _parse_positions(elem)
            if not positions:
                counts["skipped_codings"] += 1
                continue
            for pos0, pos1 in positions:
                pos0, pos1 = _clamp_offsets(pos0, pos1, len(text))
                if pos1 <= pos0:
                    counts["skipped_codings"] += 1
                    continue
                try:
                    await coding_repo.add_text_coding(
                        cid=cid,
                        fid=fid,
                        seltext=text[pos0:pos1],
                        pos0=pos0,
                        pos1=pos1,
                        owner=codername,
                    )
                    counts["codings"] += 1
                except IntegrityError:
                    counts["skipped_codings"] += 1
                    await session.rollback()

    message = (
        f"NVivo import complete: {counts['sources']} sources, "
        f"{counts['categories']} categories, {counts['codes']} codes, "
        f"{counts['codings']} codings, {counts['skipped_codings']} codings skipped"
    )
    return {"ok": True, "message": message, **counts}
