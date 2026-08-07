/**
 * Locale tests — German must cover every English key; the generated locales
 * must be subsets of English (fallback) with a sane minimum of coverage.
 */
import { describe, expect, it } from "vitest";
import { en } from "@/lib/locales/en";
import { de } from "@/lib/locales/de";
import { es } from "@/lib/locales/es";
import { fr } from "@/lib/locales/fr";
import { eo } from "@/lib/locales/eo";
import { eu } from "@/lib/locales/eu";
import { fa } from "@/lib/locales/fa";
import { ht } from "@/lib/locales/ht";
import { it as itLocale } from "@/lib/locales/it";
import { ja } from "@/lib/locales/ja";
import { pt } from "@/lib/locales/pt";
import { ro } from "@/lib/locales/ro";
import { sv } from "@/lib/locales/sv";
import { zh } from "@/lib/locales/zh";

describe("de locale", () => {
  it("translates every English key", () => {
    const missing = Object.keys(en).filter((key) => !(key in de));
    expect(missing).toEqual([]);
  });

  it("contains no keys the English locale lacks", () => {
    const extra = Object.keys(de).filter((key) => !(key in en));
    expect(extra).toEqual([]);
  });

  it("keeps placeholders identical to the English values", () => {
    for (const key of Object.keys(en)) {
      const enTokens = en[key].match(/\{\w+\}/g) ?? [];
      const deTokens = de[key].match(/\{\w+\}/g) ?? [];
      expect(deTokens.sort(), key).toEqual(enTokens.sort());
    }
  });
});

describe("generated locales", () => {
  const generated = {
    es,
    fr,
    eo,
    eu,
    fa,
    ht,
    itLocale,
    ja,
    pt,
    ro,
    sv,
    zh,
  };

  for (const [lang, dict] of Object.entries(generated)) {
    it(`${lang} keys are a subset of English and keep placeholders`, () => {
      for (const [key, value] of Object.entries(dict)) {
        expect(key in en, `${lang}: unknown key ${key}`).toBe(true);
        const enTokens = en[key].match(/\{\w+\}/g) ?? [];
        const tokens = value.match(/\{\w+\}/g) ?? [];
        expect(tokens.sort(), `${lang}: placeholder mismatch in ${key}`).toEqual(enTokens.sort());
      }
    });

    it(`${lang} covers the core chrome keys`, () => {
      const core = [
        "nav.files",
        "nav.cases",
        "nav.settings",
        "common.save",
        "common.cancel",
        "common.delete",
        "common.close",
        "media.typeText",
        "media.typeImage",
        "settings.title",
        "sidebar.addCode",
        "nav.dashboard",
      ];
      const missing = core.filter((key) => !(key in dict));
      expect(missing, `${lang} missing core keys`).toEqual([]);
    });
  }
});
