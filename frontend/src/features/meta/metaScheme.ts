/**
 * Small read-only helpers for the codebook-v2 shape (contract §3) shared by the
 * analyze tab, the extraction editor and the screening panel. Kept separate so
 * MetaSchemeEditor stays the single editor while these stay pure readers.
 */
import type {
  FieldRole,
  MetaScheme,
  MetaSchemeCodebookV2,
  MetaEffectFamily,
  SchemeField,
} from "@/lib/api/types";

/** Parse a scheme's stored codebook (v1 or v2); null when unreadable. */
export function codebookOf(
  scheme: MetaScheme | null | undefined,
): MetaSchemeCodebookV2 | null {
  if (!scheme?.codebook) return null;
  try {
    const parsed = JSON.parse(scheme.codebook) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as MetaSchemeCodebookV2;
    }
  } catch {
    /* unreadable codebook — treated as absent */
  }
  return null;
}

export function studyFieldsOf(book: MetaSchemeCodebookV2 | null): SchemeField[] {
  if (!book) return [];
  const raw = book.study_fields ?? book.fields;
  return Array.isArray(raw) ? raw : [];
}

export function metricFieldsOf(book: MetaSchemeCodebookV2 | null): SchemeField[] {
  const fields = book?.metrics?.fields;
  return Array.isArray(fields) ? fields : [];
}

export function metricsEnabled(book: MetaSchemeCodebookV2 | null): boolean {
  if (!book) return false;
  return Boolean(book.metrics?.enabled) || metricFieldsOf(book).length > 0;
}

export function effectFamiliesOf(book: MetaSchemeCodebookV2 | null): MetaEffectFamily[] {
  return Array.isArray(book?.effect_families) ? (book?.effect_families ?? []) : [];
}

/** field name -> role (only fields that actually carry a role). */
export function roleMapOf(fields: SchemeField[]): Record<string, FieldRole> {
  const map: Record<string, FieldRole> = {};
  for (const field of fields) {
    if (field.role) map[field.name] = field.role;
  }
  return map;
}

/** First field value carrying `role` (mirrors backend `value_by_role`). */
export function valueByRole(
  record: Record<string, unknown> | null | undefined,
  roleMap: Record<string, FieldRole>,
  role: FieldRole,
): unknown {
  if (!record) return undefined;
  for (const [name, mapped] of Object.entries(roleMap)) {
    if (mapped === role && record[name] !== undefined) return record[name];
  }
  return undefined;
}

type MetricStatus = "complete" | "fallback" | "incomplete";

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * Frontend mirror of the backend completeness rule (contract §5): full
 * descriptives are complete; a recognised fallback family is `fallback`;
 * anything else is `incomplete`.
 */
export function metricStatus(
  metric: Record<string, unknown>,
  roleMap: Record<string, FieldRole>,
  families: MetaEffectFamily[] = [],
): { status: MetricStatus; reason: string } {
  const all = (roles: FieldRole[]) =>
    roles.every((role) => asNumber(valueByRole(metric, roleMap, role)) !== null);
  if (all(["n1", "m1", "sd1", "n2", "m2", "sd2"])) {
    return { status: "complete", reason: "" };
  }
  const has = (roles: FieldRole[]) =>
    roles.every((role) => valueByRole(metric, roleMap, role) !== undefined && valueByRole(metric, roleMap, role) !== "");
  if (
    (asNumber(valueByRole(metric, roleMap, "yi")) !== null &&
      (asNumber(valueByRole(metric, roleMap, "vi")) !== null ||
        asNumber(valueByRole(metric, roleMap, "sei")) !== null)) ||
    (has(["d"]) || has(["g"])) ||
    (all(["n1", "n2"]) && asNumber(valueByRole(metric, roleMap, "t")) !== null) ||
    (all(["n1", "n2"]) && asNumber(valueByRole(metric, roleMap, "F")) !== null) ||
    (has(["r"]) && asNumber(valueByRole(metric, roleMap, "n_total")) !== null) ||
    (has(["or"]) && (has(["or_ci_low"]) || has(["or_ci_high"]) || has(["log_odds"]))) ||
    (has(["rr"]) && (has(["or_ci_low"]) || has(["or_ci_high"]))) ||
    (asNumber(valueByRole(metric, roleMap, "eta2p")) !== null) ||
    (asNumber(valueByRole(metric, roleMap, "beta")) !== null &&
      asNumber(valueByRole(metric, roleMap, "beta_se")) !== null) ||
    (asNumber(valueByRole(metric, roleMap, "chi2")) !== null &&
      asNumber(valueByRole(metric, roleMap, "p")) !== null)
  ) {
    // The caller renders `meta.*` reasons through `t()`; raw `missing_reason`
    // values (user data) pass through unchanged.
    return { status: "fallback", reason: "meta.metricFallbackReason" };
  }
  const explicit = valueByRole(metric, roleMap, "missing_reason");
  const reason =
    explicit === undefined || explicit === "" || explicit === null
      ? "meta.metricIncompleteReason"
      : String(explicit);
  void families;
  return { status: "incomplete", reason };
}

/** True when a field's current value is empty (missing-data filter). */
export function isEmptyValue(_field: SchemeField, value: unknown): boolean {
  if (value === undefined || value === null || value === "") return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value as object).length === 0;
  return false;
}

/** Coerce an editor's raw string into the value type the field expects. */
export function coerceValue(field: SchemeField, value: unknown): unknown {
  const editor = field.editor;
  if (editor === "number") {
    if (value === "" || value === null || value === undefined) return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : value;
  }
  if (editor === "boolean") return Boolean(value);
  if (editor === "multiselect") {
    if (Array.isArray(value)) return value;
    if (!value) return [];
    return [value];
  }
  return value;
}
