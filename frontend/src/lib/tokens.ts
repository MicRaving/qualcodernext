/**
 * Typed access to the canonical design tokens (repo root: qualcoder-v4/tokens.json).
 */
import tokens from "../../../tokens.json";

export type ThemeMode = "light" | "dark";

export interface Tokens {
  colors: typeof tokens.colors;
  spacing: typeof tokens.spacing;
  radius: typeof tokens.radius;
  typography: typeof tokens.typography;
  icons: typeof tokens.icons;
  motion: typeof tokens.motion;
  shell: typeof tokens.shell;
}

export const designTokens: Tokens = tokens;

export function colorFor(mode: ThemeMode, key: keyof typeof tokens.colors): string {
  const palette = tokens.colors[key] as Record<ThemeMode, string>;
  return palette[mode];
}

export const codePalette: string[] = tokens.colors.code_palette.values;
