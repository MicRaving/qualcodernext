import { describe, expect, it } from "vitest";
import type { Source } from "@/lib/api";
import { filterSources, mediaTypeLabel, sortSources } from "@/features/manage/files";

function makeSource(overrides: Partial<Source>): Source {
  return {
    id: 1,
    name: "a.txt",
    fulltext: null,
    mediapath: null,
    memo: "",
    owner: "default",
    date: "2024-01-01 00:00:00",
    av_text_id: null,
    risid: null,
    media_type: "text",
    ...overrides,
  };
}

describe("filterSources", () => {
  const sources = [
    makeSource({ id: 1, name: "Interview One.txt", memo: "first session" }),
    makeSource({ id: 2, name: "fieldnotes.txt", memo: "site visit notes" }),
    makeSource({ id: 3, name: "photo.png", memo: "courtyard" }),
  ];

  it("matches names case-insensitively", () => {
    expect(filterSources(sources, "INTERVIEW")).toEqual([sources[0]]);
    expect(filterSources(sources, "field")).toHaveLength(1);
  });

  it("matches memo text", () => {
    expect(filterSources(sources, "courtyard")).toEqual([sources[2]]);
  });

  it("returns everything for an empty query", () => {
    expect(filterSources(sources, "")).toEqual(sources);
    expect(filterSources(sources, "   ")).toEqual(sources);
  });
});

describe("sortSources", () => {
  const sources = [
    makeSource({ id: 1, name: "Bravo.txt", date: "2024-02-01 10:00:00", owner: "zoe", media_type: "audio" }),
    makeSource({ id: 2, name: "alpha.txt", date: "2024-01-01 09:00:00", owner: "amy", media_type: "text" }),
    makeSource({ id: 3, name: "Charlie.pdf", date: "2024-03-01 08:00:00", owner: "mike", media_type: "image" }),
  ];

  it("sorts by name ascending with localeCompare", () => {
    expect(sortSources(sources, "name", "asc").map((s) => s.name)).toEqual([
      "alpha.txt",
      "Bravo.txt",
      "Charlie.pdf",
    ]);
  });

  it("sorts by name descending", () => {
    expect(sortSources(sources, "name", "desc").map((s) => s.name)).toEqual([
      "Charlie.pdf",
      "Bravo.txt",
      "alpha.txt",
    ]);
  });

  it("sorts by date ascending and descending", () => {
    expect(sortSources(sources, "date", "asc").map((s) => s.id)).toEqual([2, 1, 3]);
    expect(sortSources(sources, "date", "desc").map((s) => s.id)).toEqual([3, 1, 2]);
  });

  it("sorts by owner", () => {
    expect(sortSources(sources, "owner", "asc").map((s) => s.owner)).toEqual(["amy", "mike", "zoe"]);
  });

  it("sorts by media type", () => {
    expect(sortSources(sources, "type", "asc").map((s) => s.media_type)).toEqual([
      "audio",
      "image",
      "text",
    ]);
  });
});

describe("mediaTypeLabel", () => {
  it("reports PDF when the filename ends in .pdf", () => {
    expect(mediaTypeLabel("text", "report.PDF")).toBe("PDF");
    expect(mediaTypeLabel("text", "paper.pdf")).toBe("PDF");
    expect(mediaTypeLabel("text", "notes.txt")).toBe("Text");
  });

  it("maps media types to labels", () => {
    expect(mediaTypeLabel("text")).toBe("Text");
    expect(mediaTypeLabel("pdf")).toBe("PDF");
    expect(mediaTypeLabel("image")).toBe("Image");
    expect(mediaTypeLabel("audio")).toBe("Audio");
    expect(mediaTypeLabel("video")).toBe("Video");
  });
});
