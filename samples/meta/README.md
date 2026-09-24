# Meta-analysis sample project

A small, ready-to-open QCnext project for testing the Meta-analysis workspace.

Open **`samples/meta/meta-sample.qda`** in QCnext (or copy it anywhere first).

It contains 10 search hits (6 included, 4 excluded for the four criteria), four
inclusion criteria, one role-based coding scheme, screening verdicts from two coders
(with a couple of deliberate disagreements for the Agreement dialog), six coded
extractions with descriptives-based effect sizes across three outcome domains, and a
PDF per included study.

Also here:

- `imports/search_results.xml` / `.ris` / `.csv` — the same search results in three
  formats, for testing the Import labeler.
- `scheme.json` / `criteria.json` — the scheme and criteria, for reference/reuse.

Regenerate everything with:

```
backend/.venv/Scripts/python.exe scripts/make-meta-sample.py
```
