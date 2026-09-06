"""Nightly/delta version scheme — ``X.Y.Z`` stable vs ``X.Y.Z_NNN`` nightly.

Stable releases ship as full Tauri installers (``qcnext-latest.json``).
Delta/nightly patches ship as small signed zips (``qcnext-nightly.json``)
numbered ``<base>_<NNN>`` (e.g. ``0.1.13_001``).

Rules (mirrored in ``frontend/src/stores/updates.ts`` — keep in sync):

- ``tauri.conf.json`` / ``Cargo.toml`` / ``package.json`` always carry the
  BASE semver (``X.Y.Z``); Tauri/Cargo reject ``_NNN`` suffixes. Only
  ``APP_VERSION`` and the nightly manifest carry the full ``X.Y.Z_NNN``.
- A nightly is OLDER than the stable of the same base
  (``0.1.13_009 < 0.1.13``), so opting out of nightlies converges back to
  the next stable. Nightlies order by their counter.
- ``stable`` channel users are only offered non-nightly candidates;
  ``nightly`` channel users are offered anything newer (nightly or stable).
"""

from __future__ import annotations

import re

#: ``0.1.13`` or ``0.1.13_001`` (1-5 digit counter, zero-padded by convention).
NIGHTLY_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:_(\d{1,5}))?$")

UPDATE_CHANNELS: tuple[str, ...] = ("stable", "nightly")


def parse(version: str) -> tuple[int, int, int, int | None]:
    """Parse ``X.Y.Z[_NNN]`` into ``(major, minor, patch, nightly|None)``."""
    match = NIGHTLY_RE.match((version or "").strip())
    if not match:
        raise ValueError(f"invalid version {version!r} — expected X.Y.Z[_NNN]")
    major, minor, patch, nightly = match.groups()
    return int(major), int(minor), int(patch), int(nightly) if nightly is not None else None


def base_of(version: str) -> str:
    """The stable base of a version (``0.1.13_001`` -> ``0.1.13``)."""
    major, minor, patch, _ = parse(version)
    return f"{major}.{minor}.{patch}"


def is_nightly(version: str) -> bool:
    """Whether the version carries an ``_NNN`` nightly counter."""
    return parse(version)[3] is not None


def format_version(base: str, nightly: int | None) -> str:
    """Format a base + optional counter (``0.1.13``, ``3`` -> ``0.1.13_003``)."""
    major, minor, patch, _ = parse(base)
    if nightly is None:
        return f"{major}.{minor}.{patch}"
    if not 0 <= nightly <= 99999:
        raise ValueError(f"nightly counter out of range: {nightly!r}")
    return f"{major}.{minor}.{patch}_{nightly:03d}"


def compare(left: str, right: str) -> int:
    """Compare two versions: -1 / 0 / +1.

    Base semver compares first; within the same base, any nightly sorts
    BEFORE the stable (``_009 < stable``) and nightlies order by counter.
    """
    left_parts = parse(left)
    right_parts = parse(right)
    if left_parts[:3] != right_parts[:3]:
        return -1 if left_parts[:3] < right_parts[:3] else 1
    left_nightly, right_nightly = left_parts[3], right_parts[3]
    if left_nightly == right_nightly:
        return 0
    # Stable (None) is newer than any nightly of the same base.
    if left_nightly is None:
        return 1
    if right_nightly is None:
        return -1
    return -1 if left_nightly < right_nightly else 1


def is_newer(candidate: str, current: str) -> bool:
    """Whether ``candidate`` is strictly newer than ``current``."""
    try:
        return compare(candidate, current) > 0
    except ValueError:
        return False


def visible_on_channel(candidate: str, current: str, channel: str) -> bool:
    """Whether ``candidate`` should be offered on ``channel``.

    - ``stable``: only non-nightly candidates newer than current.
    - ``nightly``: anything newer (nightly or stable upgrade path).
    Unknown channels fall back to ``stable`` behaviour.
    """
    if channel not in UPDATE_CHANNELS:
        channel = "stable"
    try:
        nightly = is_nightly(candidate)
    except ValueError:
        return False
    if channel == "stable" and nightly:
        return False
    return is_newer(candidate, current)
