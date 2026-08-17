# AI — assistant chat, semantic search, and configuration

QCnext integrates local or cloud **LLMs** as a research assistant: a chat pane
grounded in your project, a **semantic search** over your texts via an
embedding index, and a Model Context Protocol (MCP) endpoint for tool access.
The feature must be enabled and configured first (see
[settings.md](settings.md) → AI assistant).

## How to reach it

- Ribbon → **AI** (sparkles icon, right side). Toggles the right-bar pane;
  the center view stays whatever it showed.

## The pane

The AI pane has a header with the **mode** select, the **prompt library**
select, and a **Chat / Search** tab toggle.

### Chat

- **Chat modes**: general, help, topic exploration, code analysis, text
  analysis, memo analysis.
- **Prompt library**: a second select lists the prompts registered for the
  current mode; picking one overrides the mode's default prompt for the next
  message.
- **Message thread**: your messages right, assistant left, error bubbles, a
  "thinking" indicator while waiting, auto-scroll, and a **clear** (eraser)
  button.
- **Quick actions**: "Paraphrase" and "Sentiment" chips send the current input
  with the matching prompt-library id.
- **Memo analysis mode**: shows a memo picker (file + code memos with search
  and checkboxes); the selected memos are sent with the chat request.
- Enter sends, Shift+Enter is a newline. A warning banner explains when the
  assistant is disabled.

### Search

- **Semantic search** over the project's text sources using the AI embedding
  index: a query input + Search; results list file name, score and a text
  excerpt; clicking a result opens the source in the coder.

### Settings (same pane family)

The AI **configuration** itself lives in the Settings pane (provider, models,
API base/key, MCP permissions, service status check, semantic index
build/delete, pseudonyms) — see [settings.md](settings.md).

### MCP

The AI backend exposes a JSON-RPC 2.0 endpoint for tool access; the permission
level (read / write / full) is configured in Settings.

## High-level logic

- Chat requests run as plain request/response calls (no streaming); context is
  attached server-side per mode (memos, text, code details).
- **Semantic search** needs the persistent embedding index, built per project
  from its text sources; "Build / Rebuild" indexes everything, and search
  returns nearest neighbours with scores.
- MCP lets external AI tooling query and (per permissions) modify the project
  through the same backend.
