// @vitest-environment jsdom
/**
 * Context pickers — "All" is the default: after the data loads, every
 * memos/codes/files key is selected (all = true) and the derived id lists
 * carry all of them.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useContextPickers } from "@/features/ai/contextPickerData";

const mocks = vi.hoisted(() => ({
  memos: [
    { kind: "file", id: 10, name: "f-memo", memo: "m", date: "", owner: "" },
    { kind: "code", id: 20, name: "c-memo", memo: "m", date: "", owner: "" },
  ],
  codeTree: [
    { id: 5, kind: "code", name: "Teaching", memo: "", parent_id: null },
  ],
  sources: [
    { id: 7, name: "sample.txt", memo: "", media_type: "text" },
  ],
}));

vi.mock("@/lib/api", () => ({
  api: {
    codeTree: () => Promise.resolve(mocks.codeTree),
    reports: { codeFrequencies: () => Promise.resolve({ rows: [] }) },
    sources: () => Promise.resolve(mocks.sources),
  },
  fetchWithTimeout: () =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ memos: mocks.memos }) }),
  initApiBase: () => Promise.resolve("http://test"),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

let container: HTMLElement;
let root: Root;

function Probe({ showClear = false }: { showClear?: boolean }) {
  const p = useContextPickers();
  return (
    <div>
      <span data-testid="all">{String(p.all)}</span>
      <span data-testid="count">{p.selectedKeys.size}</span>
      <span data-testid="memos">{p.selectedMemoIds.join(",")}</span>
      <span data-testid="codes">{p.selectedCodeIds.join(",")}</span>
      <span data-testid="files">{p.selectedSourceIds.join(",")}</span>
      {showClear && (
        <button type="button" onClick={() => p.setAll(false)} data-testid="clear-all" />
      )}
    </div>
  );
}

function renderProbe(showClear = false) {
  act(() => {
    root.render(<Probe showClear={showClear} />);
  });
}

function text(id: string): string {
  return container.querySelector(`[data-testid="${id}"]`)?.textContent ?? "";
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("useContextPickers all-default", () => {
  it("selects every key after the data loads (All on by default)", async () => {
    renderProbe();
    await act(async () => {});
    // file:10, code:20, c:5, f:7
    expect(text("all")).toBe("true");
    expect(text("count")).toBe("4");
    expect(text("memos")).toBe("10,20");
    expect(text("codes")).toBe("5");
    expect(text("files")).toBe("7");
  });

  it("setAll(false) clears the selection and all becomes false", async () => {
    renderProbe(true);
    await act(async () => {});
    expect(text("all")).toBe("true");

    act(() => {
      container.querySelector<HTMLButtonElement>("[data-testid='clear-all']")?.click();
    });
    expect(text("all")).toBe("false");
    expect(text("count")).toBe("0");
  });
});
