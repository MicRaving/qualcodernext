// @vitest-environment jsdom
/**
 * SearchDialog live search must ignore a superseded response: when an older
 * (slower) request resolves after a newer one, its results must not replace
 * the newer results.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import { SearchDialog } from "@/features/search/SearchDialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const apiMock = vi.hoisted(() => {
  const fns: Record<string, ReturnType<typeof vi.fn>> = {};
  const api = new Proxy({} as Record<string, (...args: unknown[]) => unknown>, {
    get: (_target, prop: string) => {
      fns[prop] ??= vi.fn();
      return fns[prop];
    },
  });
  return { api, fns };
});

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: apiMock.api,
}));

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function hit(name: string) {
  return {
    kind: "file",
    id: 1,
    name,
    context: "",
    match_start: 0,
    match_end: 0,
    match_count: 1,
  };
}

describe("SearchDialog stale responses", () => {
  let el: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers();
    apiMock.fns.aiStatus = vi.fn().mockResolvedValue({ enabled: false, configured: false });
    el = document.createElement("div");
    document.body.appendChild(el);
    root = createRoot(el);
  });

  afterEach(() => {
    act(() => root.unmount());
    el.remove();
    vi.useRealTimers();
  });

  function render(query: string) {
    root.render(
      <I18nProvider>
        <SearchDialog open anchor={null} query={query} onClose={() => {}} />
      </I18nProvider>,
    );
  }

  it("keeps the newer results when the older request resolves last", async () => {
    const slow = deferred<unknown>();
    const fast = deferred<unknown>();
    apiMock.fns.search = vi
      .fn()
      .mockReturnValueOnce(slow.promise)
      .mockReturnValueOnce(fast.promise);

    await act(async () => render("old"));
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    await act(async () => render("new"));
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(apiMock.fns.search).toHaveBeenCalledTimes(2);

    await act(async () => fast.resolve({ results: [hit("NEWER-RESULT")], total: 1 }));
    await act(async () => slow.resolve({ results: [hit("OLDER-RESULT")], total: 1 }));

    expect(el.textContent).toContain("NEWER-RESULT");
    expect(el.textContent).not.toContain("OLDER-RESULT");
  });
});
