// @vitest-environment jsdom
/**
 * MetaExtractionForm audit regressions: the key/value editor keeps its row
 * mounted while the key is typed, the JSON editor does not re-pretty-print the
 * text the user is typing, and an emptied numeric object-list cell saves as
 * null rather than 0.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider, t as tr } from "@/lib/i18n";
import { ToastProvider } from "@/lib/toast";
import { MetaExtractionForm } from "@/features/meta/MetaExtractionForm";
import type { MetaExtraction, MetaScheme } from "@/lib/api/types";

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

const field = (name: string, editor: string, extra: Record<string, unknown> = {}) => ({
  name,
  label: name,
  group: "Study",
  type: "string",
  editor,
  required: false,
  description: "",
  role: null,
  ...extra,
});

const SCHEME: MetaScheme = {
  id: 1,
  name: "s",
  label: "Scheme S",
  codebook: JSON.stringify({
    version: 2,
    category: "Meta",
    groups: [{ name: "Study", label: "Study" }],
    fields: [
      field("tags", "kv"),
      field("blob", "json"),
      field("arms", "objectlist", { columns: [{ name: "n", type: "number" }] }),
    ],
    metrics: { enabled: false, group: "Metrics", label: "M", fields: [] },
    effect_families: [],
    code_fields: [],
  }),
  created: "",
  updated: "",
};

function extraction(): MetaExtraction {
  return {
    id: 1,
    hit_id: 1,
    owner: "alice",
    scheme: "s",
    study_vars: {
      records: [{ study: { tags: { a: "1" }, blob: null, arms: [{ n: 5 }] }, metrics: [] }],
    },
    dv_metrics: [],
    status: "extracted",
    created: "",
    updated: "",
  };
}

let root: Root | null = null;
let el: HTMLDivElement | null = null;

async function renderForm() {
  el = document.createElement("div");
  document.body.appendChild(el);
  await act(async () => {
    root = createRoot(el as HTMLDivElement);
    root.render(
      <I18nProvider>
        <ToastProvider>
          <MetaExtractionForm extraction={extraction()} scheme={SCHEME} onSaved={() => {}} />
        </ToastProvider>
      </I18nProvider>,
    );
  });
}

function byAria<T extends HTMLElement>(label: string): T {
  return document.querySelector(`[aria-label="${label}"]`) as T;
}

function setValue(node: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto =
    node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(node, value);
  node.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  apiMock.fns.metaSaveExtraction = vi.fn(async () => ({ ok: true }));
});

afterEach(() => {
  act(() => root?.unmount());
  el?.remove();
  root = null;
  el = null;
});

describe("MetaExtractionForm (audit)", () => {
  it("keeps the key/value row mounted while its key is edited", async () => {
    await renderForm();
    const keyInput = byAria<HTMLInputElement>(tr("meta.kvKey"));
    expect(keyInput.value).toBe("a");
    await act(async () => setValue(keyInput, "ab"));
    const after = byAria<HTMLInputElement>(tr("meta.kvKey"));
    expect(after).toBe(keyInput);
    expect(after.value).toBe("ab");
  });

  it("does not reformat valid JSON while it is being typed", async () => {
    await renderForm();
    const area = byAria<HTMLTextAreaElement>("blob");
    await act(async () => setValue(area, '{"a":1}'));
    expect(byAria<HTMLTextAreaElement>("blob").value).toBe('{"a":1}');
  });

  it("saves an emptied numeric object-list cell as null, not 0", async () => {
    await renderForm();
    await act(async () => setValue(byAria<HTMLInputElement>("n 1"), ""));
    const save = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent === tr("common.save"),
    ) as HTMLButtonElement;
    await act(async () => save.click());
    const body = apiMock.fns.metaSaveExtraction.mock.calls[0][0] as {
      study_vars: { records: { study: { arms: { n: unknown }[] } }[] };
    };
    expect(body.study_vars.records[0].study.arms[0].n).toBeNull();
  });
});
