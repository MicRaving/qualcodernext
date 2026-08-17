# Settings — appearance, language, AI, pseudonyms, updates

The Settings pane is a wide right-bar panel with stacked headline sections.
Settings **auto-save**: AI settings persist debounced on change (no Save
button); theme and language apply immediately. Settings is available with or
without an open project (theme, AI and transcription options are
machine-level).

## How to reach it

- Ribbon → **Settings** (gear icon, right side).

## Sections

### Appearance

- **Dark / light theme** switch (persisted; defaults to the OS preference).

### Language

- **UI locale** dropdown — all supported languages.

### Import / Export

The embedded interchange view (see [interchange.md](interchange.md)): REFI
export link and auto-detected import — reachable from Settings without leaving
the pane.

### Accessibility

- The **display-mode** dropdown (off / screenreader / high-contrast /
  large-text / reduced-motion / colorblind-friendly) with a short explanation.

### AI assistant

- **Enable** switch.
- **Provider**: Ollama, LM Studio (local — probed on open and on pick;
  unreachable providers are greyed out with an "(unreachable)" hint),
  opencode-go, Gemini, GPT, Claude, custom. Picking a provider fills its
  preset base URL and model.
- **Model**: dropdown populated from the provider (polled every 60 s while the
  pane is open, so newly pulled local models appear); loading/unavailable
  hints.
- **API base URL** (editing switches the provider to "custom"), **API key**
  (password field; optional for local providers, required hint for cloud
  ones), **MCP permissions** (read / write / full).
- **Service status**: a Check button probes the provider and shows OK /
  broken for a few seconds (with the probe error).
- **Semantic index**: status (chunks + embedding model when built),
  Build / Rebuild, Delete, and a help flyout.
- A draft cache preserves typed values across pane open/close; the backend
  never overwrites a stored key with a blank one.

### Pseudonyms

Add a **pseudonym pair** (original → replacement, min 2 chars), list all
pairs, delete them. Used when exporting/rendering text — for anonymising
quotes in published material.

### App updates (desktop)

Auto-update toggle, check interval (daily/weekly/never), **Check now**,
**Install when available** (with download progress). The browser build notes
that updates are desktop-only.

### Project maintenance

- **Compact on close** switch (maintenance pass when the project closes).

### R integration and About

A status card reports whether **R** is installed (version + path), with a link
to install it when missing. The **About** section shows a short app text.
These two always sit at the very bottom of the pane.

## High-level logic

AI settings, pseudonyms and update/maintenance preferences are stored per
machine; the AI settings gate the whole AI feature (chat, search, MCP). The
semantic index is per project and lives beside the project folder, so it can
be rebuilt or deleted independently of the AI provider config.
