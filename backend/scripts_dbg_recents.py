"""One-shot: verify create_project persists recent_projects."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from qualcoder_api.services.project_service import ProjectService  # noqa: E402
from qualcoder_api.services import user_settings  # noqa: E402


async def main():
    tmp = Path(tempfile.mkdtemp(prefix="qc-recents-"))
    proj = tmp / "Probe.qda"
    svc = ProjectService()
    ok = await svc.create_project(str(proj), codername="probe")
    print("created:", ok)
    print("recents:", user_settings.get_recent_projects())
    sf = Path(user_settings.SETTINGS_FILE)
    print("settings exists:", sf.exists(), "->", sf)
    await svc.close_project()

import tempfile  # noqa: E402

asyncio.run(main())
