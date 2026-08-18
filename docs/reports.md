# Analysis, Reports \& Statistics

[← Back to Documentation Hub](README.md)

This guide covers the Analysis workspace in QCnext: eleven analytical reports, statistical tools, interrater reliability calculations, publishing capabilities, SQL/R consoles, and the SVG visual code map editor with automated model generators.

\---

## Overview of Analysis Workspace

!\[Code Frequencies](screenshots/reports.jpg)

Access Analysis by clicking **Reports** in the ribbon. The left bar organizes available tools into three sections: **Analytical Reports**, **Tools**, and **Graphs**. In the header of most reports you can click Publish to export to Word, Excel, and PowerPoint formats (experimental).

1. Code Frequencies: Ranked bar chart and breakdown table displaying usage counts per code and category. Includes cumulative frequency charts (downloadable as PNG) and CSV exports.
2. Code Segments: Flat list of all coded passages in the project, filterable by file, code, category, or coder. Includes coder comparison mode for side-by-side segment auditing.
3. File × Code Matrix: Matrix table, stacked bar chart, and visual heatmap illustrating code usage across documents or cases. Ideal for identifying which sources contain specific themes.
4. Code Relations \& Co-Occurrence: Co-occurrence matrix (Code × Code) displaying how frequently codes overlap within the same document or passage. Includes Crossovers mode to trace thematic transitions.
5. Interrater Reliability: Computes statistical agreement across multiple coders (Cohen’s $\\kappa$, Krippendorff’s $\\alpha$, and Gwet’s AC1, and percentage agreement) including details.
6. Text \& Corpus: Four analytical tabs: Word Cloud generator, Exact Coded Passage Match finder, Document Summaries table, and Attribute Value inspector.
7. Dictionary Autocode \& Frequency: MAXDictio-style dictionary management. Import term lists, map terms to codes, execute dictionary autocoding across files, and inspect document-term frequency matrices.
8. Mixed-Methods Statistics: Evaluates relationships between qualitative codes and quantitative case attributes with **Crosstabs \& Chi-Square ($\\chi^2$)** as well as Non-parametric comparison **(Mann-Whitney U)** of numeric attributes between cases with vs. without target codes
9. Summary Table Grid: Grid displaying Document/Case × Code matrix filled with **coding memos**. Click any cell to edit memos inline.
10. Sentiment Analysis: Analyzes emotional tone across passages using offline VADER lexicon scoring (negative, neutral, positive, compound) or AI-assisted sentiment evaluation.
11. Document Comparison: Side-by-side alignment of two text files linked by Longest Common Subsequence (LCS), highlighting code overlays, Dice similarity coefficients, and co-occurrence tables.

\---

## Analytical Tools: Codebook, References, SQL \& R

### Codebook Tool

Generates structured text codebooks with optional code memos. Exportable to `.txt` or `.csv`.

### Bibliographic References

Bibliography manager holding RIS/Zotero reference metadata (authors, year, title). Allows attaching PDF documents directly to reference items.

### Read-Only SQL Query Editor

!\[SQL Query](screenshots/sql.jpg)
Execute custom read-only `SELECT` queries directly against the project SQLite database. Save and load query templates for advanced data extraction.

### R Script Console

Integrated environment for executing R statistical scripts against project data. Features pre-built script templates (RSQLite matrices, `quanteda` word frequencies, `irr` agreement metrics), background execution, and artifact rendering (stdout, PNG charts, CSV outputs).

\---

## Graphs \& Visual Code Maps

The **Graphs** workspace provides an interactive SVG canvas for visual modeling and code mapping.

### SVG Canvas Features

* **Draggable Nodes**: Create nodes representing Codes, Categories, Cases, Files, Memos, or Free Text. Positions auto-save on mouse release.
* **Connector Lines**: Connect nodes with customizable line styles (solid, dashed), arrow directions, and mid-line relation labels.
* **Graph Inspector**: Customize font sizes, colors, node labels, and line attributes in the right bar.

### Automated Model Generators

Click **Models** on the graph toolbar to generate visual graphs automatically:

|Model Generator|Generated Structure|
|-|-|
|**Category Hierarchy**|Tree structure of categories and codes.|
|**File Hierarchy**|Files with associated cases and applied codes.|
|**File Comparison**|Bipartite graph mapping files to shared codes.|
|**Case Hierarchy**|Cases with associated files and attributes.|
|**Case Comparison**|Bipartite graph mapping cases to applied codes.|
|**Co-Occurrence Network**|Network graph connecting codes based on co-occurrence density.|

\---

[← Back to Documentation Hub](README.md)

