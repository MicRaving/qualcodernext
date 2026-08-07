/**
 * Media helpers matching backend semantics (core/enums.py).
 */

export function isPdf(filename: string): boolean {
  return filename.toLowerCase().endsWith(".pdf");
}

/** True when a source should open in the PDF coder. */
export function usesPdfCoder(source: { name: string; media_type: string }): boolean {
  return source.media_type === "text" && isPdf(source.name);
}
