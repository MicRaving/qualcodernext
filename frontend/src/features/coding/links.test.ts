/**
 * Segment link payload tests — the `qcnext-link://` clipboard format and
 * the in-session paste memory (used by the coders' copy/paste flow).
 */
import { describe, expect, it, beforeEach } from "vitest";
import {
  encodeLinkPayload,
  parseLinkPayload,
  rememberCopiedLink,
  readLinkPayload,
} from "@/features/coding/links";

describe("link payload", () => {
  it("encodes fid:pos0-pos1 under the qcnext-link scheme", () => {
    expect(encodeLinkPayload(7, 12, 34)).toBe("qcnext-link://7:12-34");
  });

  it("round-trips through parse", () => {
    expect(parseLinkPayload(encodeLinkPayload(3, 5, 9))).toEqual({
      fid: 3,
      pos0: 5,
      pos1: 9,
    });
  });

  it("accepts surrounding whitespace", () => {
    expect(parseLinkPayload("  qcnext-link://1:0-4  ")).toEqual({
      fid: 1,
      pos0: 0,
      pos1: 4,
    });
  });

  it("rejects other schemes and malformed payloads", () => {
    expect(parseLinkPayload("https://example.com/7:1-2")).toBeNull();
    expect(parseLinkPayload("qcnext-link://7:1")).toBeNull();
    expect(parseLinkPayload("qcnext-link://a:1-2")).toBeNull();
    expect(parseLinkPayload("qcnext-link://7:-1-2")).toBeNull();
    expect(parseLinkPayload("")).toBeNull();
  });
});

describe("in-session paste memory", () => {
  beforeEach(() => {
    rememberCopiedLink(null);
  });

  it("remembers the last copied link without the clipboard API", () => {
    rememberCopiedLink({ fid: 2, pos0: 4, pos1: 8 });
    expect(readLinkPayload()).resolves.toEqual({ fid: 2, pos0: 4, pos1: 8 });
  });

  it("returns null when nothing was copied", () => {
    expect(readLinkPayload()).resolves.toBeNull();
  });
});
