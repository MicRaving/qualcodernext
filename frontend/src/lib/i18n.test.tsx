// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { I18nProvider, t, useI18n, type Locale } from "@/lib/i18n";
import { en } from "@/lib/locales/en";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function LocaleProbe() {
  const { t: translate, locale } = useI18n();
  return (
    <span>
      {locale}:{translate("nav.files")}
    </span>
  );
}

function SetLocaleProbe({ locale }: { locale: Locale }) {
  const { setLocale } = useI18n();
  return (
    <button type="button" onClick={() => setLocale(locale)}>
      set-{locale}
    </button>
  );
}

function ThrowProbe() {
  useI18n();
  return null;
}

describe("t()", () => {
  it("resolves dot-path keys", () => {
    expect(t("welcome.recentProjects")).toBe("Recent projects");
    expect(t("nav.interchange")).toBe("Import/Export");
    expect(t("settings.aiAssistant")).toBe("AI assistant");
  });

  it("returns the key itself when missing", () => {
    expect(t("no.such.key")).toBe("no.such.key");
    expect(t("nav")).toBe("nav");
    expect(t("")).toBe("");
  });

  it("interpolates {name} params", () => {
    expect(t("shell.summary", { codes: 12, files: 34 })).toBe("12 codes · 34 files");
    expect(t("theme.switchLabel", { theme: "dark" })).toBe("Switch to dark theme");
    expect(t("backend.ok", { status: "ok" })).toBe("Backend ok");
  });

  it("keeps placeholders for missing params and ignores extras", () => {
    expect(t("shell.summary", { codes: 1 })).toBe("1 codes · {files} files");
    expect(t("shell.summary", { codes: 1, files: 2, extra: "x" })).toBe("1 codes · 2 files");
  });

  it("treats numeric params as strings", () => {
    expect(t("shell.summary", { codes: 0, files: 7 })).toBe("0 codes · 7 files");
  });
});

describe("I18nProvider", () => {
  it("defaults to locale 'en' and translates through context", () => {
    const html = renderToStaticMarkup(
      <I18nProvider>
        <LocaleProbe />
      </I18nProvider>,
    );
    expect(html).toContain("en:Files");
  });

  it("persists setLocale to localStorage", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    act(() => {
      root.render(
        <I18nProvider>
          <SetLocaleProbe locale="en" />
        </I18nProvider>,
      );
    });
    container.querySelector("button")?.click();
    expect(window.localStorage.getItem("qc-locale")).toBe("en");
    act(() => root.unmount());
    container.remove();
  });

  it("loads the persisted locale on mount", () => {
    window.localStorage.setItem("qc-locale", "en");
    const html = renderToStaticMarkup(
      <I18nProvider>
        <LocaleProbe />
      </I18nProvider>,
    );
    expect(html).toContain("en:Files");
  });

  it("falls back to 'en' when the persisted value is invalid", () => {
    window.localStorage.setItem("qc-locale", "xx-invalid");
    const html = renderToStaticMarkup(
      <I18nProvider>
        <LocaleProbe />
      </I18nProvider>,
    );
    expect(html).toContain("en:Files");
  });

  it("context value is stable across re-renders (memoized)", () => {
    const seen: unknown[] = [];
    function SnapshotProbe() {
      const i18n = useI18n();
      seen.push(i18n);
      return null;
    }
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    act(() => {
      root.render(
        <I18nProvider>
          <SnapshotProbe />
        </I18nProvider>,
      );
    });
    act(() => {
      root.render(
        <I18nProvider>
          <SnapshotProbe />
        </I18nProvider>,
      );
    });
    expect(seen.length).toBeGreaterThanOrEqual(2);
    expect(seen[0]).toBe(seen[1]);
    act(() => root.unmount());
    container.remove();
  });
});

describe("useI18n", () => {
  it("throws when used outside an I18nProvider", () => {
    expect(() => renderToStaticMarkup(<ThrowProbe />)).toThrow(
      "useI18n must be used within an I18nProvider",
    );
  });
});

describe("en dictionary", () => {
  it("has unique keys and non-empty string values", () => {
    const keys = Object.keys(en);
    expect(new Set(keys).size).toBe(keys.length);
    for (const [key, value] of Object.entries(en)) {
      expect(key.length, key).toBeGreaterThan(0);
      expect(value.length, key).toBeGreaterThan(0);
    }
  });
});

afterEach(() => {
  window.localStorage.clear();
});
