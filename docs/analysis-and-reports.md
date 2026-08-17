# Analysis, Reports, Statistics & Code Maps Guide

[← Back to Documentation Hub](README.md)

This guide covers the Analysis workspace in QCnext: eleven analytical reports, statistical tools, interrater reliability calculations, publishing capabilities, SQL/R consoles, and the SVG visual code map editor with automated model generators.

---

## Table of Contents
- [Overview of Analysis Workspace](#overview-of-analysis-workspace)
- [The 11 Analytical Reports](#the-11-analytical-reports)
- [Analytical Tools: Codebook, References, SQL & R](#analytical-tools-codebook-references-sql--r)
- [Publishing Reports to Word, Excel & PowerPoint](#publishing-reports-to-word-excel--powerpoint)
- [Graphs & Visual Code Maps](#graphs--visual-code-maps)

---

## Overview of Analysis Workspace

Access Analysis by clicking **Reports** in the ribbon. The left bar organizes available tools into three sections: **Analytical Reports**, **Tools**, and **Graphs**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ANALYSIS ARCHITECTURE                             │
│                                                                             │
│ ┌──────────────────────┐  ┌──────────────────────┐  ┌────────────────────┐ │
│ │ ANALYTICAL REPORTS   │  │ SPECIALIZED TOOLS    │  │ VISUAL CODE MAPS   │ │
│ │ • Frequencies        │  │ • Codebook Exporter  │  │ • SVG Canvas       │ │
│ │ • Segments           │  │ • RIS References     │  │ • 6 Model Gen.     │ │
│ │ • File × Code Heatmap│  │ • Read-Only SQL      │  │ • Node Drag & Drop │ │
│ │ • Code Relations     │  │ • R Script Console   │  │ • Arrow Connectors │ │
│ │ • Interrater Agreement│  └──────────────────────┘  └────────────────────┘ │
│ │ • Text & Corpus      │                                                    │
│ │ • Word Dictionary    │  ┌───────────────────────────────────────────────┐ │
│ │ • Mixed-Methods Stats│  │ PUBLISHING ENGINE                             │ │
│ │ • Summary Grid       │  │ Export formatted .docx / .xlsx / .pptx reports│ │
│ │ • Sentiment Analysis │  └───────────────────────────────────────────────┘ │
│ │ • Document Compare   │                                                    │
│ └──────────────────────┘                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## The 11 Analytical Reports

### 1. Code Frequencies
![Code Frequencies](screenshots/12-reports-code-frequencies.png)
Ranked bar chart and breakdown table displaying usage counts per code and category. Includes cumulative frequency charts (downloadable as PNG) and CSV exports.

### 2. Code Segments
![Code Segments](screenshots/13-reports-code-segments.png)
Flat list of all coded passages in the project, filterable by file, code, category, or coder. Includes coder comparison mode for side-by-side segment auditing.

### 3. File × Code Matrix
![File × Code](screenshots/14-reports-file-code.png)
Matrix table, stacked bar chart, and visual heatmap illustrating code usage across documents or cases. Ideal for identifying which sources contain specific themes.

### 4. Code Relations & Co-Occurrence
![Code Relations](screenshots/15-reports-code-relations.png)
Co-occurrence matrix (Code × Code) displaying how frequently codes overlap within the same document or passage. Includes Crossovers mode to trace thematic transitions.

### 5. Interrater Reliability
![Interrater Reliability](screenshots/16-reports-interrater.png)
Computes statistical agreement across multiple coders:
- **Multi-Coder Agreement**: Calculates **Krippendorff’s alpha ($\alpha$)** across all selected raters.
- **Pairwise Table**: Computes **Cohen’s kappa ($\kappa$)**, Krippendorff’s $\alpha$, and **Gwet’s AC1** coefficient alongside observed percentage agreement.
- **Agreement Cards**: Displays Detailed Both / Only A / Only B / Neither breakdowns per code.

### 6. Text & Corpus
![Text & Corpus](screenshots/17-reports-text-corpus.png)
Four analytical tabs: Word Cloud generator, Exact Coded Passage Match finder, Document Summaries table, and Attribute Value inspector.

### 7. Dictionary Autocode & Frequency
![Dictionary](screenshots/18-reports-dictionary.png)
MAXDictio-style dictionary management. Import term lists, map terms to codes, execute dictionary autocoding across files, and inspect document-term frequency matrices.

### 8. Mixed-Methods Statistics
![Statistics](screenshots/19-reports-stats.png)
Evaluates relationships between qualitative codes and quantitative case attributes:
- **Crosstabs & Chi-Square ($\chi^2$)**: Chi-square tests of independence with degrees of freedom, p-value, and Cramér’s V effect size.
- **Group Comparisons (Mann-Whitney U)**: Non-parametric comparison of numeric attributes between cases with vs. without target codes.

### 9. Summary Table Grid
![Summary Table](screenshots/20-reports-summary-table.png)
Grid displaying Document/Case × Code matrix filled with **coding memos**. Click any cell to edit memos inline.

### 10. Sentiment Analysis
![Sentiment](screenshots/21-reports-sentiment.png)
Analyzes emotional tone across passages using offline VADER lexicon scoring (negative, neutral, positive, compound) or AI-assisted sentiment evaluation.

### 11. Document Comparison
![Document Comparison](screenshots/22-reports-doc-compare.png)
Side-by-side alignment of two text files linked by Longest Common Subsequence (LCS), highlighting code overlays, Dice similarity coefficients, and co-occurrence tables.

---

## Analytical Tools: Codebook, References, SQL & R

### Codebook Tool
![Codebook](screenshots/23-reports-codebook.png)
Generates structured text codebooks with optional code memos. Exportable to `.txt` or `.csv`.

### Bibliographic References
![References](screenshots/24-reports-references.png)
Bibliography manager holding RIS/Zotero reference metadata (authors, year, title). Allows attaching PDF documents directly to reference items.

### Read-Only SQL Query Editor
![SQL Query](screenshots/25-reports-sql.png)
Execute custom read-only `SELECT` queries directly against the project SQLite database. Save and load query templates for advanced data extraction.

### R Script Console
Integrated environment for executing R statistical scripts against project data. Features pre-built script templates (RSQLite matrices, `quanteda` word frequencies, `irr` agreement metrics), background execution, and artifact rendering (stdout, PNG charts, CSV outputs).

---

## Publishing Reports to Word, Excel & PowerPoint

Click **Publish** in the header of supported reports (Frequencies, Segments, Summary Table, Codebook) to export production-ready documents:
- **Word (`.docx`)**: Formatted reports complete with tables, code color swatches, and metadata.
- **Excel (`.xlsx`)**: Structured multi-tab spreadsheets.
- **PowerPoint (`.pptx`)**: Formatted slide decks for executive presentations.

---

## Graphs & Visual Code Maps

The **Graphs** workspace provides an interactive SVG canvas for visual modeling and code mapping.

### SVG Canvas Features
- **Draggable Nodes**: Create nodes representing Codes, Categories, Cases, Files, Memos, or Free Text. Positions auto-save on mouse release.
- **Connector Lines**: Connect nodes with customizable line styles (solid, dashed), arrow directions, and mid-line relation labels.
- **Graph Inspector**: Customize font sizes, colors, node labels, and line attributes in the right bar.

### Automated Model Generators
Click **Models** on the graph toolbar to generate visual graphs automatically:

| Model Generator | Generated Structure |
| :--- | :--- |
| **Category Hierarchy** | Tree structure of categories and codes. |
| **File Hierarchy** | Files with associated cases and applied codes. |
| **File Comparison** | Bipartite graph mapping files to shared codes. |
| **Case Hierarchy** | Cases with associated files and attributes. |
| **Case Comparison** | Bipartite graph mapping cases to applied codes. |
| **Co-Occurrence Network** | Network graph connecting codes based on co-occurrence density. |

---

[← Back to Documentation Hub](README.md)
