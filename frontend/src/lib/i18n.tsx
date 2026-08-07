/**
 * Minimal internationalization (no dependencies).
 *
 * English ships as the reference locale; German is fully translated and the
 * remaining upstream languages (es, fr, eo, eu, fa, ht, it, ja, pt, ro, sv,
 * zh) are generated from the upstream gettext .po files. Missing keys fall
 * back to the English dictionary so partial locales stay usable.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { en } from "@/lib/locales/en";
import { de } from "@/lib/locales/de";
import { es } from "@/lib/locales/es";
import { fr } from "@/lib/locales/fr";
import { eo } from "@/lib/locales/eo";
import { eu } from "@/lib/locales/eu";
import { fa } from "@/lib/locales/fa";
import { ht } from "@/lib/locales/ht";
import { it } from "@/lib/locales/it";
import { ja } from "@/lib/locales/ja";
import { pt } from "@/lib/locales/pt";
import { ro } from "@/lib/locales/ro";
import { sv } from "@/lib/locales/sv";
import { zh } from "@/lib/locales/zh";

export type Locale =
  | "en"
  | "de"
  | "es"
  | "fr"
  | "eo"
  | "eu"
  | "fa"
  | "ht"
  | "it"
  | "ja"
  | "pt"
  | "ro"
  | "sv"
  | "zh";

const LOCALES: Record<Locale, Record<string, string>> = {
  en,
  de,
  es,
  fr,
  eo,
  eu,
  fa,
  ht,
  it,
  ja,
  pt,
  ro,
  sv,
  zh,
};

/** Native display names for the language switcher. */
// eslint-disable-next-line react-refresh/only-export-components
export const LOCALE_NAMES: Record<Locale, string> = {
  en: "English",
  de: "Deutsch",
  es: "Español",
  fr: "Français",
  eo: "Esperanto",
  eu: "Euskara",
  fa: "فارسی",
  ht: "Kreyòl ayisyen",
  it: "Italiano",
  ja: "日本語",
  pt: "Português",
  ro: "Română",
  sv: "Svenska",
  zh: "中文",
};

const LOCALE_KEY = "qc-locale";

const LOCALE_IDS = Object.keys(LOCALES) as Locale[];

function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && LOCALE_IDS.includes(value as Locale);
}

function loadLocale(): Locale {
  if (typeof window === "undefined") return "en";
  const saved = window.localStorage.getItem(LOCALE_KEY);
  return isLocale(saved) ? saved : "en";
}

/** Resolve a dot-path key in a flat dictionary; unknown keys yield undefined. */
function lookup(dict: Record<string, string>, key: string): string | undefined {
  return Object.prototype.hasOwnProperty.call(dict, key) ? dict[key] : undefined;
}

/** Replace `{name}` placeholders from params; absent params keep their token. */
function interpolate(value: string, params?: Record<string, string | number>): string {
  if (!params) return value;
  return value.replace(/\{(\w+)\}/g, (token, name: string) =>
    name in params ? String(params[name]) : token,
  );
}

export function translate(
  dict: Record<string, string>,
  key: string,
  params?: Record<string, string | number>,
): string {
  let value = lookup(dict, key);
  if (value === undefined && dict !== en) {
    // Fall back to the reference locale before giving up on the key.
    value = lookup(en, key);
  }
  return value === undefined ? key : interpolate(value, params);
}

/** Translate using the persisted locale (safe outside React). */
export function t(key: string, params?: Record<string, string | number>): string {
  return translate(LOCALES[loadLocale()], key, params);
}

function createTranslator(dict: Record<string, string>): typeof t {
  return (key, params) => translate(dict, key, params);
}

export interface I18nApi {
  t: typeof t;
  locale: Locale;
  setLocale(locale: Locale): void;
}

const I18nContext = createContext<I18nApi | null>(null);

export function useI18n(): I18nApi {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within an I18nProvider");
  }
  return ctx;
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(loadLocale);

  const setLocale = useCallback((next: Locale) => {
    window.localStorage.setItem(LOCALE_KEY, next);
    setLocaleState(next);
  }, []);

  const value = useMemo<I18nApi>(
    () => ({ t: createTranslator(LOCALES[locale]), locale, setLocale }),
    [locale, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
