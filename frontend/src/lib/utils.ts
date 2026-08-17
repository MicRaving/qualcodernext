import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn/ui class merge helper. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Extract a displayable error message from an unknown caught value. */
export function errorMessage(e: unknown, fallback = "Operation failed"): string {
  return e instanceof Error ? e.message : fallback;
}
