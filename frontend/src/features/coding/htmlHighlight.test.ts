import { describe, expect, it } from "vitest";
import {
  MAX_HIGHLIGHTS,
  buildHighlights,
  collapseWhitespace,
  decodeHtmlEntities,
  htmlToViewText,
  injectHighlightScript,
  qcFindMatches,
  stripPageScripts,
  type QcCodingPayload,
} from "@/features/coding/htmlHighlight";

const SCRIPT = "<script>QC</script>";

const payload = (seltext: string): QcCodingPayload => ({ seltext, color: null, name: "" });

describe("stripPageScripts", () => {
  it("removes script blocks", () => {
    expect(stripPageScripts("<p>hi</p><script>alert(1)</script><p>there</p>")).toBe(
      "<p>hi</p><p>there</p>",
    );
  });

  it("removes unterminated script blocks (truncated snapshots must not keep a live script)", () => {
    expect(stripPageScripts("<p>a</p><script>var x = 1")).toBe("<p>a</p>");
  });

  it("does not end a script block at an escaped <\\/script> inside a JS string", () => {
    expect(stripPageScripts('<script>document.write("<\\/script>")</script><p>ok</p>')).toBe(
      "<p>ok</p>",
    );
  });

  it("ignores script text inside HTML comments", () => {
    const html = "<!-- <script>alert(1)</script> --><p>x</p>";
    expect(stripPageScripts(html)).toBe(html);
  });

  it("does not treat <script> inside an attribute value as a block", () => {
    const html = '<div data-x="<script>nope</script>">t</div>';
    expect(stripPageScripts(html)).toBe(html);
  });

  it("strips on* handlers (quoted, unquoted, any case)", () => {
    expect(
      stripPageScripts(`<img src="x.png" onerror="alert(1)" onclick='go()' OnLoad=evil>`),
    ).toBe(`<img src="x.png">`);
  });

  it("keeps attribute values that merely look like handlers", () => {
    expect(stripPageScripts(`<a title="onclick=foo" href="#x">t</a>`)).toBe(
      `<a title="onclick=foo" href="#x">t</a>`,
    );
  });

  it("does not strip on* lookalikes inside page text", () => {
    expect(stripPageScripts("<p>read onclick=here</p>")).toBe("<p>read onclick=here</p>");
  });

  it("strips javascript: URLs from navigable attributes", () => {
    expect(stripPageScripts('<a href="javascript:alert(1)">x</a>')).toBe("<a>x</a>");
    expect(stripPageScripts("<a HREF=JAVASCRIPT:foo>x</a>")).toBe("<a>x</a>");
  });

  it("keeps ordinary URLs", () => {
    expect(stripPageScripts('<a href="https://example.org">x</a>')).toBe(
      '<a href="https://example.org">x</a>',
    );
  });

  it("keeps style blocks (CSS is inert) and does not mistake <script> inside them", () => {
    const html = '<style>.x{content:"<script>"}</style><p>y</p>';
    expect(stripPageScripts(html)).toBe(html);
  });

  it("keeps the doctype and regular markup byte-for-byte", () => {
    const html = "<!DOCTYPE html><html><body>hi</body></html>";
    expect(stripPageScripts(html)).toBe(html);
  });
});

describe("injectHighlightScript", () => {
  it("injects before the real </body>", () => {
    expect(injectHighlightScript("<html><body><p>x</p></body></html>", SCRIPT)).toBe(
      "<html><body><p>x</p><script>QC</script></body></html>",
    );
  });

  it("never injects inside a comment (a </body> in a comment must not swallow the script)", () => {
    expect(injectHighlightScript("<!-- </body> --><p>x</p></body>", SCRIPT)).toBe(
      "<!-- </body> --><p>x</p><script>QC</script></body>",
    );
  });

  it("ignores </body> text inside style content", () => {
    expect(injectHighlightScript('<style>x{content:"</body>"}</style><p>y</p></body>', SCRIPT)).toBe(
      '<style>x{content:"</body>"}</style><p>y</p><script>QC</script></body>',
    );
  });

  it("appends at the end when the document has no </body>", () => {
    expect(injectHighlightScript("<p>x</p>", SCRIPT)).toBe("<p>x</p><script>QC</script>");
  });
});

describe("decodeHtmlEntities / collapseWhitespace", () => {
  it("decodes named, decimal and hex references", () => {
    expect(decodeHtmlEntities("Tom &amp; Jerry &mdash; &#39;x&#39; &#x41;")).toBe("Tom & Jerry — 'x' A");
  });

  it("keeps unknown entities as-is", () => {
    expect(decodeHtmlEntities("&notreal; &amp;")).toBe("&notreal; &");
  });

  it("collapses whitespace runs (incl. NBSP) and trims", () => {
    expect(collapseWhitespace("  a\n b\t c\u00A0 d  ")).toBe("a b c d");
  });
});

describe("htmlToViewText", () => {
  it("decodes entities and collapses whitespace", () => {
    expect(htmlToViewText("<p>Tom &amp; Jerry &mdash; ok</p>")).toBe("Tom & Jerry — ok");
    expect(htmlToViewText("<p>a &#39;b&#39; &#x41;</p>")).toBe("a 'b' A");
  });

  it("joins inline text and keeps block boundaries zero-width (mirrors the DOM)", () => {
    expect(htmlToViewText("<p>Hello</p><p>world</p>")).toBe("Helloworld");
  });

  it("keeps inter-tag whitespace (it is a text node in the DOM)", () => {
    expect(htmlToViewText("<p>Hello</p>\n<p>world</p>")).toBe("Hello world");
  });

  it("drops head/script/style/noscript/template content", () => {
    expect(
      htmlToViewText(
        "<head><title>t</title></head><body><script>var x=1</script><style>a{}</style>hi<noscript>no</noscript></body>",
      ),
    ).toBe("hi");
  });

  it("drops code/pre content (segments are never anchored there)", () => {
    expect(htmlToViewText("<p>keep</p><pre>  raw\n text </pre>")).toBe("keep");
  });

  it("treats a bare < in text as text", () => {
    expect(htmlToViewText("<p>1 < 2 and 3</p>")).toBe("1 < 2 and 3");
  });
});

describe("qcFindMatches", () => {
  it("matches collapsed whitespace", () => {
    const text = collapseWhitespace("The  quick\n brown fox");
    expect(qcFindMatches(text, ["The quick brown"], 100)).toEqual([
      { seg: 0, start: 0, len: 15, mode: "collapsed" },
    ]);
  });

  it("falls back to whitespace-free matching across element boundaries", () => {
    // <p>Hello</p><p>world</p> -> DOM text "Helloworld"; the backend fulltext
    // has "Hello\nworld".
    expect(qcFindMatches("Helloworld", ["Hello\nworld"], 100)).toEqual([
      { seg: 0, start: 0, len: 10, mode: "stripped" },
    ]);
  });

  it("matches NBSP-containing text after collapsing", () => {
    const text = collapseWhitespace("Tom\u00A0Jerry");
    expect(qcFindMatches(text, ["Tom Jerry"], 100)).toEqual([
      { seg: 0, start: 0, len: 9, mode: "collapsed" },
    ]);
  });

  it("uses the 40-char prefix when the tail diverges", () => {
    const prefix = "abcdefghijklmnopqrstuvwxyz0123456789abcd"; // 40 chars
    const text = `q ${prefix} gone`;
    expect(qcFindMatches(text, [`${prefix}ZZ`], 100)).toEqual([
      { seg: 0, start: 2, len: 40, mode: "collapsed" },
    ]);
  });

  it("skips empty and whitespace-only segments", () => {
    expect(qcFindMatches("abc", ["", "   "], 100)).toEqual([]);
  });

  it("dedupes segments matching the same position", () => {
    expect(qcFindMatches("abc def", ["abc", "abc"], 100)).toHaveLength(1);
  });

  it("caps the number of marked segments", () => {
    const text = "w0 w1 w2 w3 w4 w5 w6 w7 w8 w9 w10 w11";
    const segs = ["w0", "w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8", "w9", "w10", "w11"];
    const hits = qcFindMatches(text, segs, 3);
    expect(hits).toHaveLength(3);
    expect(hits.map((h) => h.seg)).toEqual([0, 1, 2]);
  });

  it("round-trips through its own source (the iframe runs this exact code)", () => {
    const Core = new Function(`return ${qcFindMatches.toString()}`)() as typeof qcFindMatches;
    const text = "Helloworld";
    const segs = ["Hello\nworld", "world", "zzz", "", "  "];
    const max = 10;
    expect(Core(text, segs, max)).toEqual(qcFindMatches(text, segs, max));
  });

  it("core source is safe to embed in a script tag", () => {
    expect(qcFindMatches.toString().startsWith("function qcFindMatches")).toBe(true);
    expect(qcFindMatches.toString()).not.toContain("</script");
  });
});

describe("buildHighlights", () => {
  it("finds segments through the full pipeline (whitespace + entities + block boundaries)", () => {
    const html =
      "<html><head><title>x</title></head><body><p>Tom &amp; Jerry</p><p>are best friends</p></body></html>";
    const hits = buildHighlights(html, [payload("Tom & Jerry\nare best")]);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ seg: 0, start: 0, len: 16, mode: "stripped" });
  });

  it("returns positions in view-text coordinates", () => {
    const html = "<p>alpha beta</p><p>gamma</p>";
    const hits = buildHighlights(html, [payload("beta\ngamma")]);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ seg: 0, start: 5, len: 9, mode: "stripped" });
  });

  it("matches entity-heavy and NBSP text whitespace-insensitively", () => {
    const html = "<p>Hello&nbsp;world &amp; beyond</p>";
    const hits = buildHighlights(html, [payload("Hello world & beyond")]);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ seg: 0, start: 0, mode: "collapsed" });
  });

  it("finds nothing when the segment is not in the page", () => {
    expect(buildHighlights("<p>nothing here</p>", [payload("missing text")])).toEqual([]);
  });

  it("finds nothing when the only occurrence is inside code/pre", () => {
    expect(buildHighlights("<p>keep me</p><pre>hidden text</pre>", [payload("hidden text")])).toEqual(
      [],
    );
  });

  it("respects the mark cap", () => {
    const html = "<p>" + Array.from({ length: MAX_HIGHLIGHTS + 20 }, (_, i) => `w${i}`).join(" ") + "</p>";
    const codings = Array.from({ length: MAX_HIGHLIGHTS + 20 }, (_, i) => payload(`w${i}`));
    expect(buildHighlights(html, codings)).toHaveLength(MAX_HIGHLIGHTS);
  });
});
