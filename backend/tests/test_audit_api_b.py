"""Regression tests for the api-b audit fixes (security helpers, server paths)."""

from __future__ import annotations

import pytest

from qualcoder_api.core.security import (
    assert_safe_zip_names,
    is_ssrf_blocked_url,
    sanitize_filename,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/",  # decimal 127.0.0.1
        "http://0x7f000001/",  # hex
        "http://127.1/",  # shorthand
        "http://0177.0.0.1/",  # octal
        "http://10.1/",  # shorthand private
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6 loopback
        "http://[::ffff:169.254.169.254]/",
        "http://127.0.0.1/",
        "http://localhost/",
    ],
)
def test_ssrf_blocks_alternate_ip_spellings(url: str) -> None:
    assert is_ssrf_blocked_url(url)


@pytest.mark.parametrize(
    "url", ["https://example.com/", "http://8.8.8.8/", "https://1password.com/", "http://[2001:4860::8888]/"]
)
def test_ssrf_allows_public_hosts(url: str) -> None:
    assert not is_ssrf_blocked_url(url)


@pytest.mark.parametrize("name", ["C:evil", "C:/evil", "\\evil", "../x", "a/../../x"])
def test_zip_guard_rejects_escapes(name: str) -> None:
    with pytest.raises(ValueError):
        assert_safe_zip_names([name])


def test_server_project_zip_guard_uses_shared_rules() -> None:
    import io
    import zipfile

    from fastapi import HTTPException

    from qualcoder_api.api.v1.server_projects import _zip_safe_names

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("C:evil/data.qda", b"x")
    with zipfile.ZipFile(buf) as zf, pytest.raises(HTTPException) as exc:
        _zip_safe_names(zf)
    assert exc.value.status_code == 422


def test_project_name_cannot_shape_path() -> None:
    # create_project builds the folder from sanitize_filename(name).
    assert "/" not in sanitize_filename("../../etc/evil", "project")
    assert sanitize_filename("..", "project") != ".."
