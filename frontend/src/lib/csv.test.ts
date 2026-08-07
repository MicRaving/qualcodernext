// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { downloadCsv, toCsv } from "@/lib/csv";

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
