"""Detect the kind of an interchange upload file."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from qualcoder_api.interchange.importers.base import TRANSANA_TABLES


def detect_import_kind(path: str) -> str:
    """Sniff an interchange upload and return the import kind.

    Returns one of ``"refi"``, ``"rqda"``, ``"taguette"``, ``"transana"``,
    ``"ris"``, ``"survey"``, ``"codebook"``, ``"xlsx"``, ``"sav"``,
    ``"merge"``. Raises ``ValueError`` when the file is not a supported
    interchange format.
    """
    import zipfile

    name = Path(path).name.lower()
    with open(path, "rb") as fh:
        head = fh.read(4096)

    # Zip archive → an xlsx workbook or a zipped .qda project (merge).
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if any(entry.startswith("xl/") for entry in names):
                    return "xlsx"
                if any(entry.split("/")[-1] == "data.qda" for entry in names):
                    return "merge"
        except zipfile.BadZipFile as err:
            raise ValueError("not a valid zip archive") from err
        raise ValueError(
            "zip archive without xl/ entries or data.qda — expected an xlsx "
            "workbook or a zipped .qda project"
        )

    # SPSS .sav (``$FL2``/``$FL3``/``$FL32`` at offset 0, ``$FL`` at offset 4
    # in the old compressed variants).
    if head.startswith(b"$FL") or head[4:7] == b"$FL":
        return "sav"

    # SQLite database → RQDA (QualCoder v3), Taguette or Transana.
    if head.startswith(b"SQLite format 3\x00"):
        conn = sqlite3.connect(path)
        try:
            tables_present = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        except sqlite3.Error as err:
            raise ValueError(f"invalid database file: {err}") from err
        finally:
            # Close explicitly: an exception below (unrecognized database)
            # would otherwise keep the connection referenced by the
            # traceback until GC, locking the temp file on Windows.
            conn.close()
        if {"documents", "tags", "highlights"} <= tables_present:
            return "taguette"
        if tables_present & {"source", "file", "codecat", "freecode"}:
            return "rqda"
        if {name.lower() for name in tables_present} & TRANSANA_TABLES:
            return "transana"
        raise ValueError("unrecognized database (expected RQDA, Taguette or Transana)")

    # XML document → REFI-QDA.
    if head.lstrip().startswith(b"<?xml") or b"<project" in head[:1024]:
        return "refi"

    text = head.decode("utf-8", errors="replace")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines and (lines[0].startswith("TY") or any(ln.startswith("TY  -") for ln in lines[:10])):
        return "ris"

    # Codebook lines are ``category>>subcategory>>code`` (txt or csv).
    if ">>" in text:
        return "codebook"

    if name.endswith((".txt", ".text")):
        return "codebook"

    if name.endswith(".csv") or "," in text or ";" in text:
        return "survey"

    raise ValueError(
        "unrecognized file type — supported: .qdp/.qdc (REFI-QDA), .rqda, "
        "Taguette (.sqlite3), Transana (.tprd), .ris, survey .csv, "
        "Excel .xlsx, SPSS .sav, codebook .txt/.csv, zipped .qda projects "
        "and Zotero"
    )
