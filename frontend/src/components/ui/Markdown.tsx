/**
 * Markdown — a deliberately small, dependency-free markdown renderer.
 *
 * Shared by the in-app help docs and the AI chat (assistant replies). Renders
 * headings, paragraphs, horizontal rules, tables, fenced code, bullet/numbered
 * lists, inline code, bold/italic emphasis, and images/links as plain text —
 * never as raw HTML, so model output and bundled docs are safe to render
 * without sanitization. Block elements accept a ``size`` ("xs" for help docs,
 * "sm" for chat bubbles).
 */
import { type ReactNode } from "react";

interface MarkdownProps {
  text: string;
  size?: "xs" | "sm";
}

const SIZE: Record<NonNullable<MarkdownProps["size"]>, string> = {
  xs: "text-xs",
  sm: "text-sm",
};

export function Markdown({ text, size = "xs" }: MarkdownProps) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  const s = SIZE[size];
  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("# ")) {
      blocks.push(
        <h2 key={key++} className={`${s} mb-1 font-semibold text-text-primary`}>
          {line.slice(2)}
        </h2>,
      );
      i += 1;
      continue;
    }
    if (line.startsWith("## ")) {
      blocks.push(
        <h3 key={key++} className={`${s} mb-1 mt-2 font-semibold text-text-primary`}>
          {line.slice(3)}
        </h3>,
      );
      i += 1;
      continue;
    }
    if (line.startsWith("### ")) {
      blocks.push(
        <h4 key={key++} className={`${s} mb-1 mt-2 font-medium text-text-primary`}>
          {line.slice(4)}
        </h4>,
      );
      i += 1;
      continue;
    }
    // Horizontal rule: `---` (or `***` / `___`).
    if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) {
      blocks.push(<hr key={key++} className="my-2 border-border" />);
      i += 1;
      continue;
    }
    // Markdown table: consecutive lines starting with `|` (a leading
    // separator row `|-|-|-|` is skipped as a divider).
    if (/^\s*\|/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) {
        buf.push(lines[i]);
        i += 1;
      }
      const body = buf.filter((l) => !/^\s*\|[\s:-]+\|/.test(l));
      const rows = body
        .map((l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim()))
        .filter((cells) => cells.some((c) => c !== ""));
      if (rows.length > 0) {
        blocks.push(
          <table key={key++} className="my-2 w-full border-collapse text-xs">
            <tbody>
              {rows.map((cells, ri) => (
                <tr key={ri} className="border-b border-border">
                  {cells.map((cell, ci) => (
                    <td
                      key={ci}
                      className="border border-border px-2 py-1 align-top text-text-secondary"
                    >
                      {inline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>,
        );
      }
      continue;
    }
    if (line.startsWith("```")) {
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith("```")) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1;
      blocks.push(
        <pre
          key={key++}
          className="my-1 overflow-x-auto whitespace-pre-wrap break-words rounded-sm border border-border bg-bg p-2 text-xs text-text-primary"
        >
          {buf.join("\n")}
        </pre>,
      );
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ul
          key={key++}
          className={`${s} my-1 list-disc space-y-0.5 pl-4 leading-relaxed text-text-secondary`}
        >
          {buf.map((item, j) => (
            <li key={j}>{inline(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ol
          key={key++}
          className={`${s} my-1 list-decimal space-y-0.5 pl-4 leading-relaxed text-text-secondary`}
        >
          {buf.map((item, j) => (
            <li key={j}>{inline(item)}</li>
          ))}
        </ol>,
      );
      continue;
    }
    if (!line.trim()) {
      i += 1;
      continue;
    }
    blocks.push(
      <p key={key++} className={`${s} my-1 leading-relaxed text-text-secondary`}>
        {inline(line)}
      </p>,
    );
    i += 1;
  }
  return <div className="space-y-1">{blocks}</div>;
}

function inline(text: string): ReactNode {
  // Images render as their alt text; links as their label — no raw HTML.
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|!?\[[^\]]*\]\([^)]*\))/g);
  return parts.map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className="rounded-sm bg-bg px-1 text-xs text-accent">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-text-primary">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return (
        <em key={i} className="italic text-text-secondary">
          {part.slice(1, -1)}
        </em>
      );
    }
    if (part.startsWith("[") && part.endsWith(")")) {
      const m = /^!?\[([^\]]*)\]\([^)]*\)$/.exec(part);
      if (m) {
        return (
          <span key={i} className="italic text-text-secondary/70">
            {m[1] || "(image)"}
          </span>
        );
      }
    }
    return <span key={i}>{part}</span>;
  });
}