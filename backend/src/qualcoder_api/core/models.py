"""Pydantic v2 domain models for QualCoder v4.

Each model mirrors a row of the v14 SQLite schema. Models are frozen so
they can be shared across API layers and caches without accidental mutation.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from qualcoder_api.core.enums import MediaType


class Project(BaseModel):
    """Top-level project metadata (``project`` table row)."""

    model_config = ConfigDict(frozen=True)

    databaseversion: str = "v14"
    date: str = ""
    memo: str = ""
    about: str = ""
    codername: str = "default"
    bookmarkfile: int | None = None
    bookmarkpos: int | None = None
    recently_used_codes: str = ""
    avbookmarkfile: int | None = None
    avbookmarkmsec: int | None = None
    avbookmarktextpos: int | None = None


class Source(BaseModel):
    """A source file (text, PDF, image, audio, video) in the project."""

    model_config = ConfigDict(frozen=True)

    id: int = 0
    name: str = ""
    fulltext: str | None = None
    mediapath: str | None = None
    memo: str = ""
    memo_type: str = ""
    owner: str = ""
    date: str = ""
    av_text_id: int | None = None
    risid: int | None = None

    # mypy cannot type-check decorators stacked above @property, but pydantic
    # requires @computed_field to be the outermost decorator here.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def media_type(self) -> MediaType:
        """Media type derived from the mediapath prefix (never stored)."""
        return MediaType.from_mediapath(self.mediapath)


class Code(BaseModel):
    """A single code in the codebook (``code_name`` row)."""

    model_config = ConfigDict(frozen=True)

    cid: int = 0
    name: str = ""
    memo: str = ""
    memo_type: str = ""
    catid: int | None = None
    owner: str = ""
    date: str = ""
    color: str = "#ffffff"
    supercid: int | None = None


class Category(BaseModel):
    """A hierarchical category grouping codes (``code_cat`` row)."""

    model_config = ConfigDict(frozen=True)

    catid: int = 0
    name: str = ""
    owner: str = ""
    date: str = ""
    memo: str = ""
    supercatid: int | None = None


class Coding(BaseModel):
    """A text-coded segment (``code_text`` row)."""

    model_config = ConfigDict(frozen=True)

    ctid: int = 0
    cid: int = 0
    fid: int = 0
    seltext: str = ""
    pos0: int = 0
    pos1: int = 0
    owner: str = ""
    date: str = ""
    memo: str = ""
    avid: int | None = None
    important: int = 0
    weight: int = 0


class ImageCoding(BaseModel):
    """A rectangular coded region on an image (``code_image`` row)."""

    model_config = ConfigDict(frozen=True)

    imid: int = 0
    id: int = 0  # source id
    x1: int = 0
    y1: int = 0
    width: int = 0
    height: int = 0
    cid: int = 0
    memo: str = ""
    date: str = ""
    owner: str = ""
    important: int = 0
    pdf_page: int | None = None
    weight: int = 0


class AVCoding(BaseModel):
    """A time-range coded segment in audio/video (``code_av`` row)."""

    model_config = ConfigDict(frozen=True)

    avid: int = 0
    id: int = 0  # source id
    pos0: int = 0
    pos1: int = 0
    cid: int = 0
    memo: str = ""
    date: str = ""
    owner: str = ""
    important: int = 0
    weight: int = 0


class Case(BaseModel):
    """A qualitative case entity (``cases`` row)."""

    model_config = ConfigDict(frozen=True)

    caseid: int = 0
    name: str = ""
    memo: str = ""
    owner: str = ""
    date: str = ""


class CaseText(BaseModel):
    """Link between a case and a file span (``case_text`` row)."""

    model_config = ConfigDict(frozen=True)

    id: int = 0
    caseid: int = 0
    fid: int = 0
    pos0: int = 0
    pos1: int = 0
    owner: str = ""
    date: str = ""
    memo: str = ""


class Attribute(BaseModel):
    """An attribute value assigned to a file or case (``attribute`` row)."""

    model_config = ConfigDict(frozen=True)

    attrid: int = 0
    name: str = ""
    attr_type: str = ""
    value: str = ""
    id: int = 0  # source or case id
    date: str = ""
    owner: str = ""


class AttributeType(BaseModel):
    """Definition of an attribute type (``attribute_type`` row)."""

    model_config = ConfigDict(frozen=True)

    name: str = ""
    date: str = ""
    owner: str = ""
    memo: str = ""
    case_or_file: str = "case"
    value_type: str = "text"
    value_labels: dict[str, str] = {}

    @field_validator("case_or_file")
    @classmethod
    def _scope(cls, v: str) -> str:
        if v not in ("case", "file"):
            raise ValueError("case_or_file must be 'case' or 'file'")
        return v

    @field_validator("value_type")
    @classmethod
    def _value_type(cls, v: str) -> str:
        if v not in ("text", "number", "date", "boolean"):
            raise ValueError("value_type must be text/number/date/boolean")
        return v

    @field_validator("value_labels", mode="before")
    @classmethod
    def _value_labels(cls, v: object) -> object:
        """Accept a JSON-encoded string (persisted column) or a dict."""
        if v is None or v == "":
            return {}
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return {}
        return v


class Journal(BaseModel):
    """A journal entry (``journal`` row)."""

    model_config = ConfigDict(frozen=True)

    jid: int = 0
    name: str = ""
    jentry: str = ""
    date: str = ""
    owner: str = ""


class Annotation(BaseModel):
    """A text annotation on a source file (``annotation`` row)."""

    model_config = ConfigDict(frozen=True)

    anid: int = 0
    fid: int = 0
    pos0: int = 0
    pos1: int = 0
    memo: str = ""
    owner: str = ""
    date: str = ""
