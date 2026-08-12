import { describe, expect, it } from "vitest";
import {
  buildCrAt,
  rawToRendered,
  renderedToRaw,
  stripCr,
  normalizeCodingPositions,
} from "@/features/coding/media";

describe("CRLF offset mapping", () => {
  const raw = "[00:01] first line\r\n[00:11] second line\r\n[00:21] third line";
  const rendered = stripCr(raw);

  it("strips CR but keeps LF", () => {
    expect(rendered).toBe("[00:01] first line\n[00:11] second line\n[00:21] third line");
  });

  it("counts CRs before every raw offset", () => {
    const crAt = buildCrAt(raw);
    // "[00:01] first line" is 18 chars; the first CR sits at index 18.
    expect(crAt[0]).toBe(0);
    expect(crAt[18]).toBe(0);
    expect(crAt[19]).toBe(1);
    expect(crAt[39]).toBe(1);
    expect(crAt[40]).toBe(2);
    expect(crAt[raw.length]).toBe(2);
  });

  it("maps rendered offsets back to raw offsets", () => {
    const crAt = buildCrAt(raw);
    // Before the first CR, raw == rendered.
    expect(renderedToRaw(raw, crAt, 0)).toBe(0);
    expect(renderedToRaw(raw, crAt, 10)).toBe(10);
    // The second line: rendered offset 19 is inside "[00:11] second...",
    // whose raw position is 20 (one CR behind).
    expect(renderedToRaw(raw, crAt, 19)).toBe(20);
    expect(renderedToRaw(raw, crAt, 40)).toBe(42);
    // The end of the text.
    expect(renderedToRaw(raw, crAt, rendered.length)).toBe(raw.length);
  });

  it("maps raw positions to rendered positions", () => {
    const crAt = buildCrAt(raw);
    expect(rawToRendered(crAt, 0)).toBe(0);
    expect(rawToRendered(crAt, 20)).toBe(19);
    expect(rawToRendered(crAt, raw.length)).toBe(rendered.length);
  });

  it("round-trips every position", () => {
    const crAt = buildCrAt(raw);
    for (let i = 0; i <= rendered.length; i++) {
      expect(rawToRendered(crAt, renderedToRaw(raw, crAt, i))).toBe(i);
    }
  });

  it("is a no-op on LF-only text", () => {
    const plain = "[00:01] a\n[00:02] b";
    const crAt = buildCrAt(plain);
    expect(stripCr(plain)).toBe(plain);
    for (let i = 0; i <= plain.length; i++) {
      expect(renderedToRaw(plain, crAt, i)).toBe(i);
      expect(rawToRendered(crAt, i)).toBe(i);
    }
  });

  describe("normalizeCodingPositions", () => {
    const raw = "[00:01] first line\r\n[00:11] second line\r\n[00:21] third line";
    const crAt = buildCrAt(raw);

    it("keeps raw-space codings untouched", () => {
      // Selection on "second line" stored in raw space: raw[21:33].
      const c = { pos0: 21, pos1: 33, seltext: raw.slice(21, 33) };
      expect(normalizeCodingPositions(raw, crAt, c)).toBe(c);
    });

    it("keeps raw-space codings that span a CRLF line break", () => {
      const c = { pos0: 14, pos1: 24, seltext: raw.slice(14, 24) };
      expect(normalizeCodingPositions(raw, crAt, c)).toBe(c);
    });

    it("converts rendered-space codings (single line)", () => {
      // "second line" at rendered offsets 20..32 (one CR behind).
      const c = { pos0: 20, pos1: 32, seltext: "second line" };
      const out = normalizeCodingPositions(raw, crAt, c);
      expect(out).toEqual({ pos0: 21, pos1: 33, seltext: "second line" });
    });

    it("converts old-build codings with empty seltext", () => {
      const c = { pos0: 20, pos1: 32, seltext: "" };
      const out = normalizeCodingPositions(raw, crAt, c);
      expect(out.pos0).toBe(21);
      expect(out.pos1).toBe(33);
    });

    it("converts old-build codings with broken seltext", () => {
      // A rendered-space coding whose seltext does not match either the
      // raw or the rendered slice at its position (e.g. multi-line old
      // selections) is shifted back to raw space.
      const c = { pos0: 20, pos1: 32, seltext: "xx" };
      const out = normalizeCodingPositions(raw, crAt, c);
      expect(out.pos0).toBe(21);
      expect(out.pos1).toBe(33);
    });

    it("keeps self-consistent codings (raw slice matches seltext)", () => {
      // Old-build artifacts that are internally consistent are kept as-is;
      // this also protects TextCoder and new-build codings.
      const c = { pos0: 20, pos1: 32, seltext: raw.slice(20, 32) };
      expect(normalizeCodingPositions(raw, crAt, c)).toBe(c);
    });

    it("keeps codings in the region before the first CR as-is", () => {
      const c = { pos0: 2, pos1: 8, seltext: raw.slice(2, 8) };
      expect(normalizeCodingPositions(raw, crAt, c)).toBe(c);
    });
  });
});
