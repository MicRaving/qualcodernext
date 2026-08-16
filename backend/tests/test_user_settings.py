"""User-settings tests — app-level settings (auto-open, sync overrides).

The settings file is monkeypatched to a tmp path so the developer's real
``~/.qualcoder/settings.json`` is never read or written.
"""

from __future__ import annotations

import pytest

from qualcoder_api.services import user_settings


def test_auto_open_project_defaults_to_true(monkeypatch, tmp_path):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    assert user_settings.get_auto_open_project() is True


def test_auto_open_project_persistence(monkeypatch, tmp_path):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    assert user_settings.save_auto_open_project(False) is False
    assert user_settings.get_auto_open_project() is False
    assert user_settings.save_auto_open_project(True) is True
    assert user_settings.get_auto_open_project() is True


def test_sync_override_defaults_to_auto(monkeypatch, tmp_path):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    assert user_settings.get_sync_override(r"C:\Projects\Study.qda") == "auto"


def test_sync_override_persistence(monkeypatch, tmp_path):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    path = r"C:\Projects\Study.qda"
    assert user_settings.set_sync_override(path, "off") == "off"
    assert user_settings.get_sync_override(path) == "off"
    # Other projects are unaffected (still "auto").
    assert user_settings.get_sync_override(r"C:\Projects\Other.qda") == "auto"
    # "auto" restores the re-detecting behaviour.
    assert user_settings.set_sync_override(path, "auto") == "auto"
    assert user_settings.get_sync_override(path) == "auto"


def test_sync_override_rejects_unknown_modes(monkeypatch, tmp_path):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    with pytest.raises(ValueError, match="sync override"):
        user_settings.set_sync_override(r"C:\Projects\Study.qda", "sometimes")


def test_updates_settings_default_to_auto_update(monkeypatch, tmp_path):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    settings = user_settings.get_updates_settings()
    assert settings["auto_update"] is True
    assert settings["check_interval"] == "daily"


def test_updates_settings_persistence(monkeypatch, tmp_path):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    assert user_settings.save_updates_settings(
        {"check_interval": "weekly", "auto_update": False}
    ) == {"check_interval": "weekly", "auto_update": False}
    assert user_settings.get_updates_settings() == {
        "check_interval": "weekly",
        "auto_update": False,
    }
    # Turning auto-update back on (default) sticks across reloads.
    assert user_settings.save_updates_settings(
        {"check_interval": "never", "auto_update": True}
    ) == {"check_interval": "never", "auto_update": True}
    assert user_settings.get_updates_settings() == {
        "check_interval": "never",
        "auto_update": True,
    }
