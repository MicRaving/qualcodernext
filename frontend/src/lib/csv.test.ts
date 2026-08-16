// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { downloadCsv, parseCsv, toCsv } from "@/lib/csv";

describe("toCsv", () => {
  it("quotes cells containing commas", () => {
    expect(toCsv(["name", "notes"], [["a, b", "plain"]])).toBe(
      '\uFEFF"name","notes"\r\n"a, b","plain"\r\n',
    );
  });

  it("escapes embedded double quotes as doubled quotes", () => {
    expect(toCsv(["quote"], [['say "hi"']])).toBe('\uFEFF"quote"\r\n"say ""hi"""\r\n');
  });

  it("keeps newlines inside a cell intact", () => {
    expect(toCsv(["text"], [["line1\nline2"]])).toBe('\uFEFF"text"\r\n"line1\nline2"\r\n');
  });

  it("uses CRLF line endings and a UTF-8 BOM prefix", () => {
    expect(toCsv(["a"], [["b"]])).toBe('\uFEFF"a"\r\n"b"\r\n');
    expect(toCsv(["a"], [["b"]]).startsWith("\uFEFF")).toBe(true);
    expect(toCsv(["a"], [["b"]]).includes("\r\n")).toBe(true);
  });

  it("converts null and undefined cells to empty strings", () => {
    expect(toCsv(["a", "b"], [[null, undefined]])).toBe('\uFEFF"a","b"\r\n"",""\r\n');
  });

  it("emits a header row even with no data rows", () => {
    expect(toCsv(["a", "b"], [])).toBe('\uFEFF"a","b"\r\n');
  });

  it("stringifies non-string values", () => {
    expect(toCsv(["n"], [[42, true]])).toBe('\uFEFF"n"\r\n"42","true"\r\n');
  });
});

describe("downloadCsv", () => {
  it("creates a blob URL, clicks a temp anchor and revokes the URL", async () => {
    const createObjectURL = vi.fn<(_blob: Blob) => string>(() => "blob:mock-csv");
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as typeof URL.revokeObjectURL;
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    downloadCsv("report.csv", ["code", "count"], [["alpha", 3]]);

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-csv");
    expect(click).toHaveBeenCalledTimes(1);
    expect(click.mock.instances[0]).toBeInstanceOf(HTMLAnchorElement);

    const blob = createObjectURL.mock.calls[0]?.[0] as Blob;
    expect(blob.type).toBe("text/csv;charset=utf-8");
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect([bytes[0], bytes[1], bytes[2]]).toEqual([0xef, 0xbb, 0xbf]);
    expect(new TextDecoder("utf-8", { ignoreBOM: true }).decode(bytes)).toBe(
      '\uFEFF"code","count"\r\n"alpha","3"\r\n',
    );

    click.mockRestore();
  });
});

describe("parseCsv", () => {
  /** Headers+rows only — the cell-span tests below cover the new field. */
  const table = (text: string) => {
    const { cells, ...rest } = parseCsv(text);
    void cells;
    return rest;
  };

  it("parses a simple header + rows", () => {
    expect(table("name,note\nalpha,one\nbeta,two\n")).toEqual({
      headers: ["name", "note"],
      rows: [
        ["alpha", "one"],
        ["beta", "two"],
      ],
    });
  });

  it("keeps quoted fields containing commas intact", () => {
    expect(table('name,note\n"a, b",plain\n')).toEqual({
      headers: ["name", "note"],
      rows: [["a, b", "plain"]],
    });
  });

  it("unescapes doubled quotes inside quoted fields", () => {
    expect(table('quote\n"say ""hi"""\n')).toEqual({
      headers: ["quote"],
      rows: [['say "hi"']],
    });
  });

  it("keeps newlines inside quoted fields as one record", () => {
    expect(table('text\n"line1\nline2"\n')).toEqual({
      headers: ["text"],
      rows: [["line1\nline2"]],
    });
  });

  it("accepts CRLF and LF line endings", () => {
    expect(table("a,b\r\n1,2\r\n")).toEqual({
      headers: ["a", "b"],
      rows: [["1", "2"]],
    });
    expect(table("a,b\n1,2\n")).toEqual({
      headers: ["a", "b"],
      rows: [["1", "2"]],
    });
    expect(table("a,b\r\n1,2")).toEqual({
      headers: ["a", "b"],
      rows: [["1", "2"]],
    });
  });

  it("returns headers with an empty row list for a header-only file", () => {
    expect(table("a,b\n")).toEqual({ headers: ["a", "b"], rows: [] });
    expect(table("a,b")).toEqual({ headers: ["a", "b"], rows: [] });
  });

  it("detects tabs for TSV input", () => {
    expect(table("name\tnote\nalpha\tone\ntwo\t" + "three\n")).toEqual({
      headers: ["name", "note"],
      rows: [
        ["alpha", "one"],
        ["two", "three"],
      ],
    });
  });

  it("keeps commas inside quoted header cells", () => {
    expect(table('"a, b",c\n1,2\n')).toEqual({
      headers: ["a, b", "c"],
      rows: [["1", "2"]],
    });
  });

  it("strips a UTF-8 BOM", () => {
    expect(table("\uFEFFa,b\n1,2\n")).toEqual({
      headers: ["a", "b"],
      rows: [["1", "2"]],
    });
  });

  it("round-trips toCsv output", () => {
    const text = toCsv(["name", "note"], [["a, b", 'say "hi"'], ["line1\nline2", ""]]);
    expect(table(text)).toEqual({
      headers: ["name", "note"],
      rows: [
        ["a, b", 'say "hi"'],
        ["line1\nline2", ""],
      ],
    });
  });

  it("handles empty input and a lone quoted empty field", () => {
    expect(table("")).toEqual({ headers: [], rows: [] });
    expect(table('""')).toEqual({ headers: [""], rows: [] });
    expect(table('"",""\n""\n')).toEqual({ headers: ["", ""], rows: [[""]] });
  });

  describe("cells (raw spans)", () => {
    it("maps simple fields to their raw offsets", () => {
      const { cells } = parseCsv("a,b\nxx,yyy\n");
      expect(cells).toEqual([
        [
          { text: "xx", start: 4, end: 6, toRaw: [4, 5] },
          { text: "yyy", start: 7, end: 10, toRaw: [7, 8, 9] },
        ],
      ]);
    });

    it("skips quote delimiters and unescapes quotes in the map", () => {
      const text = 'a,b\n"x, y","say ""hi"""\n';
      const { cells } = parseCsv(text);
      const [c0, c1] = cells[0];
      expect(c0).toEqual({
        text: "x, y",
        start: 5, // first decoded char, past the opening quote
        end: 9, // one past the last decoded char
        toRaw: [5, 6, 7, 8],
      });
      // "say ""hi""" — decoded `say "hi"`; the doubled-quote pairs map to
      // their first quote (16 and 20).
      expect(c1.text).toBe('say "hi"');
      expect(c1.start).toBe(12);
      expect(c1.end).toBe(21);
      expect(c1.toRaw).toEqual([12, 13, 14, 15, 16, 18, 19, 20]);
      // every decoded char maps back to the matching raw text char:
      expect(c1.toRaw.map((r) => text[r]).join("")).toBe(c1.text);
    });

    it("maps embedded newlines inside quoted fields", () => {
      const { cells } = parseCsv('text\n"l1\nl2"\n');
      const [c] = cells[0];
      expect(c.text).toBe("l1\nl2");
      expect(c.start).toBe(6);
      expect(c.end).toBe(11);
      expect(c.toRaw).toEqual([6, 7, 8, 9, 10]);
    });

    it("reports zero-length spans for empty fields", () => {
      const { cells } = parseCsv("a,b,c\n1,,3\n");
      expect(cells[0][1]).toEqual({ text: "", start: 8, end: 8, toRaw: [] });
    });

    it("round-trips toCsv output with exact char maps", () => {
      const text = toCsv(["name", "note"], [["a, b", 'say "hi"'], ["line1\nline2", ""]]);
      const { cells, rows } = parseCsv(text);
      cells.forEach((cellRow, ri) =>
        cellRow.forEach((cell, ci) => {
          expect(cell.text).toBe(rows[ri][ci]);
          const raw = cell.toRaw.map((r) => text[r]).join("");
          expect(raw).toBe(cell.text);
        }),
      );
    });

    it("aligns cells with rows 1:1", () => {
      const text = toCsv(["a", "b"], [["x", "y"], ["z", "w"]]);
      const { cells, rows } = parseCsv(text);
      expect(cells).toHaveLength(rows.length);
      cells.forEach((row, ri) => expect(row).toHaveLength(rows[ri].length));
    });
  });
});
