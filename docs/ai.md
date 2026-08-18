# AI Assistant \& Settings

[← Back to Documentation Hub](README.md)

!!!! This section will be reworked to resemble the current state of the AI sidebar!

QCnext integrates both privacy-focused **Local LLMs** (Ollama, LM Studio) and **Cloud AI Providers** (Gemini, OpenAI GPT, Anthropic Claude, custom endpoints) to support qualitative coding, topic discovery, and semantic search.

Access AI Configuration in **Settings → AI Assistant**.

### Setup Steps

1. **Enable AI**: Toggle the **Enable AI Assistant** switch.
2. **Select Provider**: Choose your preferred provider (Ollama and LM Studio auto-probe local endpoints; unreachable options display an `unreachable` indicator).
3. **Select Model**: Choose a model from the list (e.g., `qwen3.8-27b`, `mistral`, `gemini-3.7-flash`).
4. **API Credentials**: Most cloud providers require entering your API Key, optional for local providers.
5. **Check Service**: Click **Check** to verify connectivity with the provider endpoint.
6. **Configure Permissions**:

   * **Read**: Read-only access to codes, files, cases, and report summaries.
   * **Write**: Allows AI tools to create proposed codes, memos, or scratchpad items.
   * **Full**: Full project access.

\---

## AI Assistant

Toggle the AI assistant pane by clicking ✨ **AI** in the ribbon. You can decide which data from the project you want to expose to the LLMs - be aware that this may increase token consumptions and context size.

* **Chat Modes**:

  * **General / Help**: Ask questions about QCnext features or qualitative methodologies.
  * **Topic Exploration**: Brainstorm potential themes and sub-themes from document excerpts.
  * **Code Analysis**: Request AI evaluation of code definitions and coding consistency.
  * **Text Analysis**: Summarize long interview transcripts or analyze participant discourse.
  * **Memo Analysis**: Select specific code/file memos to include as grounded context for AI synthesis (may be merged into topic exploration in future releases).
  * **Semantic Search**: locates conceptually relevant passages across your qualitative material based on meaning rather than exact word matches (e.g., `"passages expressing job burnout"` or `"frustration with bureaucratic processes"`). You need to build a vector index in the settings first.
* **Prompt Library**: Preset system prompts tailored for qualitative research workflows.
* **Quick Action Chips**:

  * **Paraphrase**: Generates concise summaries of selected passages.
  * **Sentiment**: Scores emotional tone and underlying sentiment.

\---

[← Back to Documentation Hub](README.md)

