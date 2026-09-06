"""Nightly version scheme tests — `X.Y.Z` stable vs `X.Y.Z_NNN` deltas.

Mirrors the TypeScript helpers in `frontend/src/stores/updates.ts`;
ordering rules must stay identical on both sides.
"""

from __future__ import annotations

import pytest

from qualcoder_api.services import versioning


def test_parse_stable_and_nightly():
    assert versioning.parse("0.1.13") == (0, 1, 13, None)
    assert versioning.parse("0.1.13_001") == (0, 1, 13, 1)
    assert versioning.parse("  1.2.3_42 ") == (1, 2, 3, 42)


def test_parse_rejects_garbage():
    for bad in ("", "1.2", "v1.2.3", "1.2.3-", "1.2.3_abc", "1.2.3_123456"):
        with pytest.raises(ValueError, match="invalid version"):
            versioning.parse(bad)


def test_base_of_and_is_nightly():
    assert versioning.base_of("0.1.13_001") == "0.1.13"
    assert versioning.base_of("0.1.13") == "0.1.13"
    assert versioning.is_nightly("0.1.13_001") is True
    assert versioning.is_nightly("0.1.13") is False


def test_format_version_round_trip():
    assert versioning.format_version("0.1.13", None) == "0.1.13"
    assert versioning.format_version("0.1.13", 1) == "0.1.13_001"
    with pytest.raises(ValueError, match="out of range"):
        versioning.format_version("0.1.13", 100000)


def test_nightly_is_newer_than_same_base_stable():
    # Nightlies are post-release patches: a client on the stable must be
    # offered the nightly built on top of it (the 0.1.14_001 incident).
    assert versioning.compare("0.1.14_001", "0.1.14") == 1
    assert versioning.compare("0.1.14", "0.1.14_001") == -1
    assert versioning.compare("0.1.13_001", "0.1.13_002") == -1
    assert versioning.compare("0.1.13_002", "0.1.13_002") == 0
    assert versioning.compare("0.1.12", "0.1.13_001") == -1
    assert versioning.compare("0.2.0_001", "0.1.13") == 1


def test_is_newer_rejects_garbage():
    assert versioning.is_newer("0.1.14_001", "0.1.13") is True
    assert versioning.is_newer("garbage", "0.1.13") is False


def test_visible_on_channel():
    # Stable users never see nightlies, even newer ones.
    assert versioning.visible_on_channel("0.1.14", "0.1.13", "stable") is True
    assert versioning.visible_on_channel("0.1.14_001", "0.1.13", "stable") is False
    # Nightly users see anything newer — nightlies and the next stable.
    assert versioning.visible_on_channel("0.1.14_001", "0.1.13", "nightly") is True
    assert versioning.visible_on_channel("0.1.13_002", "0.1.13_001", "nightly") is True
    assert versioning.visible_on_channel("0.1.14", "0.1.13_009", "nightly") is True
    assert versioning.visible_on_channel("0.1.13_001", "0.1.13_001", "nightly") is False
    # Regression: same-base nightly over the installed stable must show.
    assert versioning.visible_on_channel("0.1.14_001", "0.1.14", "nightly") is True
    assert versioning.visible_on_channel("0.1.14_001", "0.1.14", "stable") is False
    # Unknown channels fall back to stable behaviour.
    assert versioning.visible_on_channel("0.1.14_001", "0.1.13", "beta") is False
