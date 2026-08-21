import { describe, expect, it } from "vitest";
import {
  MAX_HIGHLIGHTS,
  buildHighlightedHtml,
  buildHighlights,
  buildViewModel,
  cleanEmptyLines,
  codingsOverlappingRange,
  collapseWhitespace,
  decodeHtmlEntities,
  htmlToViewText,
  injectHighlightScript,
  locateInFulltext,
  mapViewRangeToSource,
  markStyleFor,
  parseFrameMessage,
  qcFindMatches,
  stripPageScripts,
  viewTextMatchesFulltext,
  type QcCodingPayload,
  type QcSelectionMessage,
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

describe("buildViewModel", () => {
  it("mirrors the iframe DOM walk: whitespace-only text nodes are dropped", () => {
    // The injected script skips nodes whose value is all whitespace
    // (`!nodeValue.trim()`), so inter-tag "\n" must NOT become a space.
    const m = buildViewModel("<p>Hello</p>\n<p>world</p>");
    expect(m.text).toBe("Helloworld");
    expect(m.stripped).toBe("Helloworld");
  });

  it("collapses runs of whitespace across text nodes into one space", () => {
    const m = buildViewModel("<p>a  b </p><p> c</p>");
    expect(m.text).toBe("a b c");
    expect(m.stripped).toBe("abc");
    expect(m.strippedToText).toEqual([0, 2, 4]);
  });

  it("decodes entities and maps each view char back to its source span", () => {
    // <p>Tom &amp; Jerry</p> -> "Tom & Jerry"; the '&' maps to the whole
    // "&amp;" entity range (src [7,12)), single chars map 1:1.
    const html = "<p>Tom &amp; Jerry</p>";
    const m = buildViewModel(html);
    expect(m.text).toBe("Tom & Jerry");
    expect(m.charSpans[0]).toEqual([[3, 4]]);
    expect(m.charSpans[1]).toEqual([[4, 5]]);
    expect(m.charSpans[3]).toEqual([[6, 7]]);
    expect(m.charSpans[4]).toEqual([[7, 12]]);
    expect(m.charSpans[5]).toEqual([[12, 13]]);
  });

  it("maps a collapsed NBSP entity to the whole entity range", () => {
    const m = buildViewModel("<p>Hello&nbsp;world</p>");
    expect(m.text).toBe("Hello world");
    expect(m.charSpans[5]).toEqual([[8, 14]]);
  });

  it("skips inert content: code/pre, textarea, head, script", () => {
    const m = buildViewModel(
      "<head><title>t</title></head><body><p>keep</p><pre>raw</pre>" +
        "<textarea>ta</textarea><script>var x</script></body>",
    );
    expect(m.text).toBe("keep");
  });

  it("auto-closes the head at the first non-head element", () => {
    const m = buildViewModel("<head><title>t</title><p>body text</p>");
    expect(m.text).toBe("body text");
  });

  it("keeps a literal bare < as text with its own span", () => {
    const m = buildViewModel("<p>1 < 2</p>");
    expect(m.text).toBe("1 < 2");
    expect(m.charSpans[2]).toEqual([[5, 6]]);
  });

  it("keeps unknown entities literal, char by char", () => {
    const m = buildViewModel("<p>&notreal;</p>");
    expect(m.text).toBe("&notreal;");
    expect(m.charSpans[0]).toEqual([[3, 4]]);
    expect(m.charSpans[1]).toEqual([[4, 5]]);
  });
});

describe("markStyleFor", () => {
  it("uses the code color when it is a real hex color", () => {
    expect(markStyleFor("#336699")).toContain("rgba(51,102,153,.22)");
    expect(markStyleFor("#336699")).toContain("rgba(51,102,153,.6)");
  });

  it("falls back to the accent for null/invalid colors", () => {
    expect(markStyleFor(null)).toContain("rgba(217,119,6,.22)");
    expect(markStyleFor("#zzz")).toContain("rgba(217,119,6,.22)");
  });

  it("matches the injected script's styleFor output", () => {
    expect(markStyleFor("#336699")).toBe(
      "background:rgba(51,102,153,.22);outline:1px solid rgba(51,102,153,.6);" +
        "border-radius:2px;color:inherit;padding:0",
    );
  });
});

describe("buildHighlightedHtml", () => {
  const countMarks = (html: string): number =>
    (html.match(/<mark class="qc-live-coding"/g) ?? []).length;

  it("embeds a mark around a matched segment with style and title", () => {
    const html = "<p>Tom &amp; Jerry are best friends</p>";
    const out = buildHighlightedHtml(html, [
      { seltext: "Tom & Jerry", color: "#336699", name: "Friends" },
    ]);
    expect(out).toBe(
      '<p><mark class="qc-live-coding" title="Friends" ' +
        'style="background:rgba(51,102,153,.22);outline:1px solid rgba(51,102,153,.6);' +
        'border-radius:2px;color:inherit;padding:0">Tom &amp; Jerry</mark> are best friends</p>',
    );
  });

  it("splits a match across element boundaries into per-node marks", () => {
    const html = "<p>Hello</p><p>world</p>";
    const out = buildHighlightedHtml(html, [{ seltext: "Hello\nworld", color: null, name: "" }]);
    expect(out).toBe("<p><mark class=\"qc-live-coding\" style=\"background:rgba(217,119,6,.22);outline:1px solid rgba(217,119,6,.6);border-radius:2px;color:inherit;padding:0\">Hello</mark></p><p><mark class=\"qc-live-coding\" style=\"background:rgba(217,119,6,.22);outline:1px solid rgba(217,119,6,.6);border-radius:2px;color:inherit;padding:0\">world</mark></p>");
    expect(countMarks(out)).toBe(2);
  });

  it("marks entities and collapsed whitespace inside a single mark", () => {
    const html = "<p>Hello&nbsp;world &amp; beyond</p>";
    const out = buildHighlightedHtml(html, [
      { seltext: "Hello world & beyond", color: null, name: "" },
    ]);
    expect(countMarks(out)).toBe(1);
    expect(out).toContain(">Hello&nbsp;world &amp; beyond</mark>");
  });

  it("never anchors a mark inside code/pre content", () => {
    const html = "<p>keep me</p><pre>hidden text</pre>";
    const out = buildHighlightedHtml(html, [{ seltext: "hidden text", color: null, name: "" }]);
    expect(countMarks(out)).toBe(0);
    expect(out).toBe(html);
  });

  it("does not mark text inside a textarea", () => {
    const html = "<p>keep</p><textarea>ta text</textarea>";
    const out = buildHighlightedHtml(html, [{ seltext: "ta text", color: null, name: "" }]);
    expect(countMarks(out)).toBe(0);
  });

  it("escapes literal < inside marked text so it cannot join the mark tags", () => {
    const html = "<p>1 < 2 and 2 < 3</p>";
    const out = buildHighlightedHtml(html, [{ seltext: "1 < 2", color: null, name: "" }]);
    expect(out).toContain(">1 &lt; 2</mark>");
    expect(out).toContain("and 2 < 3");
    expect(countMarks(out)).toBe(1);
  });

  it("escapes quotes/ampersands in the title attribute", () => {
    const html = "<p>alpha beta</p>";
    const out = buildHighlightedHtml(html, [
      { seltext: "alpha", color: null, name: 'Evil " code & <b>' },
    ]);
    expect(out).toContain('title="Evil &quot; code &amp; &lt;b&gt;"');
  });

  it("never nests marks when two segments overlap", () => {
    const html = "<p>alpha beta gamma</p>";
    const out = buildHighlightedHtml(html, [
      { seltext: "alpha beta", color: null, name: "A" },
      { seltext: "beta gamma", color: null, name: "B" },
    ]);
    // Second match overlaps the first mark's range — it must be dropped.
    expect(countMarks(out)).toBe(1);
    expect(out).not.toMatch(/<mark[^>]*><mark/);
    expect((out.match(/<\/mark>/g) ?? []).length).toBe(countMarks(out));
  });

  it("does not change the page's visible text (parseability invariant)", () => {
    const html =
      "<html><head><title>x</title></head><body>" +
      "<p>Tom &amp; Jerry</p><p>are best friends</p>" +
      "<pre>raw</pre><script>var a=1</script></body></html>";
    const out = buildHighlightedHtml(html, [
      { seltext: "Tom & Jerry\nare best", color: "#ff0000", name: "pair" },
    ]);
    expect(countMarks(out)).toBeGreaterThan(0);
    expect(htmlToViewText(out)).toBe(htmlToViewText(html));
  });

  it("produces balanced markup (every open mark is closed)", () => {
    // "w3 w4" crosses the <p> boundary (no space in the DOM view), so the
    // stripped fallback marks it as two per-node spans; all 3 marks balance.
    const html = "<p>w0 w1 w2 w3</p><p>w4 w5</p>";
    const out = buildHighlightedHtml(html, [
      { seltext: "w1 w2", color: null, name: "" },
      { seltext: "w3 w4", color: null, name: "" },
    ]);
    const opens = countMarks(out);
    const closes = (out.match(/<\/mark>/g) ?? []).length;
    expect(opens).toBe(3);
    expect(closes).toBe(opens);
  });

  it("returns the html untouched when there are no codings or no matches", () => {
    const html = "<p>nothing here</p>";
    expect(buildHighlightedHtml(html, [])).toBe(html);
    expect(buildHighlightedHtml(html, [{ seltext: "missing", color: null, name: "" }])).toBe(html);
  });

  it("survives the strip + inject round-trip (marks and script both present)", () => {
    const html =
      "<html><body><p>cat and dog</p><script>alert(1)</script>" +
      "<p onclick=\"x()\">second line</p></body></html>";
    const baked = buildHighlightedHtml(stripPageScripts(html), [
      { seltext: "cat and dog", color: "#00aa00", name: "pet" },
    ]);
    const srcDoc = injectHighlightScript(baked, "<script>QC</script>");
    expect(srcDoc).not.toContain("alert(1)");
    expect(srcDoc).not.toContain("onclick=");
    expect(countMarks(srcDoc)).toBe(1);
    expect(srcDoc).toContain("<script>QC</script>");
    // The injected script must land AFTER the marks, before </body>.
    expect(srcDoc.indexOf("<mark")).toBeGreaterThan(-1);
    expect(srcDoc.indexOf("</body>")).toBeGreaterThan(srcDoc.indexOf("</mark>"));
  });

  it("round-trips baked marks through the injected script's core positions", () => {
    // What the parent bakes must be what the iframe's own matching would
    // find: identical qcFindMatches calls on the same collapsed text.
    const html = "<p>Tom &amp; Jerry</p><p>are best friends</p>";
    const codings: QcCodingPayload[] = [{ seltext: "Tom & Jerry\nare best", color: null, name: "" }];
    const model = buildViewModel(html);
    const baked = buildHighlightedHtml(html, codings);
    const bakedView = buildViewModel(baked);
    expect(bakedView.text).toBe(model.text);
    expect(countMarks(baked)).toBeGreaterThan(0);
  });
});

describe("mapViewRangeToSource", () => {
  it("maps a within-node selection 1:1 to source offsets", () => {
    const m = buildViewModel("<p>Hello world</p>");
    // "Hello world" lives at source [3,14); "world" = view indices [6,11).
    expect(mapViewRangeToSource(m, 6, 11)).toEqual({ pos0: 9, pos1: 14, seltext: "world" });
    expect(mapViewRangeToSource(m, 0, 5)).toEqual({ pos0: 3, pos1: 8, seltext: "Hello" });
  });

  it("maps across text nodes (inter-tag whitespace is dropped in the view)", () => {
    const m = buildViewModel("<p>Hello</p>\n<p>world</p>");
    // view = "Helloworld"; "Hello" = [0,5) -> source [3,8).
    expect(mapViewRangeToSource(m, 0, 5)).toEqual({ pos0: 3, pos1: 8, seltext: "Hello" });
    // The full selection spans both <p>s — the source range includes the
    // closing/opening tags between the words.
    expect(mapViewRangeToSource(m, 0, 10)).toEqual({ pos0: 3, pos1: 21, seltext: "Helloworld" });
  });

  it("maps an entity char to the whole entity source span", () => {
    const m = buildViewModel("<p>Tom &amp; Jerry</p>");
    // view = "Tom & Jerry"; the '&' is view index 4 -> the whole "&amp;".
    expect(mapViewRangeToSource(m, 4, 5)).toEqual({ pos0: 7, pos1: 12, seltext: "&" });
  });

  it("maps a collapsed whitespace run to the full source run", () => {
    const m = buildViewModel("<p>a  b</p>");
    // view = "a b" — the space covers source [4,6) (both raw spaces).
    expect(mapViewRangeToSource(m, 1, 2)).toEqual({ pos0: 4, pos1: 6, seltext: " " });
    expect(mapViewRangeToSource(m, 0, 3)).toEqual({ pos0: 3, pos1: 7, seltext: "a b" });
  });

  it("clamps out-of-range indices and rejects empty selections", () => {
    const m = buildViewModel("<p>abc</p>");
    expect(mapViewRangeToSource(m, 2, 20)).toEqual({ pos0: 5, pos1: 6, seltext: "c" });
    expect(mapViewRangeToSource(m, 5, 5)).toBeNull();
    expect(mapViewRangeToSource(m, 3, 3)).toBeNull();
    expect(mapViewRangeToSource(m, 4, 2)).toBeNull(); // start beyond end
  });

  it("never maps into code/pre content (absent from the model)", () => {
    const m = buildViewModel("<p>keep</p><pre>raw</pre>");
    expect(m.text).toBe("keep");
    expect(mapViewRangeToSource(m, 0, 4)).toEqual({ pos0: 3, pos1: 7, seltext: "keep" });
    expect(mapViewRangeToSource(m, 4, 10)).toBeNull();
  });
});

describe("viewTextMatchesFulltext", () => {
  it("matches modulo whitespace and block newlines", () => {
    expect(viewTextMatchesFulltext("Helloworld", "Hello\nworld")).toBe(true);
    expect(viewTextMatchesFulltext("Hello world", "Hello   world")).toBe(true);
    expect(viewTextMatchesFulltext("Tom & Jerry", "Tom & Jerry")).toBe(true);
    expect(viewTextMatchesFulltext("a b", "a\u00A0b")).toBe(true);
  });

  it("rejects different text and empty selections", () => {
    expect(viewTextMatchesFulltext("Hello world", "Hello there")).toBe(false);
    expect(viewTextMatchesFulltext("alpha", "aleph")).toBe(false);
    expect(viewTextMatchesFulltext(" ", " ")).toBe(false);
    expect(viewTextMatchesFulltext("", "")).toBe(false);
  });
});

describe("locateInFulltext", () => {
  const modelOf = (fulltext: string) => buildViewModel(fulltext);

  it("locates a view slice in the fulltext and returns the raw slice", () => {
    const ft = "Probe\nProbe page\nThe quick brown fox jumps over the lazy dog.\n\nAnother line.";
    const hit = locateInFulltext(ft, modelOf(ft), "own fox jumps over the lazy dog.", 52);
    expect(hit).not.toBeNull();
    // "own" starts inside "brown": raw "The quick brown" -> 'o' at 29.
    expect(hit!.pos0).toBe(29);
    expect(hit!.pos1).toBe(61);
    expect(hit!.seltext).toBe("own fox jumps over the lazy dog.");
  });

  it("matches across the block newlines the extraction inserts", () => {
    const ft = "Hello\nworld\nmore text";
    const hit = locateInFulltext(ft, modelOf(ft), "Helloworld", 0);
    expect(hit).toEqual({ pos0: 0, pos1: 11, seltext: "Hello\nworld" });
  });

  it("handles the full pipeline drift (title/headings shift source vs fulltext)", () => {
    // The backend's extraction includes the title and inserts "\n" at block
    // tags, so source offsets drift; the locate must still find the text the
    // view selection covers and return FULLTEXT positions.
    const html =
      "<title>Probe</title><body><h1>Probe page</h1>" +
      "<p>The quick brown fox jumps over the lazy dog.</p>" +
      "<p>Another line of research text to select.</p></body>";
    const fulltext =
      "Probe\nProbe page\nThe quick brown fox jumps over the lazy dog.\n\n" +
      "Another line of research text to select.\n";
    const view = buildViewModel(html);
    // View text: "Probe pageThe quick brown fox jumps over the lazy dog.…" —
    // "own fox jumps over the lazy dog." starts at view index 22 (the 'o' of
    // "brown", one text node so the inner spaces are preserved).
    const mapped = mapViewRangeToSource(view, 22, 54);
    expect(mapped).not.toBeNull();
    expect(mapped!.seltext).toBe("own fox jumps over the lazy dog.");
    const hit = locateInFulltext(fulltext, modelOf(fulltext), mapped!.seltext, mapped!.pos0);
    expect(hit).not.toBeNull();
    expect(hit!.pos0).toBe(29);
    expect(hit!.pos1).toBe(61);
    expect(hit!.seltext).toBe("own fox jumps over the lazy dog.");
    expect(viewTextMatchesFulltext(mapped!.seltext, hit!.seltext)).toBe(true);
  });

  it("uses the source hint to disambiguate repeated text", () => {
    const ft = "cat and dog. also a cat and dog.";
    const m = modelOf(ft);
    const near = locateInFulltext(ft, m, "dog.", 24);
    expect(near!.pos0).toBe(28);
    expect(near!.seltext).toBe("dog.");
    const far = locateInFulltext(ft, m, "dog.", 4);
    expect(far!.pos0).toBe(8);
    expect(far!.seltext).toBe("dog.");
  });

  it("is whitespace-insensitive on both sides", () => {
    const ft = "alpha\n\n beta   gamma";
    const hit = locateInFulltext(ft, modelOf(ft), "beta gamma", 0);
    expect(hit).not.toBeNull();
    expect(hit!.seltext).toBe("beta   gamma");
  });

  it("returns null for missing or empty selections", () => {
    const ft = "nothing here at all";
    const m = modelOf(ft);
    expect(locateInFulltext(ft, m, "not present", 0)).toBeNull();
    expect(locateInFulltext(ft, m, "   ", 0)).toBeNull();
    expect(locateInFulltext(ft, m, "", 0)).toBeNull();
    expect(locateInFulltext(ft, m, "nothing here at all and then some", 0)).toBeNull();
  });
});

describe("codingsOverlappingRange", () => {
  it("finds the codings whose spans overlap the given source range", () => {
    const codings = [
      { ctid: 1, pos0: 0, pos1: 10 },
      { ctid: 2, pos0: 12, pos1: 20 },
      { ctid: 3, pos0: 10, pos1: 11 },
    ];
    expect(codingsOverlappingRange(codings, 9, 11).map((c) => c.ctid)).toEqual([1, 3]);
    expect(codingsOverlappingRange(codings, 11, 12)).toEqual([]);
    expect(codingsOverlappingRange(codings, 0, 1).map((c) => c.ctid)).toEqual([1]);
  });
});

describe("parseFrameMessage", () => {
  it("parses a qc:selection payload with rect", () => {
    expect(
      parseFrameMessage({
        type: "qc:selection",
        startView: 3,
        endView: 9,
        text: "abc",
        rect: { left: 1, top: 2, bottom: 3 },
        mouseX: 5,
        mouseY: 6,
      }),
    ).toEqual({
      type: "qc:selection",
      startView: 3,
      endView: 9,
      text: "abc",
      rect: { left: 1, top: 2, bottom: 3 },
      mouseX: 5,
      mouseY: 6,
    });
  });

  it("accepts a missing rect / mouse (defaults to null / 0)", () => {
    const msg = parseFrameMessage({ type: "qc:selection", startView: 0, endView: 1, text: "x" });
    expect(msg).not.toBeNull();
    expect((msg as QcSelectionMessage).rect).toBeNull();
    expect((msg as QcSelectionMessage).mouseX).toBe(0);
  });

  it("parses the contextmenu payload (view index optional)", () => {
    expect(
      parseFrameMessage({ type: "qc:contextmenu", x: 10, y: 20, viewIndex: 7 }),
    ).toEqual({ type: "qc:contextmenu", x: 10, y: 20, viewIndex: 7 });
    expect(parseFrameMessage({ type: "qc:contextmenu", x: 1, y: 2 })).toEqual({
      type: "qc:contextmenu",
      x: 1,
      y: 2,
      viewIndex: null,
    });
  });

  it("parses the clear and mousedown signals", () => {
    expect(parseFrameMessage({ type: "qc:selection-cleared" })).toEqual({
      type: "qc:selection-cleared",
    });
    expect(parseFrameMessage({ type: "qc:frame-mousedown" })).toEqual({
      type: "qc:frame-mousedown",
    });
  });

  it("rejects unknown types and malformed payloads (qc:codings never routes)", () => {
    expect(parseFrameMessage({ type: "qc:codings", codings: [] })).toBeNull();
    expect(parseFrameMessage({ type: "qc:selection", startView: "x", endView: 1, text: "t" })).toBeNull();
    expect(parseFrameMessage({ type: "qc:selection", startView: 0, endView: 1 })).toBeNull();
    expect(parseFrameMessage({ type: "qc:contextmenu", x: "a", y: 1 })).toBeNull();
    expect(parseFrameMessage({ type: "qc:contextmenu", x: NaN, y: 1 })).toBeNull();
    expect(parseFrameMessage(null)).toBeNull();
    expect(parseFrameMessage("hi")).toBeNull();
    expect(parseFrameMessage({ type: "qc:highlight-ready" })).toBeNull();
  });
});

describe("cleanEmptyLines", () => {
  it("collapses runs of blank lines to a single newline", () => {
    expect(cleanEmptyLines("a\n\n\nb")).toBe("a\nb");
  });

  it("strips trailing whitespace per line", () => {
    expect(cleanEmptyLines("a  \nb\t\n")).toBe("a\nb");
  });

  it("normalizes CRLF to LF", () => {
    expect(cleanEmptyLines("a\r\n\r\nb")).toBe("a\nb");
  });

  it("handles CR-only line endings", () => {
    expect(cleanEmptyLines("a\r\rb")).toBe("a\nb");
  });

  it("trims leading and trailing whitespace", () => {
    expect(cleanEmptyLines("  \n\nhello\n\n  ")).toBe("hello");
  });

  it("preserves single newlines as paragraph breaks", () => {
    expect(cleanEmptyLines("para1\npara2")).toBe("para1\npara2");
  });

  it("returns empty string for blank input", () => {
    expect(cleanEmptyLines("")).toBe("");
    expect(cleanEmptyLines("  \n  \n  ")).toBe("");
  });
});
