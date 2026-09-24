// @vitest-environment jsdom
/**
 * MetaSchemeEditor — the reworked editor must let a field be labelled, given a
 * dropdown editor with options, carry a role, expand effect-size families into
 * metric fields, and save a codebook-v2 payload the publish step understands
 * (``study_fields`` alias kept alongside ``fields``).
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

function switchByLabel(label: string, rootNode: ParentNode = document) {
  return rootNode.querySelector(`[role="switch"][aria-label="${label}"]`) as HTMLButtonElement | null;
}

function checkboxByLabel(label: string, rootNode: ParentNode = document) {
  const wrapper = Array.from(rootNode.querySelectorAll("label")).find((l) =>
    (l.textContent ?? "").includes(label),
  );
  return (wrapper?.querySelector('input[type="checkbox"]') ?? null) as HTMLInputElement | null;
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

/** Name the scheme in the left pane and click save. */
async function nameAndSave(name = "my-scheme") {
  const aside = document.querySelector("aside") as HTMLElement;
  await act(async () => {
    const input = control(tr("meta.schemeName"), aside);
    if (input) setValue(input, name);
  });
  await act(async () => {
    buttonByText(tr("common.save"))?.click();
  });
}

function savedCodebook() {
  const body = apiMock.fns.metaCreateScheme.mock.calls[0][0] as {
    name: string;
    codebook: {
      version: number;
      groups: { name: string; label: string }[];
      study_fields: Record<string, unknown>[];
      fields: Record<string, unknown>[];
      metrics: { enabled: boolean; fields: Record<string, unknown>[] };
      effect_families: string[];
    };
  };
  return body;
}

describe("MetaSchemeEditor", () => {
  it("adds a field, derives its name, edits dropdown options and saves a v2 codebook", async () => {
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

    await nameAndSave();

    expect(apiMock.fns.metaCreateScheme).toHaveBeenCalledTimes(1);
    const body = savedCodebook();
    expect(body.name).toBe("my-scheme");
    expect(body.codebook.version).toBe(2);
    expect(body.codebook.groups).toEqual([{ name: "Study", label: "Study" }]);
    expect(body.codebook.study_fields[0]).toMatchObject({
      name: "sample_size_mean",
      label: "Sample size mean",
      editor: "select",
      options: ["male"],
    });
    // v1 alias keeps the publish path working.
    expect(body.codebook.fields).toEqual(body.codebook.study_fields);
    expect(body.codebook.metrics).toMatchObject({ enabled: false, fields: [] });
    expect(onChanged).toHaveBeenCalled();
  });

  it("assigns a controlled role to a field", async () => {
    await render();
    await act(async () => {
      buttonByText(tr("meta.addField"))?.click();
    });
    const section = document.querySelector("section") as HTMLElement;
    await act(async () => {
      const label = control(tr("meta.fieldLabel"), section);
      if (label) setValue(label, "Group 1 mean");
    });
    await act(async () => {
      const role = control(tr("meta.fieldRole"), section);
      if (role) setValue(role, "m1");
    });
    await nameAndSave("roles");

    const body = savedCodebook();
    expect(body.codebook.study_fields[0]).toMatchObject({ name: "group_1_mean", role: "m1" });
  });

  it("expands an enabled effect-size family into editable metric fields", async () => {
    await render();
    const aside = document.querySelector("aside") as HTMLElement;

    await act(async () => {
      checkboxByLabel(tr("meta.family_descriptives"), aside)?.click();
    });
    await act(async () => {
      buttonByText(tr("meta.addStandardFields"), aside)?.click();
    });
    await nameAndSave("effects");

    const body = savedCodebook();
    expect(body.codebook.effect_families).toContain("descriptives");
    expect(body.codebook.metrics.enabled).toBe(true);
    const metrics = body.codebook.metrics.fields;
    expect(metrics.map((f) => f.name)).toEqual(["n1i", "m1i", "sd1i", "n2i", "m2i", "sd2i"]);
    expect(metrics[0]).toMatchObject({ name: "n1i", role: "n1", editor: "number" });
    expect(metrics[5]).toMatchObject({ name: "sd2i", role: "sd2" });
  });

  it("enables the metrics section and adds a custom metric field", async () => {
    await render();
    const aside = document.querySelector("aside") as HTMLElement;

    await act(async () => {
      switchByLabel(tr("meta.metricsSection"), aside)?.click();
    });
    await act(async () => {
      buttonByText(tr("meta.addMetricField"), aside)?.click();
    });

    const section = document.querySelector("section") as HTMLElement;
    await act(async () => {
      const label = control(tr("meta.fieldLabel"), section);
      if (label) setValue(label, "Custom effect");
    });
    await act(async () => {
      const role = control(tr("meta.fieldRole"), section);
      if (role) setValue(role, "yi");
    });
    // The moderator opt-in applies to metric fields too, on by default.
    const moderator = checkboxByLabel(tr("meta.useAsModerator"), section);
    expect(moderator).not.toBeNull();
    expect(moderator?.checked).toBe(true);
    await nameAndSave("custom-metric");

    const body = savedCodebook();
    expect(body.codebook.metrics).toMatchObject({ enabled: true });
    expect(body.codebook.metrics.fields[0]).toMatchObject({
      name: "custom_effect",
      role: "yi",
      group: "Metrics",
      moderator: true,
    });
  });

  it("lets a field opt out of being used as a moderator", async () => {
    await render();
    await act(async () => {
      buttonByText(tr("meta.addField"))?.click();
    });
    const section = document.querySelector("section") as HTMLElement;
    await act(async () => {
      const label = control(tr("meta.fieldLabel"), section);
      if (label) setValue(label, "Country");
    });

    // The checkbox defaults to checked; unchecking emits `moderator: false`.
    const moderator = checkboxByLabel(tr("meta.useAsModerator"), section);
    expect(moderator).not.toBeNull();
    expect(moderator?.checked).toBe(true);
    await act(async () => {
      moderator?.click();
    });

    await nameAndSave("not-a-moderator");
    const body = savedCodebook();
    expect(body.codebook.study_fields[0]).toMatchObject({ name: "country", moderator: false });
  });
});
