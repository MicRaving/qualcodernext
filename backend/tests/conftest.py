"""Shared pytest fixtures for the qualcoder_api backend."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# A real user hotpatch under ~/.qualcoder would otherwise mount its SPA
# catch-all into every test app (see hotpatch.frontend_version) and shadow
# dynamically added routes — tests must never depend on machine state.
os.environ.setdefault("QC_NO_HOTPATCH", "1")


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A fresh directory where a test project can be created.

    Project directories carry the ``.qda`` suffix (legacy convention).
    """
    return tmp_path / "TestProject.qda"


@pytest.fixture
def app_version() -> str:
    return "QualCoder 4.0.0-test"
