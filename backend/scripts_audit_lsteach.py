"""One-shot: run the REAL /codes tree endpoint logic over LSTeach."""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

SRC = Path(r"D:\Downloads\LSTeach2.0_BKUP_20260714_21.qda")


async def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="qc-lst-api-"))
    target = work / "LSTeach.qda"
    shutil.copytree(SRC, target)
    for junk in ("data.qda-wal", "data.qda-shm", "project_in_use.lock"):
        (target / junk).unlink(missing_ok=True)

    from fastapi import HTTPException

    from qualcoder_api.api.v1.codes import code_tree
    from qualcoder_api.persistence.repo.code_repo import CodeRepository
    from qualcoder_api.services.project_service import ProjectService

    svc = ProjectService()
    res = await svc.open_project(str(target), codername="auditor")
    assert res.ok, res.error

    async with svc.session_factory() as db:
        try:
            tree = await code_tree(db)
        except HTTPException as err:
            print("FAIL code_tree:", err.status_code, err.detail)
            return 1
        kinds = {}
        max_sub_depth = 0
        for item in tree:
            kinds[item.kind] = kinds.get(item.kind, 0) + 1
        # sub-code chains must terminate within the depth cap
        by_id = {(i.kind, i.id): i for i in tree}
        for i in tree:
            if i.kind != "code" or not i.subcode:
                continue
            cur, seen, d = i, {("code", i.id)}, 0
            while True:
                pid = cur.parent_id if cur.subcode else None
                if pid is None:
                    break
                key = ("code", pid)
                if key not in by_id or key in seen:
                    break
                seen.add(key)
                cur = by_id[key]
                d += 1
                if d > 64:
                    break
            max_sub_depth = max(max_sub_depth, d)
    await svc.close_project()
    print(f"API code_tree OK: {kinds}, max sub-code chain={max_sub_depth}")
    shutil.rmtree(work.parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
