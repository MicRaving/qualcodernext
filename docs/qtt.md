# Crafter — the Questions-Themes-Theories (QTT) workspace

**Crafter** is a MAXQDA-style analysis workspace built on the classic
**QTT (Questions-Themes-Theories)** approach. It provides **worksheets**: each
one collects your insights — evidence quotes, notes, chart references and
links — under themed sections, guided by a research question, purpose and
framework. A worksheet is where you start turning coded data into an argument.

![Crafter (QTT)](screenshots/11-qtt.png)

## How to reach it

- Ribbon → **Crafter**.

## The layout on this screen

- **Left bar**: the worksheet list (name, kind badge, item count).
- **Center**: the selected worksheet — an info block (research question,
  purpose, framework) plus the section cards.
- **Right bar**: the Inspector.

## Features

### Worksheets

- **Create**: Add opens a dialog with a name and a **template kind**:
  - **Qualitative** — single-column sections (seeded with a default
    "Insights" section).
  - **Mixed** — a two-column grid seeded with the **14 Creswell
    mixed-methods steps** (Research Questions, Qualitative/Quantitative Data
    Collection & Analysis, Joint Display Planning, Data Integration,
    Meta-Inferences, Validity & Reliability, Limitations, Reporting, Ethical
    Considerations, Reflexivity, Conclusions & Implications).
- **List**: rows show name, kind badge (Qual / Mixed) and item count; inline
  rename; context menu (Details / Rename / Delete).

### The worksheet editor

- **Info block**: research question, purpose and framework editors (Save
  enabled when dirty; drafts survive reloads).
- **Section cards**: each card has a header (name + item-count badge), a
  "new note" input (Enter or + to add), and the item list.

### Items (the content of a worksheet)

| Kind | What it is | Action |
|---|---|---|
| **Segment** | A quote from your data (with a source chip) | Clicking it jumps into the coder and flashes the passage |
| **Note** | Free text | — |
| **Chart** | A reference to a report (report name + parameters) | — |
| **Link** | An external URL | Opens in a new tab |

Each item has a section dropdown (move it to another section of the same
sheet) and a delete button.

### Send-to-QTT from the coders

The text coder's selection toolbar offers **Send to QTT** → pick a worksheet →
the selected passage is stored as a segment item (with the source text). An
open Crafter workspace refreshes automatically when something arrives.

## High-level logic

A worksheet is defined by its research question, purpose and framework; the
sections are a fixed scaffold (template-dependent). Items are typed payloads
attached to a section. **Segment items keep a live reference to the source
passage**, so the worksheet is not a copy — it is a curated index into your
coded data: click a quote and you are back in the document. This is the
bridge between "I coded everything" and "here is my analysis".
