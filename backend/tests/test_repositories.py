"""Repository tests — CRUD over the v14 schema via async sessions."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from qualcoder_api.core.enums import MediaType
from qualcoder_api.core.models import AVCoding, Category, Code, Coding, ImageCoding, Project
from qualcoder_api.persistence.database import (
    create_all_tables,
    create_project_engine,
    create_session_factory,
    dispose_engine,
)
from qualcoder_api.persistence.repositories import (
    CodeRepository,
    CodingRepository,
    ProjectRepository,
    SourceRepository,
)


@pytest.fixture
async def session(tmp_path):
    engine = create_project_engine(tmp_path / "repo.qda")
    await create_all_tables(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        await s.execute(
            text(
                "INSERT INTO project (databaseversion, date, memo, about, bookmarkfile, "
                "bookmarkpos, codername, recently_used_codes) "
                "VALUES ('v14', '2026-01-01', '', 'QualCoder 4.0-test', 0, 0, 'default', '')"
            )
        )
        await s.commit()
        yield s
    await dispose_engine(engine)


async def test_project_header_defaults(session):
    project = await ProjectRepository(session).get_header()
    assert project is not None
    assert isinstance(project, Project)
    assert project.databaseversion == "v14"
    assert project.codername == "default"


async def test_project_summary_counts(session):
    repo = ProjectRepository(session)
    sr = SourceRepository(session)
    await sr.add_source(name="a.txt", mediapath="/docs/a.txt", owner="x")
    await sr.add_source(name="b.pdf", mediapath="/docs/b.pdf", owner="x")
    cr = CodeRepository(session)
    await cr.add_code(name="code1", owner="x")
    await cr.add_category(name="cat1", owner="x")
    summary = await repo.get_summary()
    assert summary["files_count"] == 2
    assert summary["codes_count"] == 1
    assert summary["code_categories_count"] == 1
    assert summary["bookmark_filename"] is None


async def test_project_update_memo(session):
    repo = ProjectRepository(session)
    await repo.update_memo("project notes")
    assert (await repo.get_header()).memo == "project notes"


async def test_coder_names_updated_from_owners(session):
    repo = ProjectRepository(session)
    sr = SourceRepository(session)
    await sr.add_source(name="a.txt", mediapath="/docs/a.txt", owner="alice")
    await repo.update_coder_names("tester")
    cur = await session.execute(text("SELECT name FROM coder_names ORDER BY name"))
    names = [r[0] for r in cur.fetchall()]
    assert "alice" in names
    assert "tester" in names


async def test_source_media_type_derivation(session):
    sr = SourceRepository(session)
    pdf = await sr.add_source(name="doc.pdf", mediapath="/docs/doc.pdf")
    img = await sr.add_source(name="pic.png", mediapath="images:pic.png")
    aud = await sr.add_source(name="snd.mp3", mediapath="audio:snd.mp3")
    vid = await sr.add_source(name="mov.mp4", mediapath="video:mov.mp4")
    txt = await sr.add_source(name="plain.txt", mediapath=None)
    # legacy semantics: /docs/ -> text (PDF decided by extension elsewhere)
    assert pdf.media_type == MediaType.TEXT
    assert img.media_type == MediaType.IMAGE
    assert aud.media_type == MediaType.AUDIO
    assert vid.media_type == MediaType.VIDEO
    assert txt.media_type == MediaType.TEXT


async def test_source_crud_roundtrip(session):
    sr = SourceRepository(session)
    created = await sr.add_source(name="doc.txt", mediapath="/docs/doc.txt", fulltext="abc", owner="alice")
    assert created.id > 0
    fetched = await sr.get_source(created.id)
    assert fetched == created
    updated = await sr.update_source(created.id, memo="updated", owner="bob")
    assert updated.memo == "updated"
    assert updated.owner == "bob"
    listed = await sr.list_sources()
    assert len(listed) == 1
    await sr.delete_source(created.id)
    assert await sr.get_source(created.id) is None


async def test_source_delete_cascades_codings(session):
    sr = SourceRepository(session)
    src = await sr.add_source(name="doc.txt", mediapath="/docs/doc.txt", fulltext="hello world", owner="alice")
    cr = CodeRepository(session)
    code = await cr.add_code(name="c1", owner="alice")
    coding_repo = CodingRepository(session)
    await coding_repo.add_text_coding(
        cid=code.cid, fid=src.id, seltext="hello", pos0=0, pos1=5, owner="alice"
    )
    await sr.delete_source(src.id)
    assert await coding_repo.list_text_codings_for_file(src.id) == []


async def test_source_delete_cascades_transcript_companion(session):
    """Deleting a media source deletes its transcript companion (av_text_id)
    and the companion's codings; the reverse (companion without a link) does
    not recurse back."""
    sr = SourceRepository(session)
    media = await sr.add_source(name="clip.mp4", mediapath="video:clip.mp4")
    companion = await sr.add_source(name="clip.mp4.txt", mediapath=None, fulltext="")
    await sr.update_source(media.id, av_text_id=companion.id)

    cr = CodeRepository(session)
    code = await cr.add_code(name="c1", owner="alice")
    coding_repo = CodingRepository(session)
    await coding_repo.add_text_coding(
        cid=code.cid, fid=companion.id, seltext="hello", pos0=0, pos1=5, owner="alice"
    )

    await sr.delete_source(media.id)
    assert await sr.get_source(media.id) is None
    assert await sr.get_source(companion.id) is None
    assert await coding_repo.list_text_codings_for_file(companion.id) == []


async def test_source_delete_companion_without_media(session):
    """Deleting a companion directly (media's av_text_id cleared first) leaves
    the media source intact — no recursion back into the media row."""
    sr = SourceRepository(session)
    media = await sr.add_source(name="clip.mp4", mediapath="video:clip.mp4")
    companion = await sr.add_source(name="clip.mp4.txt", mediapath=None, fulltext="")
    await sr.update_source(media.id, av_text_id=companion.id)
    await sr.update_source(media.id, av_text_id=None)

    await sr.delete_source(companion.id)
    assert await sr.get_source(companion.id) is None
    assert await sr.get_source(media.id) is not None
    assert (await sr.get_source(media.id)).av_text_id is None


async def test_code_and_category_crud(session):
    cr = CodeRepository(session)
    cat = await cr.add_category(name="Theme", owner="alice")
    assert isinstance(cat, Category)
    code = await cr.add_code(name="sub", owner="alice", catid=cat.catid, color="#FF0000")
    assert isinstance(code, Code)
    assert code.catid == cat.catid
    assert code.color == "#FF0000"
    renamed = await cr.rename_code(code.cid, "sub2")
    assert renamed.name == "sub2"
    codes = await cr.list_codes()
    assert [c.name for c in codes] == ["sub2"]
    await cr.delete_code(code.cid)
    assert await cr.get_code(code.cid) is None


async def test_delete_category_reassigns_codes(session):
    cr = CodeRepository(session)
    cat = await cr.add_category(name="Theme", owner="alice")
    other = await cr.add_category(name="Other", owner="alice")
    code = await cr.add_code(name="sub", owner="alice", catid=cat.catid)
    await cr.delete_category(cat.catid)
    refetched = await cr.get_code(code.cid)
    assert refetched.catid is None
    assert await cr.get_code(code.cid) is not None
    await cr.delete_category(other.catid)


async def test_merge_codes_reassigns_codings(session):
    sr = SourceRepository(session)
    src = await sr.add_source(name="doc.txt", mediapath="/docs/doc.txt", fulltext="aaa bbb ccc", owner="a")
    cr = CodeRepository(session)
    c1 = await cr.add_code(name="one", owner="a")
    c2 = await cr.add_code(name="two", owner="a")
    c3 = await cr.add_code(name="three", owner="a")
    coding_repo = CodingRepository(session)
    await coding_repo.add_text_coding(cid=c1.cid, fid=src.id, seltext="aaa", pos0=0, pos1=3, owner="a")
    await coding_repo.add_text_coding(cid=c2.cid, fid=src.id, seltext="bbb", pos0=4, pos1=7, owner="a")
    await coding_repo.add_text_coding(cid=c3.cid, fid=src.id, seltext="ccc", pos0=8, pos1=11, owner="a")
    await cr.merge_codes(c1.cid, c2.cid)
    codings = await coding_repo.list_text_codings_for_code(c2.cid)
    assert len(codings) == 2
    assert await cr.get_code(c1.cid) is None
    # duplicate-position conflict: merging c3 into c2 keeps only the target's row
    await coding_repo.add_text_coding(cid=c3.cid, fid=src.id, seltext="aaa", pos0=0, pos1=3, owner="a")
    await cr.merge_codes(c3.cid, c2.cid)
    after = await coding_repo.list_text_codings_for_code(c2.cid)
    assert len(after) == 3
    assert sorted(c.seltext for c in after) == ["aaa", "bbb", "ccc"]
    assert len([c for c in after if c.pos0 == 0]) == 1


async def test_merge_category_moves_codes_and_children(session):
    cr = CodeRepository(session)
    parent = await cr.add_category(name="Parent", owner="a")
    child = await cr.add_category(name="Child", owner="a", supercatid=parent.catid)
    target = await cr.add_category(name="Target", owner="a")
    code = await cr.add_code(name="c", owner="a", catid=child.catid)
    await cr.merge_category(child.catid, target.catid)
    refetched = await cr.get_code(code.cid)
    assert refetched.catid == target.catid
    categories = await cr.list_categories()
    catids = {c.catid for c in categories}
    assert child.catid not in catids
    parent_after = next(c for c in categories if c.catid == parent.catid)
    assert parent_after.supercatid is None


async def test_text_coding_crud(session):
    sr = SourceRepository(session)
    src = await sr.add_source(name="doc.txt", mediapath="/docs/doc.txt", fulltext="hello world", owner="a")
    cr = CodeRepository(session)
    code = await cr.add_code(name="c", owner="a")
    coding_repo = CodingRepository(session)
    coding = await coding_repo.add_text_coding(
        cid=code.cid, fid=src.id, seltext="hello", pos0=0, pos1=5, owner="a", important=1
    )
    assert isinstance(coding, Coding)
    updated = await coding_repo.update_text_coding(coding.ctid, memo="important bit")
    assert updated.memo == "important bit"
    listed = await coding_repo.list_text_codings_for_file(src.id)
    assert len(listed) == 1
    assert listed[0].pos0 == 0
    assert listed[0].pos1 == 5
    await coding_repo.delete_text_coding(coding.ctid)
    assert await coding_repo.list_text_codings_for_file(src.id) == []


async def test_legacy_null_important_is_coerced(session):
    """Regression: legacy rows with important = NULL must not break the
    list endpoints (they 500'd the whole file → 'Failed to fetch' + no
    colored segments in the UI)."""
    from sqlalchemy import text as sql_text

    sr = SourceRepository(session)
    src = await sr.add_source(name="legacy.txt", mediapath="/docs/legacy.txt", fulltext="x", owner="a")
    cr = CodeRepository(session)
    code = await cr.add_code(name="legacy-code", owner="a")
    coding_repo = CodingRepository(session)
    coding = await coding_repo.add_text_coding(
        cid=code.cid, fid=src.id, seltext="x", pos0=0, pos1=1, owner="a"
    )
    # Simulate legacy data: NULL the important column.
    await session.execute(
        sql_text("UPDATE code_text SET important = NULL WHERE ctid = :id"), {"id": coding.ctid}
    )
    await session.commit()

    listed = await coding_repo.list_text_codings_for_file(src.id)
    assert len(listed) == 1
    assert listed[0].important == 0
    assert listed[0].ctid == coding.ctid


async def test_image_coding_crud(session):
    sr = SourceRepository(session)
    src = await sr.add_source(name="pic.png", mediapath="images:pic.png", owner="a")
    cr = CodeRepository(session)
    code = await cr.add_code(name="region", owner="a")
    coding_repo = CodingRepository(session)
    img = await coding_repo.add_image_coding(
        id=src.id, x1=10, y1=20, width=30, height=40, cid=code.cid, owner="a"
    )
    assert isinstance(img, ImageCoding)
    listed = await coding_repo.list_image_codings_for_file(src.id)
    assert len(listed) == 1
    assert listed[0].x1 == 10
    assert listed[0].height == 40
    await coding_repo.delete_image_coding(img.imid)
    assert await coding_repo.list_image_codings_for_file(src.id) == []


async def test_av_coding_crud(session):
    sr = SourceRepository(session)
    src = await sr.add_source(name="talk.mp3", mediapath="audio:talk.mp3", owner="a")
    cr = CodeRepository(session)
    code = await cr.add_code(name="segment", owner="a")
    coding_repo = CodingRepository(session)
    av = await coding_repo.add_av_coding(
        id=src.id, pos0=500, pos1=1500, cid=code.cid, owner="a"
    )
    assert isinstance(av, AVCoding)
    listed = await coding_repo.list_av_codings_for_file(src.id)
    assert len(listed) == 1
    assert listed[0].pos0 == 500
    assert listed[0].pos1 == 1500
    await coding_repo.delete_av_coding(av.avid)
    assert await coding_repo.list_av_codings_for_file(src.id) == []
