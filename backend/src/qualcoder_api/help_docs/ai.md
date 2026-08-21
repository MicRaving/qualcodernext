# AI Assistant \& Settings

[← Back to Documentation Hub](README.md)

QCnext integrates both privacy-focused Local LLMs (Ollama, LM Studio) and Cloud AI Providers (Gemini, OpenAI GPT, Anthropic Claude, custom endpoints) to support qualitative coding and topic discovery.

The AI must be configured in Settings → AI Assistant first.

### Chat

* You can chat with the LLM in a normal conversation; **Enter** sends, **Shift+Enter** inserts a newline.
* **Context pickers** (Memos / Codes / Files) above the composer decide which project data is handed to the model (memos, codes, files or a mix). The strip has an **All** toggle (on by default) that exposes every memos, code and file at once; turn it off and pick individual items to narrow the context. The whole selector can be **collapsed/expanded** with the arrow in its `Mode:` header. Note that exposing data increases token consumption and context size.
* **Markdown**: the assistant's replies are rendered as Markdown (headings, lists, tables, code, bold/italic) so its answers are easy to read.
* **Tools** toggle (default on): the assistant can call the project's MCP tools during the conversation instead of just replying with text. It may read the code tree, sources, cases and codings to ground its answers, and — when the **MCP permissions** setting allows it — create/rename/delete codes, categories, codings, cases and attribute values. Every executed tool is shown as a small *Tools used* line under the answer; every write is **audit-logged**.
* **Confirm writes** toggle (default on): before the assistant actually changes project data, the chat pauses and shows the proposed actions with **Approve** / **Reject** buttons. Turn it off to let the model write directly.
* The **MCP permissions** select (bottom of the pane) switches the access level on the fly — *Read only*, *Read + write* or *Full access* — the same setting as in Settings. Read-only tool calls are listed as *Tools used* lines without an approval tag; only writes that go through Approve/Reject carry the *Approved* / *Rejected* tag.
* Backends that do not support tool calling fall back to a plain text answer automatically.
* The same tool set is also exposed to external tooling over the built-in **MCP endpoint** (`POST /ai/mcp`, JSON-RPC 2.0): code tree, sources and their text, cases, codings, text search, project summary — plus the write tools listed above when permissions allow. Every write is **audit-logged** and undoable via History.

### Instruction templates

The dropdown in the pane's top bar picks the instruction prompts that shapes the answer. Templates are grouped **Analysis**, **Specialized** and **My templates** (your own):

* **Analysis**: Interactive Brainstorming, Compare, Criticize, Paraphrase, Saturation Check, Summarize, Identify Unexpected, Sentiment.
* **Specialized**: Code Comparison, **Reconstructive SRP** (Lieder/Schäffer, 2024) and **Theme Generation** (Friese, 2024).
* **My templates**: The **document** button (top bar) opens the **Instruction templates** editor with two tabs:
  * **Personas** — the system prompt of every chat mode (General, Help, Topic exploration, Codes, Texts, Memos, Sentiment) can be edited and **saved for all projects**; **Reset to default** restores the shipped text. The **wrapping prompt** (the "be short and concise" directive appended to every turn) is edited here too.
  * **Templates** — every editable template in one list. **Built-in** templates are edited via an app-wide override (**Reset to default** restores the shipped instructions); **App** templates are stored in your user settings and are available in every project; **Project** templates belong to the current project and can be copied to the app store with **Save globally**.

### Chat history

The **hourglass** button (top bar) opens the history menu:

* **New chat** starts a fresh conversation.
* Each saved chat can be **renamed** (pencil) and **deleted** (trash).

## Setup (Settings → AI Assistant)

1. **Enable AI**: toggle **Enable AI Assistant**.
2. **Provider**: Ollama, LM Studio, opencode-go, Gemini, GPT, Claude or a custom OpenAI-compatible endpoint. Local providers auto-probe; cloud ones need an API key.
3. **Model**: picked from the live list (provider-filtered, refreshed automatically); type any model name manually when it is not listed.
4. **Check** verifies connectivity with the provider (status dot + probe).
5. **MCP mode**: **Self-contained** (default) or **External server**.
   * *Self-contained* uses QCnext's built-in MCP tools (read code tree, sources, cases, codings; write codes, categories, codings, cases and attributes when MCP permissions allow).
   * *External* connects to a local MCP server via stdio — set the **Server command** (e.g. the path to `qualcoder-mcp`), optional **Arguments** (space-separated), and optional **Environment** variables (one `KEY=value` per line, e.g. `QUALCODER_PROJECT_PATH=/path/to/project.qda`). In external mode the agentic chat uses the external server's own tools and the *Confirm writes* pause is disabled (the external server manages its own write safety).
6. **MCP permissions**: **Read** (default), **Write**, or **Full** — gates what project data the built-in MCP endpoint may hand to the model and whether it may write. Only applies in Self-contained mode; in External mode the permission selector is replaced by an "External MCP" indicator.

## Limitations

* The conversation is stored in the project DB; switching projects shows that project's own sessions.
* A reply can take a long time on local backends (model load + generation) — the request timeout is generous (up to 5 minutes).
* An agentic turn is capped at a bounded number of model↔tool round trips so a misbehaving model cannot loop forever.
* A paused "Confirm writes" approval is held in memory — restarting the backend before answering discards it.

[← Back to Documentation Hub](README.md)