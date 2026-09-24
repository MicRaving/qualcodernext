// @vitest-environment jsdom
/**
 * MetaExtractionForm — the scheme-driven editor renders a control per codebook
 * field, derives per-metric completeness pills from the metric roles, supports
 * the "missing only" filter + raw JSON toggle, and saves through
 * `api.metaSaveExtraction`.
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

const CODEBOOK = {
  version: 2,
  category: "Meta",
  groups: [{ name: "Study", label: "Study" }],
  fields: [
    {
      name: "sample_n",
      label: "Sample N",
      group: "Study",
      type: "integer",
      editor: "number",
      required: true,
      description: "",
      role: "sample_n",
    },
    {
      name: "design",
      label: "Design",
      group: "Study",
      type: "string",
      editor: "select",
      required: false,
      description: "",
      options: ["between", "within"],
      role: null,
    },
  ],
  metrics: {
    enabled: true,
    group: "Metrics",
    label: "Effect sizes",
    fields: [
      {
        name: "yi",
        label: "Effect yi",
        group: "Metrics",
        type: "number",
        editor: "number",
        required: false,
        description: "",
        role: "yi",
      },
      {
        name: "vi",
        label: "Variance vi",
        group: "Metrics",
        type: "number",
        editor: "number",
        required: false,
        description: "",
        role: "vi",
      },
    ],
  },
  effect_families: ["yi"],
  code_fields: [],
};

const SCHEME: MetaScheme = {
  id: 1,
  name: "s",
  label: "Scheme S",
  codebook: JSON.stringify(CODEBOOK),
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
      records: [{ study: { sample_n: 10, design: "between" }, metrics: [{ yi: 0.5, vi: 0.04 }] }],
    },
    dv_metrics: [],
    status: "extracted",
    created: "",
    updated: "",
  };
}

let root: Root | null = null;
let el: HTMLDivElement | null = null;
const onSaved = vi.fn();

async function renderForm(ext: MetaExtraction) {
  el = document.createElement("div");
  document.body.appendChild(el);
  await act(async () => {
    root = createRoot(el as HTMLDivElement);
    root.render(
      <I18nProvider>
        <ToastProvider>
          <MetaExtractionForm extraction={ext} scheme={SCHEME} onSaved={onSaved} />
        </ToastProvider>
      </I18nProvider>,
    );
  });
}

function byAria(label: string) {
  return document.querySelector(`[aria-label="${label}"]`) as
    | HTMLInputElement
    | HTMLTextAreaElement
    | HTMLSelectElement
    | null;
}

function setValue(node: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null, value: string) {
  if (!node) return;
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

function buttonByText(text: string) {
  return (
    (Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent === text,
    ) as HTMLButtonElement | undefined) ?? null
  );
}

beforeEach(() => {
  // The endpoint wraps the saved row in an envelope; the form unwraps `.extraction`.
  apiMock.fns.metaSaveExtraction = vi.fn(async (body: { study_vars: MetaExtraction["study_vars"] }) => ({
    ok: true,
    id: 1,
    hit_id: 1,
    owner: "alice",
    status: "extracted",
    missing: [],
    extraction: { ...extraction(), study_vars: body.study_vars },
  }));
});

afterEach(() => {
  act(() => root?.unmount());
  el?.remove();
  root = null;
  el = null;
  vi.clearAllMocks();
});

describe("MetaExtractionForm", () => {
  it("renders scheme fields, shows a completeness pill and saves the edited metric", async () => {
    await renderForm(extraction());

    // Study + metric fields from the scheme are present.
    expect(byAria("Sample N")).not.toBeNull();
    expect(byAria("Design")).not.toBeNull();
    expect(byAria("Effect yi")).not.toBeNull();

    // yi + vi is a recognised fallback family (not full descriptives).
    expect(document.body.textContent).toContain(tr("meta.metric_fallback"));

    await act(async () => {
      setValue(byAria("Effect yi"), "0.7");
    });
    await act(async () => {
      buttonByText(tr("common.save"))?.click();
    });

    expect(apiMock.fns.metaSaveExtraction).toHaveBeenCalledTimes(1);
    const body = apiMock.fns.metaSaveExtraction.mock.calls[0][0] as {
      hit_id: number;
      study_vars: { records: { study: Record<string, unknown>; metrics: Record<string, unknown>[] }[] };
    };
    expect(body.hit_id).toBe(1);
    expect(body.study_vars.records[0].metrics[0].yi).toBe(0.7);
    expect(onSaved).toHaveBeenCalled();
  });

  it("adds key-value rows with a unique placeholder key", async () => {
    const kvBook = {
      ...CODEBOOK,
      fields: [
        {
          name: "notes_map",
          label: "Notes map",
          group: "Study",
          type: "object",
          editor: "kv",
          required: false,
          description: "",
          role: null,
        },
      ],
      metrics: { enabled: false, group: "Metrics", label: "Effect sizes", fields: [] },
    };
    const kvScheme: MetaScheme = { ...SCHEME, codebook: JSON.stringify(kvBook) };
    const ext = extraction();
    ext.study_vars = { records: [{ study: { notes_map: {} }, metrics: [] }] };
    el = document.createElement("div");
    document.body.appendChild(el);
    await act(async () => {
      root = createRoot(el as HTMLDivElement);
      root.render(
        <I18nProvider>
          <ToastProvider>
            <MetaExtractionForm extraction={ext} scheme={kvScheme} onSaved={onSaved} />
          </ToastProvider>
        </I18nProvider>,
      );
    });

    await act(async () => {
      buttonByText(tr("meta.kvAdd"))?.click();
    });
    // The placeholder key must be non-empty so a second entry can be added.
    const keys = document.querySelectorAll(
      `input[aria-label="${tr("meta.kvKey")}"]`,
    ) as NodeListOf<HTMLInputElement>;
    expect(keys.length).toBe(1);
    expect(keys[0].value).not.toBe("");

    await act(async () => {
      buttonByText(tr("meta.kvAdd"))?.click();
    });
    const keysAfter = document.querySelectorAll(
      `input[aria-label="${tr("meta.kvKey")}"]`,
    ) as NodeListOf<HTMLInputElement>;
    expect(keysAfter.length).toBe(2);
    expect(new Set(Array.from(keysAfter).map((k) => k.value)).size).toBe(2);
  });

  it("selects option N with a digit and advances to the next field", async () => {
    await renderForm(extraction());
    const design = byAria("Design") as HTMLSelectElement;
    design.focus();
    await act(async () => {
      design.dispatchEvent(
        new KeyboardEvent("keydown", { key: "2", bubbles: true, cancelable: true }),
      );
    });
    expect(design.value).toBe("within");
    expect(document.activeElement).toBe(byAria("Effect yi"));
  });

  it("moves between fields with Tab and Shift+Tab", async () => {
    await renderForm(extraction());
    const sample = byAria("Sample N") as HTMLInputElement;
    sample.focus();
    await act(async () => {
      sample.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }),
      );
    });
    expect(document.activeElement).toBe(byAria("Design"));
    const design = byAria("Design") as HTMLSelectElement;
    await act(async () => {
      design.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Tab",
          shiftKey: true,
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    expect(document.activeElement).toBe(byAria("Sample N"));
  });

  it("commits a number with Enter and advances", async () => {
    await renderForm(extraction());
    const yi = byAria("Effect yi") as HTMLInputElement;
    yi.focus();
    await act(async () => {
      yi.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }),
      );
    });
    expect(document.activeElement).toBe(byAria("Variance vi"));
  });

  it("flags incomplete metrics and supports the missing-only + raw toggles", async () => {
    const ext = extraction();
    ext.study_vars.records[0].metrics = [{ yi: 0.5 }];
    await renderForm(ext);

    expect(document.body.textContent).toContain(tr("meta.metric_incomplete"));

    await act(async () => {
      buttonByText(tr("meta.missingOnly"))?.click();
    });
    // The incomplete metric is still shown under the missing-only filter.
    expect(byAria("Effect yi")).not.toBeNull();

    await act(async () => {
      buttonByText(tr("meta.rawView"))?.click();
    });
    expect(document.body.textContent).toContain(tr("meta.studyVars"));
    expect(buttonByText(tr("meta.editorView"))).not.toBeNull();
  });
});
