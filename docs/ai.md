# AI — assistant chat, semantic search, settings, MCP

The AI assistant as a toggleable right-bar pane with a Chat / Search tab
toggle. Requires the AI feature enabled and configured (see settings.md).

## How to reach it

Ribbon → AI (sparkles icon, right side). Toggles the right-bar pane; the
center view stays whatever it showed.

## Layout slots used

- Right bar only: `AiView` (LeftBar `borderSide="l"`, wide) with a BarHeader
  holding the mode/prompt selects and the Chat/Search tab toggle.
- Center/left bar: unchanged.

## Features

### Chat (`AiChatPanel`)
- **Chat modes** (`AI_MODES`): general, help, topic exploration, code
  analysis, text analysis, memo analysis.
- **Prompt library**: a second select lists the prompts registered for the
  current mode (from `GET /ai/prompts`); picking one overrides the mode's
  default prompt for the next message.
- **Message thread**: user bubbles right, assistant left, error bubbles,
  "thinking" indicator while waiting, auto-scroll, clear (eraser) button.
- **Quick actions**: "Paraphrase" and "Sentiment" chips send the current
  input text with the matching prompt-library id.
- **Memo analysis mode**: shows a memo picker (file + code memos with
  search and checkboxes); the selected memos are sent with the chat request
  (`memo_ids`).
- Enter sends; Shift+Enter is a newline. A warning banner explains when the
  assistant is disabled.

### Search (`AiSearchPanel`)
- **Semantic search** over project text sources via the AI embedding index:
  query input + Search; results list file name, score and a text excerpt;
  clicking a result opens the source in the coder.

### Settings (same pane family)
The AI configuration itself lives in the Settings pane (provider, models,
API base/key, MCP permissions, service status check, semantic index
build/delete, pseudonyms) — see settings.md.

### MCP
The AI backend exposes `POST /ai/mcp` for tool access; the permission level
(read / write / full) is configured in Settings.

## API endpoints used

- `GET /ai/status`, `GET /ai/models`, `PUT /ai/settings`, `GET /ai/prompts`
- `POST /ai/chat` (also with `memo_ids`), `POST /ai/search`
- `GET /ai/index`, `POST /ai/index`, `DELETE /ai/index`, `POST /ai/mcp`
- `GET /memos` (memo picker data)

## Screenshot:

(to be inserted)
