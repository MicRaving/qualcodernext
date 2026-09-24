// @vitest-environment jsdom
/**
 * MetaCriteriaEditor — the reusable criterion editor emits the extended v2
 * payload (kind/options/pass values/exclusion reason/gating/help), derives a
 * stable key from the label, and supports reorder + delete.
 */
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider, t as tr } from "@/lib/i18n";
import {
  MetaCriteriaEditor,
  type MetaCriterionDraft,
} from "@/features/meta/MetaCriteriaEditor";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let el: HTMLDivElement | null = null;
let latest: MetaCriterionDraft[] = [];

function Harness() {
  const [value, setValue] = useState<MetaCriterionDraft[]>([]);
  return (
    <MetaCriteriaEditor
      value={value}
      onChange={(next) => {
        latest = next;
        setValue(next);
      }}
    />
  );
}

function byAria(label: string, index = 0) {
  return (document.querySelectorAll(`[aria-label="${label}"]`)[index] ?? null) as
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
  return Array.from(document.querySelectorAll("button")).find((b) => b.textContent === text) ?? null;
}

function ariaButton(label: string, index = 0) {
  return (document.querySelectorAll(`button[aria-label="${label}"]`)[index] ?? null) as
    | HTMLButtonElement
    | null;
}

async function render() {
  el = document.createElement("div");
  document.body.appendChild(el);
  await act(async () => {
    root = createRoot(el as HTMLDivElement);
    root.render(
      <I18nProvider>
        <Harness />
      </I18nProvider>,
    );
  });
}

beforeEach(() => {
  latest = [];
});

afterEach(() => {
  act(() => root?.unmount());
  el?.remove();
  root = null;
  el = null;
  vi.clearAllMocks();
});

describe("MetaCriteriaEditor", () => {
  it("adds a criterion and emits the extended v2 payload", async () => {
    await render();
    await act(async () => {
      buttonByText(tr("meta.addCriterion"))?.click();
    });

    expect(latest).toHaveLength(1);
    expect(latest[0]).toMatchObject({
      kind: "verdict",
      options: [],
      pass_values: ["yes"],
      gating: true,
      exclude_reason: "",
      help: "",
    });

    await act(async () => {
      setValue(byAria(tr("meta.criterionLabel")), "Randomised allocation");
    });
    expect(latest[0].label).toBe("Randomised allocation");
    expect(latest[0].key).toBe("randomised_allocation");
  });

  it("edits kind, options, pass values, exclusion reason, gating and help", async () => {
    await render();
    await act(async () => {
      buttonByText(tr("meta.addCriterion"))?.click();
    });
    await act(async () => {
      setValue(byAria(tr("meta.criterionLabel")), "Design");
    });
    await act(async () => {
      setValue(byAria(tr("meta.criterionKind")), "classify");
    });
    expect(latest[0].kind).toBe("classify");

    // The options editor is rendered before the pass-values editor.
    await act(async () => {
      buttonByText(tr("meta.addOption"))?.click();
    });
    const optionInputs = document.querySelectorAll(
      'input[aria-label="' + tr("meta.optionPlaceholder") + '"]',
    );
    expect(optionInputs.length).toBe(2);
    await act(async () => {
      setValue(optionInputs[0] as HTMLInputElement, "between");
    });
    await act(async () => {
      setValue(optionInputs[1] as HTMLInputElement, "between");
    });
    expect(latest[0].options).toEqual(["between"]);
    expect(latest[0].pass_values).toEqual(["between"]);

    await act(async () => {
      setValue(byAria(tr("meta.criterionExcludeReason")), "Not an experiment");
    });
    expect(latest[0].exclude_reason).toBe("Not an experiment");

    await act(async () => {
      setValue(byAria(tr("meta.criterionHelp")), "Check the methods section.");
    });
    expect(latest[0].help).toBe("Check the methods section.");

    await act(async () => {
      const toggle = document.querySelector(
        `[role="switch"][aria-label="${tr("meta.criterionGating")}"]`,
      ) as HTMLButtonElement | null;
      toggle?.click();
    });
    expect(latest[0].gating).toBe(false);
  });

  it("reorders and deletes criteria", async () => {
    await render();
    await act(async () => {
      buttonByText(tr("meta.addCriterion"))?.click();
    });
    await act(async () => {
      setValue(byAria(tr("meta.criterionLabel"), 0), "First");
    });
    await act(async () => {
      buttonByText(tr("meta.addCriterion"))?.click();
    });
    await act(async () => {
      setValue(byAria(tr("meta.criterionLabel"), 1), "Second");
    });
    expect(latest.map((c) => c.label)).toEqual(["First", "Second"]);

    await act(async () => {
      ariaButton(tr("meta.moveDown"), 0)?.click();
    });
    expect(latest.map((c) => c.label)).toEqual(["Second", "First"]);

    await act(async () => {
      ariaButton(tr("common.delete"), 0)?.click();
    });
    expect(latest).toHaveLength(1);
    expect(latest[0].label).toBe("First");
  });
});
