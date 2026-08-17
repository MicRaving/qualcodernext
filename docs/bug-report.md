# Reporting Bugs

The bug reporter is built into the app: capture a **screenshot** of the
current state, annotate it (highlight / redact), and compose a **GitHub
issue** — with the environment context pre-filled. Works with and without an
open project.

## How to reach it

- Ribbon → the **bug icon** (right side, next to Settings).

## What happens

1. QCnext captures a screenshot of the app **before** the composer opens (so
   the dialog never appears in its own picture).
2. The composer opens with two columns:
   - **Issue form**: title, body (seeded with an environment block — app
     version, OS/user agent, last action, last error), labels (plus quick
     pills: bug / enhancement / question), assignee and milestone fields.
   - **Screenshot + paint**: draw on the capture with three brush colors
     (red, yellow, black for redaction), three brush sizes, an eraser, undo,
     clear, reset.
3. **Download screenshot** saves the annotated PNG locally.
4. **Submit / Open browser**:
   - *Without a GitHub token* (default): opens a **pre-filled GitHub
     `issues/new` page** in your system browser — you attach the screenshot
     and finish there.
   - *With a GitHub token* configured: QCnext uploads the annotated screenshot
     through GitHub's attachment endpoint and **creates the issue** via the
     API (labels/assignee/milestone included), showing the issue link.

## High-level logic

The capture is rendered from the live app via html2canvas (with colour-space
fallbacks for the design tokens). If a rendered capture fails, a structured
**text snapshot** (app version, current view, last action, last error,
timestamp) is drawn instead, so a report is never blank. The "last action"
comes from the newest audit-log row, giving maintainers a reproducible context.
