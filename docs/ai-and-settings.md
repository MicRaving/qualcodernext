# AI Assistant \& Settings Guide

[← Back to Documentation Hub](README.md)

This guide covers configuring artificial intelligence (Local and Cloud LLMs), using the AI Assistant, building semantic search vector indices, exposing Model Context Protocol (MCP) endpoints, and customizing application settings.

\---

## Table of Contents

* [Configuring AI Providers](#configuring-ai-providers)
* [AI Assistant \& Prompt Library](#ai-assistant--prompt-library)
* [Semantic Vector Search](#semantic-vector-search)
* [Model Context Protocol (MCP) Endpoint](#model-context-protocol-mcp-endpoint)
* [Application Settings \& Preferences](#application-settings--preferences)

\---

## Configuring AI Providers

QCnext integrates both privacy-focused **Local LLMs** (Ollama, LM Studio) and **Cloud AI Providers** (Gemini, OpenAI GPT, Anthropic Claude, custom endpoints) to support qualitative coding, topic discovery, and semantic search.

Access AI Configuration in **Settings → AI Assistant** or via the AI right-bar pane.

### Setup Steps

1. **Enable AI**: Toggle the **Enable AI Assistant** switch.
2. **Select Provider**: Choose your preferred provider (Ollama and LM Studio auto-probe local endpoints; unreachable options display an `unreachable` indicator).
3. **Select Model**: Choose an active model from the dynamically populated dropdown list (e.g., `llama3.2`, `mistral`, `gemini-1.5-pro`, `gpt-4o`).
4. **API Credentials**: Enter your API Key (stored securely in machine settings; optional for local providers).
5. **Check Service**: Click **Check** to verify connectivity with the provider endpoint.

\---

## AI Assistant \& Prompt Library

Toggle the AI assistant pane by clicking ✨ **AI** in the ribbon.

### Features \& Chat Modes

* **Chat Modes**:

  * **General / Help**: Ask questions about QCnext features or qualitative methodologies.
  * **Topic Exploration**: Brainstorm potential themes and sub-themes from document excerpts.
  * **Code Analysis**: Request AI evaluation of code definitions and coding consistency.
  * **Text Analysis**: Summarize long interview transcripts or analyze participant discourse.
  * **Memo Analysis**: Select specific code/file memos to include as grounded context for AI synthesis.
* **Prompt Library**: Preset system prompts tailored for qualitative research workflows.
* **Quick Action Chips**:

  * **Paraphrase**: Generates concise summaries of selected passages.
  * **Sentiment**: Scores emotional tone and underlying sentiment.

\---

## Semantic Vector Search

Unlike traditional keyword search, **Semantic Search** locates conceptually relevant passages across your qualitative material based on meaning rather than exact word matches.

### How to Use Semantic Search

1. **Build Vector Index**: In Settings, click **Build / Rebuild Semantic Index**. QCnext chunk-indexes all text sources in your project using vector embeddings.
2. **Querying**: Switch to the **Search** tab in the AI pane and enter a natural language query (e.g., `"passages expressing job burnout"` or `"frustration with bureaucratic processes"`).
3. **Results**: Displays matching document excerpts ranked by cosine similarity score. Clicking any result opens the document in the active coder at the exact position.

> \[!NOTE]
> \*\*Privacy First\*\*: When using local providers (Ollama / LM Studio), semantic embedding indexing and search queries run 100% locally on your machine without transmitting project data online.

\---

## Model Context Protocol (MCP) Endpoint

QCnext implements a **JSON-RPC 2.0 Model Context Protocol (MCP)** server endpoint, enabling external AI tools and agents (such as Claude Desktop or custom tools) to interact with your qualitative project safely.

* **Configurable Permissions**:

  * **Read**: Read-only access to codes, files, cases, and report summaries.
  * **Write**: Allows AI tools to create proposed codes, memos, or scratchpad items.
  * **Full**: Full project access.

\---

## Application Settings \& Preferences

Access global application configuration by clicking ⚙️ **Settings** in the ribbon.

### Key Settings Sections

* **Appearance**: Switch between **Dark** and **Light** visual themes (defaults to system preference).
* **Language / Locale**: Select UI display language.
* **Accessibility**: Toggle specialized display modes (High Contrast, Screenreader, Large Text, Reduced Motion, Colorblind Friendly).
* **Pseudonym Anonymization**: Define original-to-replacement pseudonym pairs (e.g., `John Doe → Participant\_A`, `Springfield High → School\_1`) for automated quote anonymization when exporting reports.
* **Desktop Auto-Updates**: Configure update checks (Daily, Weekly, Never) and single-click update installation.
* **Project Maintenance**: Toggle automatic database compaction upon project closure.
* **R Environment**: Displays R installation status, version, and binary path for statistical scripts.

\---

[← Back to Documentation Hub](README.md)

