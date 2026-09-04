"""User settings persistence — ``~/.qualcoder/settings.json``.

Kept intentionally small: recent projects, last coder name, theme, and the
optional AI feature gate. The full settings surface arrives with the settings
UI (Phase 9).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path

from qualcoder_api.core.timeutil import now
from qualcoder_api.services.transcription import TRANSCRIPTION_DEFAULTS

logger = logging.getLogger(__name__)

QUALCODER_HOME = Path(os.path.expanduser("~")) / ".qualcoder"
SETTINGS_FILE = QUALCODER_HOME / "settings.json"

#: Serializes settings-file access. Requests hit these helpers concurrently
#: (project create/open bursts), and a read during a non-atomic write used to
#: yield truncated JSON → DEFAULTS → the next save wiped the real settings.
_SETTINGS_LOCK = threading.Lock()

#: The default wrapping prompt for AI chat: appended to the mode persona as a
#: system-level directive. Users can override it via the template creator (an
#: empty stored value falls back to this).
DEFAULT_WRAPPING_PROMPT = (
    "Be short and concise: answer directly, keep responses brief and to the "
    "point, and avoid unnecessary detail."
)

AI_DEFAULTS: dict = {
    "enabled": False,
    "provider": "lmstudio",
    "api_base": "http://127.0.0.1:1234/v1",  # LM Studio default
    "model": "",
    "api_key": "",
    #: Actively start LM Studio (server + configured model) when an AI
    #: request finds the backend unreachable. lmstudio provider only.
    "auto_start_backend": True,
    "mcp_permissions": "read",
    #: Custom wrapping prompt for AI chat ("" = DEFAULT_WRAPPING_PROMPT).
    "wrapping_prompt": "",
    #: MCP mode: "internal" (QCnext's own tools) or "external" (stdio server).
    "mcp_mode": "internal",
    #: External MCP server connection (stdio).
    "mcp_server_command": "",
    "mcp_server_args": [],
    "mcp_server_env": {},
}

# OpenAI-compatible providers. Gemini's OpenAI endpoint is on
# generativelanguage.googleapis.com; Claude uses Anthropic's OpenAI-compat
# layer. Model names track the current standard models. LM Studio serves any
# locally-loaded model, so no default model is pinned.
AI_PROVIDER_DEFAULTS: dict = {
    "lmstudio": {"api_base": "http://127.0.0.1:1234/v1", "model": ""},
    "ollama": {"api_base": "http://localhost:11434/v1", "model": "llama3.2"},
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
    "updates": {"check_interval": "daily", "auto_update": True},
    "maintenance": dict(MAINTENANCE_DEFAULTS),
    "auto_open_project": True,
}

# Per-project collaboration-sync decisions: "auto" re-detects the shared
# folder on every open; "on"/"off" are remembered manual toggles.
SYNC_OVERRIDE_MODES: tuple[str, ...] = ("auto", "on", "off")

UPDATES_DEFAULTS: dict = {
    "check_interval": "daily",
    "auto_update": True,
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
    timestamp = now()
    maintenance = get_maintenance_settings(settings)
    maintenance["last_compact"] = timestamp
    save_maintenance_settings(maintenance, settings)
    return timestamp


#: Default background-sync cadence (seconds). Configurable via the settings
#: dropdown (1 min is the default; the cycle polls the stored value each tick).
SYNC_INTERVAL_DEFAULT_SECS = 60
#: Allowed cadences for the settings dropdown (seconds). "Automatic" is not
#: offered — a concrete interval keeps the shared-folder write rate predictable.
SYNC_INTERVAL_CHOICES_SECS = (15, 30, 60, 120, 300)


def get_sync_settings(settings: dict | None = None) -> dict:
    """Return the collaboration-sync settings (enabled flag + interval)."""
    settings = settings or load_settings()
    sync = settings.get("sync")
    if not isinstance(sync, dict):
        sync = {}
    interval = int(sync.get("interval_secs", SYNC_INTERVAL_DEFAULT_SECS))
    if interval not in SYNC_INTERVAL_CHOICES_SECS:
        interval = SYNC_INTERVAL_DEFAULT_SECS
    return {"enabled": bool(sync.get("enabled", False)), "interval_secs": interval}


def save_sync_settings(
    enabled: bool, settings: dict | None = None, interval_secs: int | None = None
) -> dict:
    """Persist the collaboration-sync switch (and optional cadence)."""
    settings = settings or load_settings()
    # Copy the nested dict to avoid mutating DEFAULT_SETTINGS via the shallow
    # copy that load_settings returns when the file does not exist.
    raw_sync = settings.get("sync")
    sync = dict(raw_sync) if isinstance(raw_sync, dict) else {}
    sync["enabled"] = bool(enabled)
    if interval_secs is not None:
        if int(interval_secs) not in SYNC_INTERVAL_CHOICES_SECS:
            interval_secs = SYNC_INTERVAL_DEFAULT_SECS
        sync["interval_secs"] = int(interval_secs)
    settings["sync"] = sync
    save_settings(settings)
    return {"enabled": bool(enabled), "interval_secs": int(sync.get("interval_secs", SYNC_INTERVAL_DEFAULT_SECS))}


def get_sync_interval_secs(settings: dict | None = None) -> int:
    """The configured background-sync cadence (seconds)."""
    return int(get_sync_settings(settings).get("interval_secs", SYNC_INTERVAL_DEFAULT_SECS))


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
    import copy

    settings = copy.deepcopy(DEFAULT_SETTINGS)
    try:
        with _SETTINGS_LOCK:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # The Reddit API credentials were removed with the Reddit
                    # scraper purge — drop legacy stored keys so they never
                    # resurface or get persisted again.
                    data.pop("reddit_client_id", None)
                    data.pop("reddit_client_secret", None)
                    settings.update(data)
    except (OSError, json.JSONDecodeError) as err:
        logger.warning("Failed to load user settings: %s", err)
    return settings


def save_settings(settings: dict) -> None:
    import contextlib as _contextlib

    try:
        with _SETTINGS_LOCK:
            QUALCODER_HOME.mkdir(parents=True, exist_ok=True)
            # Atomic replace: a concurrent reader (FastAPI serves requests
            # concurrently) must never observe a half-written file — reading
            # truncated JSON used to fall back to DEFAULTS and the next save
            # then WIPED every stored key (recent projects vanished mid-run
            # on slow CI disks).
            tmp = SETTINGS_FILE.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            with _contextlib.suppress(OSError):
                os.chmod(tmp, 0o600)
            os.replace(tmp, SETTINGS_FILE)
            with _contextlib.suppress(OSError):
                os.chmod(SETTINGS_FILE, 0o600)
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
    merged["auto_start_backend"] = bool(merged.get("auto_start_backend", True))
    provider = merged["provider"]
    if not isinstance(provider, str) or provider not in AI_PROVIDER_DEFAULTS:
        provider = "custom"
        merged["provider"] = provider
    preset = AI_PROVIDER_DEFAULTS.get(provider, {})
    for key in ("api_base", "model", "api_key"):
        value = merged[key]
        if not isinstance(value, str):
            merged[key] = AI_DEFAULTS[key] if value is None else str(value)
    wrapping = merged.get("wrapping_prompt")
    if not isinstance(wrapping, str):
        wrapping = AI_DEFAULTS["wrapping_prompt"]
    merged["wrapping_prompt"] = wrapping
    # Missing/empty base URL falls back to the provider's default.
    if not merged["api_base"].strip() and preset.get("api_base"):
        merged["api_base"] = preset["api_base"]
    # MCP mode validation.
    mcp_mode = merged.get("mcp_mode", "internal")
    if mcp_mode not in ("internal", "external"):
        mcp_mode = "internal"
    merged["mcp_mode"] = mcp_mode
    # External MCP server connection fields.
    cmd = merged.get("mcp_server_command")
    merged["mcp_server_command"] = str(cmd).strip() if isinstance(cmd, str) else ""
    args = merged.get("mcp_server_args")
    if isinstance(args, list):
        merged["mcp_server_args"] = [str(a) for a in args if isinstance(a, str)]
    else:
        merged["mcp_server_args"] = []
    env = merged.get("mcp_server_env")
    if isinstance(env, dict):
        merged["mcp_server_env"] = {
            str(k): str(v)
            for k, v in env.items()
            if isinstance(k, str) and isinstance(v, str)
        }
    else:
        merged["mcp_server_env"] = {}
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
    wrapping_prompt = ai.get("wrapping_prompt")
    if wrapping_prompt is None:
        # Not part of the request (e.g. the settings tab's auto-save) —
        # keep whatever is stored so the template creator's value survives.
        wrapping_prompt = str(stored_ai.get("wrapping_prompt") or "")
    else:
        wrapping_prompt = str(wrapping_prompt).strip()
    from qualcoder_api.core.security import validate_mcp_command as _validate_mcp

    try:
        _validate_mcp(
            str(ai.get("mcp_server_command") or "") if ai.get("mcp_server_command") is not None else None,
            ai.get("mcp_server_args") if isinstance(ai.get("mcp_server_args"), list) else None,
        )
    except ValueError as err:
        raise ValueError(str(err)) from err
    clean = {
        "enabled": bool(ai.get("enabled", False)),
        "provider": provider,
        "api_base": api_base or AI_DEFAULTS["api_base"],
        "model": model or AI_DEFAULTS["model"],
        "api_key": api_key,
        "auto_start_backend": (
            bool(ai["auto_start_backend"])
            if isinstance(ai.get("auto_start_backend"), bool)
            else bool(stored_ai.get("auto_start_backend", True))
        ),
        "mcp_permissions": (
            str(ai.get("mcp_permissions") or "")
            if str(ai.get("mcp_permissions") or "") in ("read", "write", "full")
            else str(stored_ai.get("mcp_permissions") or "read")
        ),
        "wrapping_prompt": wrapping_prompt,
        "mcp_mode": (
            str(ai["mcp_mode"])
            if isinstance(ai.get("mcp_mode"), str) and ai["mcp_mode"] in ("internal", "external")
            else str(stored_ai.get("mcp_mode") or "internal")
        ),
        "mcp_server_command": (
            str(ai["mcp_server_command"] or "").strip()
            if ai.get("mcp_server_command") is not None
            else str(stored_ai.get("mcp_server_command") or "")
        ),
        "mcp_server_args": (
            [str(a) for a in ai["mcp_server_args"]]
            if isinstance(ai.get("mcp_server_args"), list)
            else list(stored_ai.get("mcp_server_args") or [])
        ),
        "mcp_server_env": (
            {str(k): str(v) for k, v in ai["mcp_server_env"].items()
             if isinstance(k, str) and isinstance(v, str)}
            if isinstance(ai.get("mcp_server_env"), dict)
            else dict(stored_ai.get("mcp_server_env") or {})
        ),
    }
    settings["ai"] = clean
    save_settings(settings)
    return dict(clean)


def get_wrapping_prompt(settings: dict | None = None) -> str:
    """The effective AI-chat wrapping prompt (custom or the default)."""
    settings = settings or load_settings()
    ai = settings.get("ai")
    text = ai.get("wrapping_prompt", "") if isinstance(ai, dict) else ""
    return text.strip() if isinstance(text, str) and text.strip() else DEFAULT_WRAPPING_PROMPT


def save_wrapping_prompt(text: str, settings: dict | None = None) -> str:
    """Persist the AI-chat wrapping prompt (blank resets to the default)."""
    settings = settings or load_settings()
    ai = settings.get("ai")
    if not isinstance(ai, dict):
        ai = {}
    ai["wrapping_prompt"] = (text or "").strip()
    settings["ai"] = ai
    save_settings(settings)
    return get_wrapping_prompt(settings)


# ----------------------------------------------------------------------
# Per-mode personas + editable built-in templates + app-wide templates
# (stored app-wide in settings.json, so they work in every project).
# ----------------------------------------------------------------------


def get_ai_personas(settings: dict | None = None) -> dict[str, str]:
    """Stored per-mode persona overrides (mode -> custom system prompt).

    Only overrides are stored — a missing mode falls back to the built-in
    persona in ``ai_prompts.MODE_SYSTEM_PROMPTS``.
    """
    settings = settings or load_settings()
    personas = settings.get("ai_personas")
    if not isinstance(personas, dict):
        return {}
    return {str(k): v for k, v in personas.items() if isinstance(v, str) and v.strip()}


def save_ai_personas(overrides: dict, settings: dict | None = None) -> dict[str, str]:
    """Persist per-mode persona overrides (blank text clears the override)."""
    settings = settings or load_settings()
    if not isinstance(overrides, dict):
        raise ValueError("personas must be a dict")
    clean = {}
    for mode, text in overrides.items():
        if isinstance(text, str) and text.strip():
            clean[str(mode)] = text.strip()
    settings["ai_personas"] = clean
    save_settings(settings)
    return dict(clean)


def get_ai_prompt_overrides(settings: dict | None = None) -> dict[str, str]:
    """Stored overrides for built-in catalog templates (id -> custom text)."""
    settings = settings or load_settings()
    overrides = settings.get("ai_prompt_overrides")
    if not isinstance(overrides, dict):
        return {}
    return {str(k): v for k, v in overrides.items() if isinstance(v, str) and v.strip()}


def save_ai_prompt_override(prompt_id: str, text: str, settings: dict | None = None) -> dict[str, str]:
    """Persist an override for a built-in template (blank clears it)."""
    settings = settings or load_settings()
    overrides = get_ai_prompt_overrides(settings)
    text = (text or "").strip()
    if text:
        overrides[str(prompt_id)] = text
    else:
        overrides.pop(str(prompt_id), None)
    settings["ai_prompt_overrides"] = overrides
    save_settings(settings)
    return dict(overrides)


def reset_ai_prompt_override(prompt_id: str, settings: dict | None = None) -> dict[str, str]:
    """Clear a built-in template override, restoring the shipped text."""
    settings = settings or load_settings()
    overrides = get_ai_prompt_overrides(settings)
    overrides.pop(str(prompt_id), None)
    settings["ai_prompt_overrides"] = overrides
    save_settings(settings)
    return dict(overrides)


def get_ai_global_prompts(settings: dict | None = None) -> list[dict]:
    """App-wide custom templates, available in every project."""
    settings = settings or load_settings()
    prompts = settings.get("ai_global_prompts")
    if not isinstance(prompts, list):
        return []
    return [p for p in prompts if isinstance(p, dict) and p.get("id") and p.get("name")]


def save_ai_global_prompt(prompt: dict, settings: dict | None = None) -> dict:
    """Create or update an app-wide template (matched by ``id``)."""
    settings = settings or load_settings()
    prompts = get_ai_global_prompts(settings)
    name = str(prompt.get("name") or "").strip()
    text = str(prompt.get("text") or "").strip()
    if not name or not text:
        raise ValueError("template name and text are required")
    prompt_id = str(prompt.get("id") or uuid.uuid4().hex)
    entry = {
        "id": prompt_id,
        "name": name,
        "description": str(prompt.get("description") or "").strip(),
        "text": text,
        "created": str(prompt.get("created") or now()),
        "updated": now(),
    }
    for i, existing in enumerate(prompts):
        if existing.get("id") == prompt_id:
            entry["created"] = existing.get("created") or entry["created"]
            prompts[i] = entry
            break
    else:
        prompts.append(entry)
    settings["ai_global_prompts"] = prompts
    save_settings(settings)
    return dict(entry)


def delete_ai_global_prompt(prompt_id: str, settings: dict | None = None) -> bool:
    """Remove an app-wide template; True when one was actually deleted."""
    settings = settings or load_settings()
    prompts = get_ai_global_prompts(settings)
    before = len(prompts)
    prompts = [p for p in prompts if p.get("id") != prompt_id]
    settings["ai_global_prompts"] = prompts
    save_settings(settings)
    return len(prompts) < before


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
        from qualcoder_api.core.palette import CODE_COLORS, COLOUR_RANGES

        return {"colors": list(CODE_COLORS), "ranges": [dict(r) for r in COLOUR_RANGES]}
    colors = [c for c in scheme["colors"] if isinstance(c, str) and c.startswith("#")]
    if len(colors) < 10:  # too few — fall back to the default palette
        from qualcoder_api.core.palette import CODE_COLORS, COLOUR_RANGES

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


# Instance identity — stable per-machine UUID used for sidecar paths and
# presence identification. Stored outside the synced folder so it never
# travels with the project.
_INSTANCE_ID_PATH = QUALCODER_HOME / "sync" / "instance_id"
_instance_id: str | None = None


def get_instance_id() -> str:
    """Stable per-machine instance ID (12-char hex). Generated on first call,
    cached in memory for the process lifetime."""
    global _instance_id
    if _instance_id is not None:
        return _instance_id
    try:
        existing = _INSTANCE_ID_PATH.read_text(encoding="utf-8").strip()
        if existing and len(existing) >= 8:
            _instance_id = existing
            return existing
    except OSError:
        pass
    new_id = uuid.uuid4().hex[:12]
    try:
        _INSTANCE_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        _INSTANCE_ID_PATH.write_text(new_id, encoding="utf-8")
    except OSError as err:
        logger.warning("could not persist instance_id: %s", err)
    _instance_id = new_id
    return new_id
