// @vitest-environment jsdom
/**
 * PseudonymsMenu tests — the Files-topbar mask button opens the
 * app-themed editor: list loads on open, add/delete round-trip through
 * the API, Escape dismisses.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import { PseudonymsMenu } from "@/features/manage/PseudonymsMenu";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const apiMock = vi.hoisted(() => {
  const fns: Record<string, ReturnType<typeof vi.fn>> = {
    pseudonyms: vi.fn(),
    addPseudonym: vi.fn(),
    deletePseudonym: vi.fn(),
  };
  const api = new Proxy({} as Record<string, (...args: unknown[]) => unknown>, {
    get: (_target, prop: string) => {
      fns[prop] ??= vi.fn();
      return fns[prop];
    },
  });
  return { api, fns };
});

vi.mock("@/lib/api", () => ({ api: apiMock.api }));

function renderMenu() {
  const el = document.createElement("div");
  document.body.appendChild(el);
  let root: Root | null = null;
  act(() => {
    root = createRoot(el);
    root.render(
      <I18nProvider>
        <PseudonymsMenu />
      </I18nProvider>,
    );
  });
  return {
    el,
    cleanup: () => {
      act(() => root?.unmount());
      el.remove();
    },
  };
}

function setInput(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  act(() => {
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function openMenu(el: HTMLElement) {
  const button = el.querySelector('button[aria-label="Pseudonyms"]') as HTMLButtonElement;
  expect(button).not.toBeNull();
  await act(async () => {
    button.click();
  });
}

beforeEach(() => {
  for (const key of Object.keys(apiMock.fns)) apiMock.fns[key].mockReset();
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("PseudonymsMenu", () => {
  it("opens the editor and lists pseudonyms", async () => {
    apiMock.fns.pseudonyms.mockResolvedValue({
      pseudonyms: [{ original: "John Doe", pseudonym: "Participant_A" }],
    });
    const { el, cleanup } = renderMenu();
    await openMenu(el);
    expect(el.textContent).toContain("John Doe");
    expect(el.textContent).toContain("Participant_A");
    expect(el.querySelector('input[aria-label="Original"]')).not.toBeNull();
    cleanup();
  });

  it("adds a pseudonym and reloads the list", async () => {
    apiMock.fns.pseudonyms.mockResolvedValue({ pseudonyms: [] });
    apiMock.fns.addPseudonym.mockResolvedValue({ pseudonym: { original: "Jo", pseudonym: "P1" } });
    const { el, cleanup } = renderMenu();
    await openMenu(el);
    setInput(el.querySelector('input[aria-label="Original"]') as HTMLInputElement, "Jo");
    const add = Array.from(el.querySelectorAll("button")).find((b) =>
      b.textContent?.includes("Add"),
    ) as HTMLButtonElement;
    await act(async () => {
      add.click();
    });
    expect(apiMock.fns.addPseudonym).toHaveBeenCalledWith("Jo", "");
    cleanup();
  });

  it("deletes a pseudonym", async () => {
    apiMock.fns.pseudonyms.mockResolvedValue({
      pseudonyms: [{ original: "John Doe", pseudonym: "Participant_A" }],
    });
    apiMock.fns.deletePseudonym.mockResolvedValue({ ok: true });
    const { el, cleanup } = renderMenu();
    await openMenu(el);
    const del = el.querySelector('button[aria-label="Delete"]') as HTMLButtonElement;
    await act(async () => {
      del.click();
    });
    expect(apiMock.fns.deletePseudonym).toHaveBeenCalledWith("John Doe");
    cleanup();
  });

  it("closes on Escape", async () => {
    apiMock.fns.pseudonyms.mockResolvedValue({ pseudonyms: [] });
    const { el, cleanup } = renderMenu();
    await openMenu(el);
    expect(el.textContent).toContain("No pseudonyms yet.");
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(el.textContent).not.toContain("No pseudonyms yet.");
    cleanup();
  });
});
