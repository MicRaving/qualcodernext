# Settings — settings pane

Appearance, language, AI assistant configuration, pseudonyms and
Import/Export — a wide right-bar pane with stacked sections (dividers, no
cards). Settings auto-save: AI settings are persisted debounced on change
(no Save button); theme/language are applied immediately.

## How to reach it

Ribbon → Settings (gear icon, right side). Available with or without an open
project (theme, AI and transcription options are machine-level).

## Layout slots used

- Right bar only: `SettingsView` (LeftBar `borderSide="l"`, `width="lg"`).
- Center/left bar: unchanged.

## Features

- **Appearance**: dark/light theme switch (persisted in localStorage,
  defaults to the OS preference).
- **Language**: UI locale dropdown (all `LOCALE_NAMES`).
- **Import/Export**: the embedded `InterchangeView` (see interchange.md) —
  REFI export link and auto-detected import.
- **Accessibility**: the a11y mode dropdown (off / screenreader /
  high-contrast / large-text / reduced-motion / colorblind).
- **AI assistant**:
  - Enable switch.
  - **Provider**: Ollama, LM Studio (local — probed on open and on pick;
    unreachable providers are greyed out in the dropdown with an
    "(unreachable)" hint), opencode-go, Gemini, GPT, Claude, custom. Picking
    a provider fills its preset base URL and model.
  - **Model**: dropdown populated from `GET /ai/models` for the current
    provider/base (polled every 60 s while the pane is open so newly pulled
    local models appear); shows loading/unavailable hints.
  - **API base URL** (editing it switches the provider to "custom"),
    **API key** (password field, optional for local providers, required hint
    for cloud ones), **MCP permissions** (read / write / full).
  - **Service status**: Check button probes the configured provider and
    shows OK / broken for 3 s (with the probe error).
  - **Semantic index**: status (chunks + embedding model when built), Build /
    Rebuild, Delete, and a help flyout explaining the index.
  - A module-level draft cache preserves typed values (e.g. an API key)
    across pane open/close; the backend refuses to overwrite a stored key
    with a blank one.
- **Pseudonyms**: add a pseudonym pair (original → replacement, min 2
  chars), list all pairs, delete; used when exporting/rendering text.
- **App updates** (desktop): auto-update toggle, check interval
  (daily/weekly/never), Check now, Install when available; downloading
  progress; "desktop only" note in the browser.
- **About**: short app text.

## API endpoints used

- `GET /ai/status`, `GET /ai/models`, `PUT /ai/settings`
- `GET /ai/index`, `POST /ai/index`, `DELETE /ai/index`
- `GET/POST/DELETE /tools/pseudonyms`
- `GET/PUT /updates/settings` (+ update check/install via the updates store)
- `GET /interchange/export/refi` (export link), `POST /importers/auto` (import)

## Screenshot:

(to be inserted)
