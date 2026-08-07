"""Shared pytest fixtures for the qualcoder_api backend."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A fresh directory where a test project can be created.

    Project directories carry the ``.qda`` suffix (legacy convention).
    """
    return tmp_path / "TestProject.qda"


@pytest.fixture
def app_version() -> str:
    return "QualCoder 4.0.0-test"
