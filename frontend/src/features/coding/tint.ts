/**
 * Coded-region fill styling: the code's color used as a translucent tint.
 *
 * The alpha is the canonical design token `colors.coding_alpha` (tokens.json).
 */
import { colorFor } from "@/lib/tokens";

/** Fallback color when a code has no explicit color. */
export const FALLBACK_CODE_COLOR = "var(--qc-accent)";

export const CODING_ALPHA = parseFloat(colorFor("light", "coding_alpha"));

/** Code color at the shared coding alpha over the background. */
export function codeTint(color: string): string {
  return `color-mix(in srgb, ${color} ${Math.round(CODING_ALPHA * 100)}%, transparent)`;
}
