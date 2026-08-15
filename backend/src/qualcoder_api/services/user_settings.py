"""User settings persistence — ``~/.qualcoder/settings.json``.

Kept intentionally small: recent projects, last coder name, theme, and the
optional AI feature gate. The full settings surface arrives with the settings
UI (Phase 9).
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path

from qualcoder_api.services.transcription import TRANSCRIPTION_DEFAULTS

logger = logging.getLogger(__name__)

QUALCODER_HOME = Path(os.path.expanduser("~")) / ".qualcoder"
SETTINGS_FILE = QUALCODER_HOME / "settings.json"

AI_DEFAULTS: dict = {
    "enabled": False,
    "provider": "ollama",
    "api_base": "http://localhost:11434/v1",  # Ollama default
    "model": "llama3.2",
    "api_key": "",
    "mcp_permissions": "read",
}

# OpenAI-compatible providers. Gemini's OpenAI endpoint is on
# generativelanguage.googleapis.com; Claude uses Anthropic's OpenAI-compat
# layer. Model names track the current standard models.
AI_PROVIDER_DEFAULTS: dict = {
    "ollama": {"api_base": "http://localhost:11434/v1", "model": "llama3.2"},
    "lmstudio": {"api_base": "http://127.0.0.1:1234/v1", "model": ""},
    "opencode-go": {"api_base": "http://localhost:8080/v1", "model": "deepseek-v4-flash"},
    "gemini": {
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.6-flash",
    },
    "gpt": {"api_base": "https://api.openai.com/v1", "model": "gpt-5.6"},
    "claude": {"api_base": "https://api.anthropic.com/v1", "model": "claude-sonnet-4-6"},
}

#: Project-maintenance preferences. ``compact_on_close`` opts into a full
#: compaction (checkpoint + VACUUM + index rebuild) on every project close;
#: ``last_compact`` is a read-only timestamp stamped by the backend whenever
#: a compaction actually ran (manual or automatic).
MAINTENANCE_DEFAULTS: dict = {
    "compact_on_close": False,
    "last_compact": "",
}

DEFAULT_SETTINGS: dict = {
    "codername": "default",
    "coders": ["default"],
    "theme": "dark",
    "recent_projects": [],
    "ai": dict(AI_DEFAULTS),
    "transcription": dict(TRANSCRIPTION_DEFAULTS),
    "sync": {"enabled": False},
    "updates": {"check_interval": "daily", "auto_update": False},
    "maintenance": dict(MAINTENANCE_DEFAULTS),
    "auto_open_project": True,
    #: Optional Reddit API app credentials (``reddit.com/prefs/apps``,
    #: "script" type). When BOTH are non-empty the Reddit scraper uses
    #: authenticated app-only OAuth (``client_credentials``) instead of the
    #: anonymous ``.json`` endpoint, which Reddit blocks for scripts.
    "reddit_client_id": "",
    "reddit_client_secret": "",
}

# Per-project collaboration-sync decisions: "auto" re-detects the shared
# folder on every open; "on"/"off" are remembered manual toggles.
SYNC_OVERRIDE_MODES: tuple[str, ...] = ("auto", "on", "off")

UPDATES_DEFAULTS: dict = {
    "check_interval": "daily",
    "auto_update": False,
}


def get_updates_settings(settings: dict | None = None) -> dict:
    """Return the app-update preferences (check cadence + auto-install)."""
    settings = settings or load_settings()
    updates = settings.get("updates")
    if not isinstance(updates, dict):
        updates = {}
    interval = updates.get("check_interval", UPDATES_DEFAULTS["check_interval"])
    if interval not in ("daily", "weekly", "never"):
        interval = UPDATES_DEFAULTS["check_interval"]
    return {
        "check_interval": interval,
        "auto_update": bool(updates.get("auto_update", UPDATES_DEFAULTS["auto_update"])),
    }


def save_updates_settings(updates: dict, settings: dict | None = None) -> dict:
    """Validate and persist the app-update preferences."""
    settings = settings or load_settings()
    if not isinstance(updates, dict):
        raise ValueError("updates settings must be a dict")
    interval = updates.get("check_interval", UPDATES_DEFAULTS["check_interval"])
    if interval not in ("daily", "weekly", "never"):
        interval = UPDATES_DEFAULTS["check_interval"]
    clean = {
        "check_interval": interval,
        "auto_update": bool(updates.get("auto_update", UPDATES_DEFAULTS["auto_update"])),
    }
    settings["updates"] = clean
    save_settings(settings)
    return dict(clean)


def get_maintenance_settings(settings: dict | None = None) -> dict:
    """Return the project-maintenance preferences (compact on close)."""
    settings = settings or load_settings()
    maintenance = settings.get("maintenance")
    if not isinstance(maintenance, dict):
        maintenance = {}
    last_compact = maintenance.get("last_compact")
    return {
        "compact_on_close": bool(maintenance.get("compact_on_close", False)),
        "last_compact": last_compact if isinstance(last_compact, str) else "",
    }


def save_maintenance_settings(maintenance: dict, settings: dict | None = None) -> dict:
    """Validate and persist the project-maintenance preferences.

    ``last_compact`` is backend-maintained: a blank/missing value keeps the
    stored timestamp.
    """
    settings = settings or load_settings()
    if not isinstance(maintenance, dict):
        raise ValueError("maintenance settings must be a dict")
    current = get_maintenance_settings(settings)
    last_compact = maintenance.get("last_compact")
    clean = {
        "compact_on_close": bool(maintenance.get("compact_on_close", False)),
        "last_compact": (
            last_compact if isinstance(last_compact, str) and last_compact else current["last_compact"]
        ),
    }
    settings["maintenance"] = clean
    save_settings(settings)
    return dict(clean)


def _settings_str(settings: dict, key: str, default: str = "") -> str:
    """A settings value coerced to str (None -> default)."""
    value = settings.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def get_reddit_credentials(settings: dict | None = None) -> dict:
    """Return the optional Reddit API app credentials (client ID + secret).

    Both values must be non-empty for the Reddit scraper to use
    authenticated app-only OAuth (``client_credentials``); otherwise it
    falls back to the anonymous ``.json`` endpoint.
    """
    settings = settings or load_settings()
    return {
        "client_id": _settings_str(settings, "reddit_client_id", "").strip(),
        "client_secret": _settings_str(settings, "reddit_client_secret", "").strip(),
    }


def save_reddit_credentials(credentials: dict, settings: dict | None = None) -> dict:
    """Validate and persist the Reddit API app credentials.

    Blank values are stored as-is: a blank client ID means the scraper
    falls back to anonymous access. Unlike ``save_ai_settings`` there is
    no "blank keeps the stored value" rule here — callers that cannot
    read the stored value back must enforce that themselves.
    """
    settings = settings or load_settings()
    if not isinstance(credentials, dict):
        raise ValueError("Reddit credentials must be a dict")
    settings["reddit_client_id"] = _settings_str(credentials, "client_id", "").strip()
    settings["reddit_client_secret"] = _settings_str(credentials, "client_secret", "").strip()
    save_settings(settings)
    return get_reddit_credentials(settings)


def get_compact_on_close(settings: dict | None = None) -> bool:
    """Whether the full compaction runs automatically on project close."""
    settings = settings or load_settings()
    return bool(get_maintenance_settings(settings)["compact_on_close"])


def set_compact_on_close(enabled: bool, settings: dict | None = None) -> bool:
    """Persist the compact-on-close switch."""
    settings = settings or load_settings()
    maintenance = get_maintenance_settings(settings)
    maintenance["compact_on_close"] = bool(enabled)
    save_maintenance_settings(maintenance, settings)
    return bool(enabled)


def get_last_compact(settings: dict | None = None) -> str:
    """Timestamp of the last compaction that actually ran ("" if never)."""
    settings = settings or load_settings()
    return get_maintenance_settings(settings)["last_compact"]


def set_last_compact(settings: dict | None = None) -> str:
    """Stamp the maintenance settings with the time a compaction ran."""
    settings = settings or load_settings()
    timestamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    maintenance = get_maintenance_settings(settings)
    maintenance["last_compact"] = timestamp
    save_maintenance_settings(maintenance, settings)
    return timestamp


def get_sync_settings(settings: dict | None = None) -> dict:
    """Return the collaboration-sync settings (enabled flag)."""
    settings = settings or load_settings()
    sync = settings.get("sync")
    if not isinstance(sync, dict):
        sync = {}
    return {"enabled": bool(sync.get("enabled", False))}


def save_sync_settings(enabled: bool, settings: dict | None = None) -> dict:
    """Persist the collaboration-sync switch."""
    settings = settings or load_settings()
    settings["sync"] = {"enabled": bool(enabled)}
    save_settings(settings)
    return {"enabled": bool(enabled)}


def get_sync_override(project_path: str, settings: dict | None = None) -> str:
    """The remembered per-project sync decision ("auto" by default).

    "on"/"off" are written by manual toggles in the UI and win over the
    shared-folder auto-detection on the next project open; "auto" keeps
    re-detecting on every open.
    """
    settings = settings or load_settings()
    overrides = settings.get("sync_override")
    if isinstance(overrides, dict):
        mode = overrides.get(project_path)
        if mode in SYNC_OVERRIDE_MODES:
            return mode
    return "auto"


def set_sync_override(project_path: str, mode: str, settings: dict | None = None) -> str:
    """Remember a per-project sync decision (manual toggle)."""
    settings = settings or load_settings()
    if mode not in SYNC_OVERRIDE_MODES:
        raise ValueError(f"sync override must be one of {SYNC_OVERRIDE_MODES}")
    overrides = settings.get("sync_override")
    if not isinstance(overrides, dict):
        overrides = {}
    overrides[project_path] = mode
    settings["sync_override"] = overrides
    save_settings(settings)
    return mode


def get_auto_open_project(settings: dict | None = None) -> bool:
    """Whether the packaged app auto-opens the most recent project."""
    settings = settings or load_settings()
    return bool(settings.get("auto_open_project", DEFAULT_SETTINGS["auto_open_project"]))


def save_auto_open_project(enabled: bool, settings: dict | None = None) -> bool:
    """Persist the auto-open-on-start setting."""
    settings = settings or load_settings()
    settings["auto_open_project"] = bool(enabled)
    save_settings(settings)
    return bool(enabled)


def load_settings() -> dict:
    """Load user settings, merging defaults for missing keys."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                settings.update(data)
    except (OSError, json.JSONDecodeError) as err:
        logger.warning("Failed to load user settings: %s", err)
    return settings


def save_settings(settings: dict) -> None:
    try:
        QUALCODER_HOME.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as err:
        logger.warning("Failed to save user settings: %s", err)


def get_recent_projects(settings: dict | None = None) -> list[str]:
    settings = settings or load_settings()
    recent = settings.get("recent_projects") or []
    return [p for p in recent if isinstance(p, str)][:10]


def append_recent_project(project_path: str, settings: dict | None = None) -> dict:
    """Add a project path to the front of the recent list (dedup, max 10)."""
    settings = settings or load_settings()
    recent = get_recent_projects(settings)
    if project_path in recent:
        recent.remove(project_path)
    recent.insert(0, project_path)
    settings["recent_projects"] = recent[:10]
    save_settings(settings)
    return settings


def get_ai_settings(settings: dict | None = None) -> dict:
    """Return the AI feature dict, merged with defaults when missing/malformed."""
    settings = settings or load_settings()
    ai = settings.get("ai")
    if not isinstance(ai, dict):
        ai = {}
    merged = dict(AI_DEFAULTS)
    merged.update({k: v for k, v in ai.items() if k in AI_DEFAULTS})
    merged["enabled"] = bool(merged["enabled"])
    provider = merged["provider"]
    if not isinstance(provider, str) or provider not in AI_PROVIDER_DEFAULTS:
        provider = "custom"
        merged["provider"] = provider
    preset = AI_PROVIDER_DEFAULTS.get(provider, {})
    for key in ("api_base", "model", "api_key"):
        value = merged[key]
        if not isinstance(value, str):
            merged[key] = AI_DEFAULTS[key] if value is None else str(value)
    # Missing/empty base URL falls back to the provider's default.
    if not merged["api_base"].strip() and preset.get("api_base"):
        merged["api_base"] = preset["api_base"]
    return merged


def save_ai_settings(ai: dict, settings: dict | None = None) -> dict:
    """Validate and store the AI settings dict, then persist and return it.

    An empty ``api_key`` in the request does NOT overwrite a stored key —
    the settings pane never knows the saved key (it is not returned by the
    status endpoint), so a blank value means "leave it unchanged". The
    returned dict always carries the effective key.
    """
    settings = settings or load_settings()
    if not isinstance(ai, dict):
        raise ValueError("AI settings must be a dict")
    stored_ai = settings.get("ai")
    if not isinstance(stored_ai, dict):
        stored_ai = {}
    provider = str(ai.get("provider") or AI_DEFAULTS["provider"])
    preset = AI_PROVIDER_DEFAULTS.get(provider)
    if preset is None:
        provider = "custom"
        preset = {}
    api_base = str(ai.get("api_base") or "").strip()
    if not api_base and preset.get("api_base"):
        api_base = preset["api_base"]
    elif preset.get("api_base") and api_base != preset["api_base"]:
        # The URL was customized away from the provider's default.
        provider = "custom"
        preset = {}
    model = str(ai.get("model") or "").strip()
    if not model and preset.get("model"):
        model = preset["model"]
    api_key = str(ai.get("api_key") or "").strip()
    if not api_key:
        # Blank key = keep the stored one (the UI cannot read it back).
        api_key = str(stored_ai.get("api_key") or "").strip()
    clean = {
        "enabled": bool(ai.get("enabled", False)),
        "provider": provider,
        "api_base": api_base or AI_DEFAULTS["api_base"],
        "model": model or AI_DEFAULTS["model"],
        "api_key": api_key,
        "mcp_permissions": (
            str(ai.get("mcp_permissions") or "read")
            if str(ai.get("mcp_permissions") or "read") in ("read", "write", "full")
            else "read"
        ),
    }
    settings["ai"] = clean
    # The settings pane ships the optional Reddit API credentials through
    # the AI-settings save (its only auto-save mechanism). Blank values
    # keep the stored ones — the pane never reads them back, so a blank
    # means "leave unchanged" (the same rule as the AI api_key).
    for key in ("reddit_client_id", "reddit_client_secret"):
        if key in ai and isinstance(ai[key], str) and ai[key].strip():
            settings[key] = ai[key].strip()
    save_settings(settings)
    return dict(clean)


def get_codername(settings: dict | None = None) -> str:
    """Return the last used coder name (falls back to "default")."""
    settings = settings or load_settings()
    codername = settings.get("codername")
    return codername if isinstance(codername, str) and codername else "default"


def resolve_owner(owner: str | None) -> str:
    """Resolve an explicit owner to the current coder when omitted."""
    if owner is None:
        return get_codername()
    owner = owner.strip()
    return owner or get_codername()


def get_transcription_settings(settings: dict | None = None) -> dict:
    """Return the transcription defaults dict, merged with defaults."""
    settings = settings or load_settings()
    tr = settings.get("transcription")
    if not isinstance(tr, dict):
        tr = {}
    merged = dict(TRANSCRIPTION_DEFAULTS)
    merged.update({k: v for k, v in tr.items() if k in TRANSCRIPTION_DEFAULTS})
    # Whisper is the only engine now; tolerate a legacy engine value stored
    # in old settings files by falling back to whisper on read.
    if merged.get("engine") != "whisper":
        merged["engine"] = "whisper"
    return merged


def save_transcription_settings(tr: dict, settings: dict | None = None) -> dict:
    """Validate and store the transcription defaults dict."""
    settings = settings or load_settings()
    if not isinstance(tr, dict):
        raise ValueError("transcription settings must be a dict")
    clean = dict(TRANSCRIPTION_DEFAULTS)
    clean.update({k: v for k, v in tr.items() if k in TRANSCRIPTION_DEFAULTS})
    if clean.get("engine") != "whisper":
        clean["engine"] = "whisper"
    settings["transcription"] = clean
    save_settings(settings)
    return dict(clean)


def get_coders(settings: dict | None = None) -> list[str]:
    """Return the known coder names (always includes the current one)."""
    settings = settings or load_settings()
    coders = settings.get("coders")
    if not isinstance(coders, list):
        coders = []
    names = [c for c in coders if isinstance(c, str) and c]
    current = get_codername(settings)
    if current not in names:
        names = [current, *names]
    return names


def set_coders(coders: list[str], settings: dict | None = None) -> list[str]:
    """Persist the coder list (keeping the current coder valid)."""
    settings = settings or load_settings()
    clean = [c for c in coders if isinstance(c, str) and c]
    if not clean:
        clean = ["default"]
    current = get_codername(settings)
    if current not in clean:
        clean.append(current)
    settings["coders"] = clean
    save_settings(settings)
    return list(clean)


def set_codername(name: str, settings: dict | None = None) -> str:
    """Switch the current coder (ensuring it exists in the coder list)."""
    settings = settings or load_settings()
    name = name.strip()
    if not name:
        raise ValueError("coder name must not be empty")
    coders = get_coders(settings)
    if name not in coders:
        coders.append(name)
        settings["coders"] = coders
    settings["codername"] = name
    save_settings(settings)
    return name


def get_color_scheme(settings: dict | None = None) -> dict:
    """Return the code color palette + ranges (custom overrides or defaults)."""
    settings = settings or load_settings()
    scheme = settings.get("color_scheme")
    if not isinstance(scheme, dict) or not isinstance(scheme.get("colors"), list):
        from qualcoder_api.persistence.repositories import CODE_COLORS, COLOUR_RANGES

        return {"colors": list(CODE_COLORS), "ranges": [dict(r) for r in COLOUR_RANGES]}
    colors = [c for c in scheme["colors"] if isinstance(c, str) and c.startswith("#")]
    if len(colors) < 10:  # too few — fall back to the default palette
        from qualcoder_api.persistence.repositories import CODE_COLORS, COLOUR_RANGES

        return {"colors": list(CODE_COLORS), "ranges": [dict(r) for r in COLOUR_RANGES]}
    ranges = scheme.get("ranges") or []
    return {"colors": colors, "ranges": ranges}


def save_color_scheme(colors: list[str], ranges: list[dict] | None = None,
                      settings: dict | None = None) -> dict:
    """Persist a custom code color palette (Settings → Colour scheme)."""
    settings = settings or load_settings()
    clean_colors = [c for c in colors if isinstance(c, str) and c.startswith("#")]
    if not clean_colors:
        raise ValueError("color scheme needs at least one colour")
    clean = {"colors": clean_colors, "ranges": ranges or []}
    settings["color_scheme"] = clean
    save_settings(settings)
    return clean


def reset_color_scheme(settings: dict | None = None) -> dict:
    """Restore the default 120-colour palette."""
    settings = settings or load_settings()
    settings.pop("color_scheme", None)
    save_settings(settings)
    return get_color_scheme(settings)
