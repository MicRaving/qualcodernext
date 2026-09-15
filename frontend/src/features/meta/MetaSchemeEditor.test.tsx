// @vitest-environment jsdom
/**
 * MetaSchemeEditor — the reworked editor must let a field be labelled, given a
 * dropdown editor with options, and saved with a codebook the publish step
 * understands (``study_fields``).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider, t as tr } from "@/lib/i18n";
import { ToastProvider } from "@/lib/toast";
import { MetaSchemeEditor } from "@/features/meta/MetaSchemeEditor";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const apiMock = vi.hoisted(() => {
  const fns: Record<string, ReturnType<typeof vi.fn>> = {};
  const api = new Proxy({} as Record<string, (...args: unknown[]) => unknown>, {
    get: (_target, prop: string) => {
      fns[prop] ??= vi.fn(async () => []);
      return fns[prop];
    },
  });
  return { api, fns };
});

vi.mock("@/lib/api", () => ({ api: apiMock.api }));

let root: Root | null = null;
let el: HTMLDivElement | null = null;

const onClose = vi.fn();
const onChanged = vi.fn();

function control(labelText: string, rootNode: ParentNode = document) {
  const label = Array.from(rootNode.querySelectorAll("label")).find((l) =>
    (l.textContent ?? "").startsWith(labelText),
  );
  return (label?.querySelector("input, textarea, select") ?? null) as
    | HTMLInputElement
    | HTMLTextAreaElement
    | HTMLSelectElement
    | null;
}

function setValue(node: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) {
  const proto =
    node instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : node instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  setter?.call(node, value);
  node.dispatchEvent(new Event(node instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
}

function buttonByText(text: string, rootNode: ParentNode = document) {
  return Array.from(rootNode.querySelectorAll("button")).find((b) => b.textContent === text) ?? null;
}

async function render() {
  el = document.createElement("div");
  document.body.appendChild(el);
  await act(async () => {
    root = createRoot(el as HTMLDivElement);
    root.render(
      <I18nProvider>
        <ToastProvider>
          <MetaSchemeEditor open schemes={[]} onClose={onClose} onChanged={onChanged} />
        </ToastProvider>
      </I18nProvider>,
    );
  });
}

afterEach(() => {
  act(() => root?.unmount());
  el?.remove();
  root = null;
  el = null;
  vi.clearAllMocks();
});

beforeEach(() => {
  apiMock.fns.metaCreateScheme = vi.fn(async () => ({ ok: true, id: 1, name: "scheme" }));
});

describe("MetaSchemeEditor", () => {
  it("adds a field, derives its name, edits dropdown options and saves", async () => {
    await render();

    // Add a field (bottom-left button) → the field pane opens on it.
    await act(async () => {
      buttonByText(tr("meta.addField"))?.click();
    });
    const section = document.querySelector("section") as HTMLElement;
    expect(control(tr("meta.fieldLabel"), section)).not.toBeNull();

    // A label derives the identifier automatically.
    await act(async () => {
      const label = control(tr("meta.fieldLabel"), section);
      if (label) setValue(label, "Sample size mean");
    });
    expect((control(tr("meta.fieldName"), section) as HTMLInputElement).value).toBe("sample_size_mean");

    // Choosing the dropdown editor reveals the option-list editor.
    await act(async () => {
      const editor = control(tr("meta.fieldEditor"), section);
      if (editor) setValue(editor, "select");
    });
    await act(async () => {
      buttonByText(tr("meta.addOption"), section)?.click();
    });
    const optionInput = section.querySelector('input[aria-label="' + tr("meta.optionPlaceholder") + '"]');
    expect(optionInput).not.toBeNull();
    await act(async () => {
      if (optionInput) setValue(optionInput as HTMLInputElement, "male");
    });

    // Name the scheme (left pane) and save.
    const aside = document.querySelector("aside") as HTMLElement;
    await act(async () => {
      const name = control(tr("meta.schemeName"), aside);
      if (name) setValue(name, "my-scheme");
    });
    await act(async () => {
      buttonByText(tr("common.save"))?.click();
    });

    expect(apiMock.fns.metaCreateScheme).toHaveBeenCalledTimes(1);
    const body = apiMock.fns.metaCreateScheme.mock.calls[0][0] as {
      name: string;
      codebook: { study_fields: Record<string, unknown>[] };
    };
    expect(body.name).toBe("my-scheme");
    expect(body.codebook.study_fields[0]).toMatchObject({
      name: "sample_size_mean",
      label: "Sample size mean",
      editor: "select",
      options: ["male"],
    });
    expect(onChanged).toHaveBeenCalled();
  });
});
