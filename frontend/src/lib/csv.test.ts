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
  it("parses a simple header + rows", () => {
    expect(parseCsv("name,note\nalpha,one\nbeta,two\n")).toEqual({
      headers: ["name", "note"],
      rows: [
        ["alpha", "one"],
        ["beta", "two"],
      ],
    });
  });

  it("keeps quoted fields containing commas intact", () => {
    expect(parseCsv('name,note\n"a, b",plain\n')).toEqual({
      headers: ["name", "note"],
      rows: [["a, b", "plain"]],
    });
  });

  it("unescapes doubled quotes inside quoted fields", () => {
    expect(parseCsv('quote\n"say ""hi"""\n')).toEqual({
      headers: ["quote"],
      rows: [['say "hi"']],
    });
  });

  it("keeps newlines inside quoted fields as one record", () => {
    expect(parseCsv('text\n"line1\nline2"\n')).toEqual({
      headers: ["text"],
      rows: [["line1\nline2"]],
    });
  });

  it("accepts CRLF and LF line endings", () => {
    expect(parseCsv("a,b\r\n1,2\r\n")).toEqual({
      headers: ["a", "b"],
      rows: [["1", "2"]],
    });
    expect(parseCsv("a,b\n1,2\n")).toEqual({
      headers: ["a", "b"],
      rows: [["1", "2"]],
    });
    expect(parseCsv("a,b\r\n1,2")).toEqual({
      headers: ["a", "b"],
      rows: [["1", "2"]],
    });
  });

  it("returns headers with an empty row list for a header-only file", () => {
    expect(parseCsv("a,b\n")).toEqual({ headers: ["a", "b"], rows: [] });
    expect(parseCsv("a,b")).toEqual({ headers: ["a", "b"], rows: [] });
  });

  it("detects tabs for TSV input", () => {
    expect(parseCsv("name\tnote\nalpha\tone\ntwo\t" + "three\n")).toEqual({
      headers: ["name", "note"],
      rows: [
        ["alpha", "one"],
        ["two", "three"],
      ],
    });
  });

  it("keeps commas inside quoted header cells", () => {
    expect(parseCsv('"a, b",c\n1,2\n')).toEqual({
      headers: ["a, b", "c"],
      rows: [["1", "2"]],
    });
  });

  it("strips a UTF-8 BOM", () => {
    expect(parseCsv("\uFEFFa,b\n1,2\n")).toEqual({
      headers: ["a", "b"],
      rows: [["1", "2"]],
    });
  });

  it("round-trips toCsv output", () => {
    const text = toCsv(["name", "note"], [["a, b", 'say "hi"'], ["line1\nline2", ""]]);
    expect(parseCsv(text)).toEqual({
      headers: ["name", "note"],
      rows: [
        ["a, b", 'say "hi"'],
        ["line1\nline2", ""],
      ],
    });
  });

  it("handles empty input and a lone quoted empty field", () => {
    expect(parseCsv("")).toEqual({ headers: [], rows: [] });
    expect(parseCsv('""')).toEqual({ headers: [""], rows: [] });
    expect(parseCsv('"",""\n""\n')).toEqual({ headers: ["", ""], rows: [[""]] });
  });
});
