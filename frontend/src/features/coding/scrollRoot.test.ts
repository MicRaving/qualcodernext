// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import {
  contentHeightOf,
  isDocumentNode,
  scrollElementOf,
} from "@/features/coding/scrollRoot";

describe("scrollRoot", () => {
  it("isDocumentNode is false for plain elements and null", () => {
    expect(isDocumentNode(null)).toBe(false);
    expect(isDocumentNode(document.body)).toBe(false);
    expect(isDocumentNode({})).toBe(false);
  });

  it("isDocumentNode detects a real Document by nodeType 9", () => {
    expect(isDocumentNode(document)).toBe(true);
  });

  it("detects a cross-realm lookalike Document (nodeType 9, not instanceof)", () => {
    // Simulates an iframe contentDocument: an object from another JS realm
    // where `instanceof Document` is false but nodeType is 9.
    const fakeDocument = {
      nodeType: 9,
      scrollingElement: { scrollHeight: 120 },
      documentElement: { scrollHeight: 100 },
    };
    expect(fakeDocument instanceof Document).toBe(false);
    expect(isDocumentNode(fakeDocument)).toBe(true);
  });

  it("scrollElementOf returns the scrollingElement for a Document root", () => {
    const se = document.createElement("div");
    Object.defineProperty(se, "scrollHeight", { value: 50 });
    const fakeDocument = {
      nodeType: 9,
      scrollingElement: se,
      documentElement: document.documentElement,
    } as unknown as Document;
    expect(scrollElementOf(fakeDocument)).toBe(se);
  });

  it("scrollElementOf falls back to documentElement without scrollingElement", () => {
    const fakeDocument = {
      nodeType: 9,
      scrollingElement: null,
      documentElement: document.documentElement,
    } as unknown as Document;
    expect(scrollElementOf(fakeDocument)).toBe(document.documentElement);
  });

  it("scrollElementOf returns the element itself for an Element root", () => {
    const el = document.createElement("div");
    expect(scrollElementOf(el)).toBe(el);
  });

  it("contentHeightOf uses the scrolling element height for Documents", () => {
    const se = document.createElement("div");
    Object.defineProperty(se, "scrollHeight", { value: 240 });
    const fakeDocument = {
      nodeType: 9,
      scrollingElement: se,
      documentElement: document.documentElement,
    } as unknown as Document;
    expect(contentHeightOf(fakeDocument)).toBe(240);
  });

  it("contentHeightOf reads the element scrollHeight for Elements", () => {
    const el = document.createElement("div");
    Object.defineProperty(el, "scrollHeight", { value: 88 });
    expect(contentHeightOf(el)).toBe(88);
  });
});