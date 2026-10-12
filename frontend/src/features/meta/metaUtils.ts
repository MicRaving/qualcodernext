/**
 * Shared defensive readers for loosely-typed (or versioned) meta API payloads.
 *
 * The meta endpoints evolve (v1/v2 codebooks, envelope vs bare responses), so
 * the views degrade to an empty state instead of crashing on an unexpected
 * shape. These helpers were duplicated across the Analyze and Agreement views.
 */

/** The value as `T` only when it is a non-array object, else `null`. */
export function asObject<T>(value: unknown): T | null {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as T;
  return null;
}

/** The value as an array of `T`, else an empty array. */
export function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}
