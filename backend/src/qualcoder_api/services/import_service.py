"""File import pipeline — copy into the project folder, extract text,
register the source row, add attribute placeholders and transcription
links. Faithful port of the legacy ``import_files`` workflow.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import zipfile
from html.entities import name2codepoint
from html.parser import HTMLParser
from pathlib import Path

from charset_normalizer import from_bytes
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qualcoder_api.core.enums import (
    AUDIO_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MediaType,
)
from qualcoder_api.core.models import Source
from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables

logger = logging.getLogger(__name__)


def detect_media_type(filename: str) -> MediaType:
    """Classify a file by extension (legacy import classification)."""
    ext = Path(filename).suffix.lower()
    if ext in DOCUMENT_EXTENSIONS:
        return MediaType.PDF if ext == ".pdf" else MediaType.TEXT
    if ext in IMAGE_EXTENSIONS:
        return MediaType.IMAGE
    if ext in AUDIO_EXTENSIONS:
        return MediaType.AUDIO
    if ext in VIDEO_EXTENSIONS:
        return MediaType.VIDEO
    return MediaType.TEXT  # unknown -> try as text


def _folder_for(mtype: MediaType) -> str:
    return {
        MediaType.TEXT: "documents",
        MediaType.PDF: "documents",
        MediaType.IMAGE: "images",
        MediaType.AUDIO: "audio",
        MediaType.VIDEO: "video",
    }[mtype]


def _prefix_for(mtype: MediaType) -> str:
    return {
        MediaType.TEXT: "/docs/",
        MediaType.PDF: "/docs/",
        MediaType.IMAGE: "/images/",
        MediaType.AUDIO: "/audio/",
        MediaType.VIDEO: "/video/",
    }[mtype]


# ----------------------------------------------------------------------
# Text extraction (ported from manage_files.py / interchange/html_parser.py)
# ----------------------------------------------------------------------

def decode_text_with_best_encoding(raw: bytes) -> str:
    """Decode text bytes using robust encoding detection and fallbacks."""
    if not raw:
        return ""
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    best_match = from_bytes(raw).best()
    if best_match is not None:
        return str(best_match)
    for encoding in ("cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="backslashreplace")


def convert_odt_to_text(path: str) -> str:
    """Rough ODT-to-text conversion with headings, list items, tables."""
    odt_file = zipfile.ZipFile(path)
    data = str(odt_file.read("content.xml"))
    data = str(bytes([ord(char) for char in data.encode("utf_8").decode("unicode_escape")]), "utf_8")
    data_start = data.find("</text:sequence-decls>")
    data_end = data.find("</office:text>")
    if data_start == -1 or data_end == -1:
        logger.warning("ODT IMPORT ERROR")
        return ""
    data = data[data_start + 22 : data_end]
    for token in (
        "</text:index-title-template>",
        "</text:index-entry-span>",
        "</text:table-of-content-entry-template>",
        "</text:index-title>",
        "</text:index-body>",
        "</text:table-of-contents>",
        "</text:table-of-content-source>",
    ):
        data = data.replace(token, "")
    data = data.replace("<text:h", "\n<text:h")
    data = data.replace("</text:h>", "\n\n")
    data = data.replace("</text:list-item>", "\n")
    data = data.replace("</text:span>", "")
    data = data.replace("</text:p>", "\n")
    data = data.replace("</text:a>", " ")
    data = data.replace("</text:list>", "")
    data = data.replace("</text:sequence>", "")
    data = data.replace("<text:list-item>", "")
    data = data.replace("<table:table table:name=", "\n=== TABLE ===\n<table:table table:name=")
    data = data.replace("</table:table>", "=== END TABLE ===\n")
    data = data.replace("</table:table-cell>", "\n")
    data = data.replace("</table:table-row>", "")
    data = data.replace("<draw:image", "\n=== IMG ===<draw:image")
    data = data.replace("</draw:frame>", "\n")
    text_ = ""
    tagged = False
    for i in range(len(data)):
        if data[i : i + 6] == "<text:" or data[i : i + 7] == "<table:" or data[i : i + 6] == "<draw:":
            tagged = True
        if not tagged:
            text_ += data[i]
        if data[i] == ">":
            tagged = False
    for entity, char in (
        ("&apos;", "'"), ("&quot;", '"'), ("&gt;", ">"), ("&lt;", "<"), ("&amp;", "&"),
    ):
        text_ = text_.replace(entity, char)
    return text_


class _HTMLToText(HTMLParser):
    """Convert HTML to text (stdlib-only port)."""

    def __init__(self) -> None:
        super().__init__()
        self._buf: list[str] = []
        self.hide_output = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag in ("p", "br", "li", "h1", "h2", "h3") and not self.hide_output:
            self._buf.append("\n")
        elif tag in ("script", "style"):
            self.hide_output = True

    def handle_startendtag(self, tag, attrs) -> None:
        if tag == "br":
            self._buf.append("\n")

    def handle_endtag(self, tag) -> None:
        if tag == "p":
            self._buf.append("\n")
        elif tag in ("script", "style"):
            self.hide_output = False

    def handle_data(self, data) -> None:
        if not self.hide_output:
            self._buf.append(data)

    def handle_entityref(self, name) -> None:
        if name in name2codepoint and not self.hide_output:
            self._buf.append(chr(name2codepoint[name]))

    def handle_charref(self, name) -> None:
        if not self.hide_output:
            n = int(name[1:], 16) if name.startswith("x") else int(name)
            self._buf.append(chr(n))

    def get_text(self) -> str:
        import re

        return re.sub(r" +", " ", "".join(self._buf))


def html_to_text(html: str) -> str:
    parser = _HTMLToText()
    try:
        parser.feed(html)
        parser.close()
    except Exception as err:
        logger.debug("html_to_text error: %s", err)
    return parser.get_text()


def tex_to_plain_text(text: str) -> str:
    """Conservative LaTeX → plain text (pylatexenc-free port).

    Removes comments, ``\\section``-style headings and ``\\textfoo{...}``
    commands, keeps the inner text of braces, and unescapes common LaTeX
    accented characters. Not a full TeX parser — good enough for coding
    (mirrors the upstream ``latex_import`` intent).
    """
    import re

    text = re.sub(r"(?<!\\)%.*$", "", text, flags=re.MULTILINE)
    # Headings become plain lines with the heading text.
    text = re.sub(
        r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)(\*)?\{(.+?)\}",
        r"\3\n",
        text,
        flags=re.DOTALL,
    )
    # Remove \label/\ref/\cite/\includegraphics arguments.
    text = re.sub(r"\\(label|ref|pageref|cite|citep|citet|includegraphics)(\[[^\]]*\])?\{[^}]*\}", "", text)
    # \emph, \textbf, \textit, \texttt, \url, \href etc. keep inner text.
    text = re.sub(
        r"\\(emph|textbf|textit|texttt|textrm|textsc|textsf|underline|mbox|ensuremath|mathrm|mathbf|mathit|url|href)\{([^}]*)\}",
        r"\2",
        text,
    )
    # Simple commands without args.
    text = re.sub(r"\\([a-zA-Z]+)\*?", "", text)
    # Escaped characters.
    text = (
        text.replace("\\&", "&")
        .replace("\\%", "%")
        .replace("\\#", "#")
        .replace("\\_", "_")
        .replace("\\{", "{")
        .replace("\\}", "}")
        .replace("\\$", "$")
        .replace("\\textbackslash", "\\")
    )
    # Accented letters (common subset).
    text = (
        text.replace("\\'a", "á").replace("\\'e", "é").replace("\\'i", "í")
        .replace("\\'o", "ó").replace("\\'u", "ú")
        .replace('\\"a', "ä").replace('\\"e', "ë").replace('\\"i', "ï")
        .replace('\\"o', "ö").replace('\\"u', "ü")
        .replace("\\~n", "ñ").replace("\\`a", "à").replace("\\`e", "è")
        .replace("\\`o", "ò").replace("\\`u", "ù").replace("\\^a", "â")
        .replace("\\^e", "ê").replace("\\^i", "î").replace("\\^o", "ô")
        .replace("\\^u", "û").replace("\\c{c}", "ç").replace("\\ss", "ß")
    )
    # Blank lines between paragraphs.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_text(path: str) -> str:
    """Extract plain text from a document file (legacy conversion order)."""
    ext = Path(path).suffix.lower()
    text_ = ""
    if ext == ".odt":
        text_ = convert_odt_to_text(path)
        text_ = text_.replace("\n", "\n\n")
    elif ext == ".docx":
        import docx2txt

        text_ = "\n\n".join(docx2txt.process(path).splitlines())
    elif ext == ".tex":
        raw = Path(path).read_bytes()
        text_ = tex_to_plain_text(decode_text_with_best_encoding(raw))
    elif ext == ".rtf":
        from striprtf.striprtf import rtf_to_text

        with open(path, encoding="latin-1") as sourcefile:
            try:
                text_ = rtf_to_text(sourcefile.read())
            except Exception as err:
                logger.debug("rtf_to_text error: %s", err)
    elif ext == ".epub":
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(path)
        for doc in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            try:
                string = doc.get_body_content().decode("utf-8")
                text_ += html_to_text(string) + "\n\n"
            except (TypeError, AttributeError) as err:
                logger.debug("ebooklib error: %s", err)
    elif ext in (".html", ".htm"):
        with open(path, encoding="utf-8", errors="surrogateescape") as sourcefile:
            text_ = html_to_text(sourcefile.read())
    elif ext == ".pdf":
        import fitz

        raw = Path(path).read_bytes()
        with fitz.open(stream=raw, filetype="pdf") as doc:
            text_ = "".join(page.get_text() for page in doc)
    if text_ == "":
        with open(path, "rb") as sourcefile:
            text_ = decode_text_with_best_encoding(sourcefile.read())
        if text_ and text_[0] == "\ufeff":
            text_ = text_[1:]
    return text_


class ImportService:
    """Imports files into an open project."""

    def __init__(self, project_path: str, session_factory: async_sessionmaker):
        self.project_path = Path(project_path)
        self.session_factory = session_factory

    def _ensure_folder(self, mtype: MediaType) -> Path:
        folder = _folder_for(mtype)
        path = self.project_path / folder
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _name_exists(self, session: AsyncSession, name: str) -> bool:
        row = await session.execute(
            text("SELECT 1 FROM source WHERE name = :n LIMIT 1"), {"n": name}
        )
        return row.first() is not None

    async def _add_attribute_placeholders(self, session: AsyncSession, entity_id: int, owner: str) -> None:
        """Insert empty attribute values for every file-scope attribute type."""
        from qualcoder_api.persistence.repositories import _capture

        rows = await session.execute(
            select(tables.attribute_type.c.name).where(
                text("caseOrFile = 'file'")
            )
        )
        now = _now()
        for (attr_name,) in rows:
            await session.execute(
                text(
                    "INSERT INTO attribute (name, attr_type, value, id, date, owner) "
                    "VALUES (:n, 'file', '', :id, :d, :o)"
                ),
                {"n": attr_name, "id": entity_id, "d": now, "o": owner},
            )
            row = (
                await session.execute(
                    text(
                        "SELECT * FROM attribute WHERE name = :n AND attr_type = 'file' "
                        "AND id = :id"
                    ),
                    {"n": attr_name, "id": entity_id},
                )
            ).first()
            if row is not None:
                data = dict(dict(row._mapping).items())
                await _capture(
                    session, "attribute", "insert", "attrid", data.get("attrid"), data
                )
        await session.commit()

    async def import_file(
        self, source_path: str, owner: str, link: bool = False, filename: str | None = None
    ) -> Source | None:
        """Import or link one file. Returns the new source (or None on skip).

        ``filename`` overrides the name used in the project (for uploads
        staged under a temporary name).
        """
        from qualcoder_api.persistence.repositories import SourceRepository

        src = Path(source_path)
        filename = filename or src.name
        mtype = detect_media_type(filename)
        mediapath = ""
        fulltext: str | None = None

        async with self.session_factory() as session:
            if await self._name_exists(session, filename):
                logger.warning("Duplicate filename, not imported: %s", filename)
                return None

            if link:
                mediapath = {
                    MediaType.TEXT: "docs:",
                    MediaType.PDF: "docs:",
                    MediaType.IMAGE: "images:",
                    MediaType.AUDIO: "audio:",
                    MediaType.VIDEO: "video:",
                }[mtype] + src.as_posix()
            else:
                dest_folder = self._ensure_folder(mtype)
                dest = dest_folder / filename
                try:
                    shutil.copy2(src, dest)
                except (OSError, PermissionError) as err:
                    logger.warning("Cannot copy file %s: %s", filename, err)
                    return None
                mediapath = _prefix_for(mtype) + filename

            if mtype in (MediaType.TEXT, MediaType.PDF):
                try:
                    fulltext = await asyncio.to_thread(extract_text, str(src))
                except Exception as err:
                    logger.warning("Text extraction failed for %s: %s", filename, err)
                    fulltext = None

            repo = SourceRepository(session)
            source = await repo.add_source(
                name=filename,
                mediapath=mediapath,
                fulltext=fulltext,
                owner=owner,
            )

            if mtype in (MediaType.AUDIO, MediaType.VIDEO):
                # transcription file + av_text_id link + attribute placeholders
                trans = await repo.add_source(
                    name=filename + ".txt",
                    mediapath=None,
                    fulltext="",
                    owner=owner,
                )
                await repo.update_source(source.id, av_text_id=trans.id)
                reloaded = await repo.get_source(source.id)
                if reloaded is None:  # pragma: no cover - row was just updated
                    raise RuntimeError("source row vanished after update")
                source = reloaded
                await self._add_attribute_placeholders(session, trans.id, owner)
            else:
                await self._add_attribute_placeholders(session, source.id, owner)

            return source
