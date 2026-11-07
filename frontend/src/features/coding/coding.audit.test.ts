// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { parseTranscript } from "@/features/coding/media";
import { useCoder, type CoderLoad } from "@/features/coding/useCoder";
import { api, type Source } from "@/lib/api";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

describe("parseTranscript (SRT)", () => {
  it("keeps every cue, not just the last, and skips cue indices", () => {
    const srt = [
      "1",
      "00:00:01,000 --> 00:00:02,500",
      "Hello there",
      "",
      "2",
      "00:00:03,000 --> 00:00:04,000",
      "Second line",
      "continued",
      "",
    ].join("\r\n");
    expect(parseTranscript(srt)).toEqual([
      { startMs: 1000, endMs: 2000, text: "Hello there" },
      { startMs: 3000, endMs: 4000, text: "Second line continued" },
    ]);
  });

  it("still parses bracket timestamps", () => {
    expect(parseTranscript("[00:05] hi\nmore")).toEqual([
      { startMs: 5000, endMs: 7500, text: "hi" },
      { startMs: 5000, endMs: 7500, text: "more" },
    ]);
  });
});

describe("useCoder reload", () => {
  it("resolves reload() with the fresh codings even when a load is in flight", async () => {
    vi.spyOn(api, "codesFlat").mockResolvedValue([]);
    let call = 0;
    const releases: Array<() => void> = [];
    const load = vi.fn((): Promise<number[]> => {
      const n = ++call;
      return new Promise((resolve) => releases.push(() => resolve([n])));
    });
    const source = { id: 1 } as Source;
    let hook: CoderLoad<number> | null = null;
    function Probe() {
      hook = useCoder<number>(source, load, "err");
      return null;
    }
    const root = createRoot(document.createElement("div"));
    await act(async () => root.render(createElement(Probe)));
    expect(load).toHaveBeenCalledTimes(1);

    let fresh: number[] | undefined;
    await act(async () => {
      void hook!.reload().then((r) => (fresh = r));
    });
    expect(load).toHaveBeenCalledTimes(2);
    // The superseded first load settles first: it must not resolve reload().
    releases[0]();
    await flush();
    expect(fresh).toBeUndefined();
    releases[1]();
    await flush();
    expect(fresh).toEqual([2]);
    act(() => root.unmount());
    vi.restoreAllMocks();
  });
});
