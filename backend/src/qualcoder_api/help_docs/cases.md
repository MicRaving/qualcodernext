# Cases & Mixed-Methods Attributes

[← Back to Documentation Hub](README.md)

This guide covers **Cases** (study units such as individuals, organizations, schools, or sites) and **Attributes** (structured quantitative/qualitative variables) for mixed-methods analysis in QCnext.

---

## Table of Contents
- [Overview & Concept](#overview--concept)
- [Case Management Layout](#case-management-layout)
- [Managing Attributes & Value Labels](#managing-attributes--value-labels)
- [Linking Files & Spans to Cases](#linking-files--spans-to-cases)
- [Mixed-Methods Integration](#mixed-methods-integration)

---

## Overview & Concept

In qualitative research, documents often represent specific entities: an interview transcript belongs to a specific respondent, field notes describe a particular school, or company reports represent distinct organizations.

In QCnext:
- A **Case** represents a study entity (e.g., *Participant P01*, *Lincoln High School*, *Company Alpha*).
- **Files** (or specific passage spans) are linked to cases.
- **Attributes** are structured variables attached to cases (or files)—such as age, gender, role, experimental group, survey score, or location.

Structuring your data into cases and attributes allows you to compare coding patterns across demographic groups or correlate qualitative themes with quantitative variables in the **Statistics Report**.

---

## Case Management Layout

Access the Cases workspace by clicking **Cases** in the ribbon.

![Cases Workspace](screenshots/cases.jpg)

### Interface Layout

- **Left Bar**: The case directory with real-time search matching case names and memos. Includes an **Add Case** button.
- **Center View**: Displays the selected case's details:
  - **Header**: Case name, creator, and creation timestamp.
  - **Case Memo**: Dedicated rich memo editor for case summaries or participant notes.
  - **Attribute Editor**: Variable grid for inspecting and modifying attribute values for this case.
  - **Member Files**: List of files linked to this case, with single-click linking/unlinking controls.
- **Right Bar**: The Inspector showing entity details and summary counts.

---

## Managing Attributes & Value Labels

Attributes define structured metadata across cases or files.

### Adding & Configuring Attribute Types

1. In the Case Details view, click **Add Attribute Type**.
2. Specify the attribute **Name** (e.g., `Age Group`, `Site Type`, `Treatment Arm`).
3. Define **Value Labels** (optional):
   - Map raw stored values to human-readable labels (e.g., `1 → High School`, `2 → University`).
   - When value labels are defined, the attribute field renders as an intuitive dropdown menu across all cases while still preserving custom text entry options.
4. **Data Types**: Supports text, numeric scales, dates, and categorical variables.

---

## Linking Files & Spans to Cases

Cases connect to qualitative material in two ways:

### 1. Whole File Linking
Link entire files (e.g., `P01_Interview.docx`, `P01_Demographics.csv`) to a case:
- **In Cases View**: Use the **Link Files** dropdown in the case details panel.
- **In File Manager**: Right-click any file row and select **Assign to Case…**.

### 2. File Span Linking
If a single transcript contains dialogue from multiple participants (e.g., a focus group transcript), you can assign specific character ranges or sections within the file to distinct cases.

---

## Mixed-Methods Integration

Setting up cases and attributes unlocks powerful mixed-methods reports in the Analysis section (see [Analysis Guide](analysis-and-reports.md)):

- **Crosstabs & Chi-Square**: Test whether code frequencies differ significantly across attribute categories (e.g., comparing themes between *Control* vs. *Treatment* groups).
- **Group Comparisons (Mann-Whitney U)**: Evaluate differences in code density across numeric attribute scales.
- **Stacked Attribute Charts**: Visualize coding distribution broken down by demographic variables.

---

[← Back to Documentation Hub](README.md)
