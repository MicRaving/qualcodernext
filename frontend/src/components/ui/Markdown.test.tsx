// @vitest-environment jsdom
/**
 * Markdown — the small dependency-free renderer shared by the help docs and
 * the AI chat. Verifies the block/inline element output (never raw HTML).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Markdown } from "@/components/ui/Markdown";

let container: HTMLElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(text: string, size: "xs" | "sm" = "sm") {
  act(() => {
    root.render(<Markdown text={text} size={size} />);
  });
}

describe("Markdown", () => {
  it("renders headings, paragraphs and emphasis", () => {
    render("# Title\n\nSome **bold** and *italic* text.");
    expect(container.querySelector("h2")?.textContent).toBe("Title");
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("em") ?? null).not.toBeNull();
    expect(container.textContent).toContain("Some bold and italic text.");
  });

  it("renders bullet and numbered lists", () => {
    render("- one\n- two\n\n1. first\n2. second");
    expect(container.querySelectorAll("ul li").length).toBe(2);
    expect(container.querySelectorAll("ol li").length).toBe(2);
  });

  it("renders fenced code blocks and inline code", () => {
    render("```js\nconst x = 1;\n```\n\nUse `x` here.");
    expect(container.querySelector("pre")?.textContent).toBe("const x = 1;");
    expect(container.querySelector("code")?.textContent).toBe("x");
  });

  it("renders links and images as plain text (no raw HTML, no anchor)", () => {
    render("[label](https://example.com) and ![alt](img.png)");
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("label");
    expect(container.textContent).toContain("alt");
  });

  it("escapes raw HTML instead of injecting it", () => {
    render("<script>alert(1)</script>");
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });

  it("applies the requested size class", () => {
    render("hello", "xs");
    expect(container.querySelector("p")?.className).toContain("text-xs");
  });
});
