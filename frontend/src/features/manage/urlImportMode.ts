/**
 * URL -> scrape mode detection for the "Import from URL" dialog.
 *
 * Only unambiguous platform hosts auto-select a mode; anything else
 * returns ``null`` so the dialog keeps the current (possibly manual)
 * choice. Handles scheme-less pastes (``youtube.com/watch?v=...``) and
 * every ``www.``/``m.``/``old.``-style subdomain of the two platforms.
 */

export type ScrapeMode = "reddit" | "youtube" | "article" | "html" | "pdf";

export function detectModeFromUrl(url: string): ScrapeMode | null {
  const trimmed = url.trim();
  if (!trimmed) return null;
  let host: string;
  try {
    host = new URL(trimmed).hostname.toLowerCase();
  } catch {
    try {
      host = new URL(`https://${trimmed}`).hostname.toLowerCase();
    } catch {
      return null;
    }
  }
  if (host === "youtube.com" || host === "youtu.be" || host.endsWith(".youtube.com") || host.endsWith(".youtu.be")) {
    return "youtube";
  }
  if (host === "reddit.com" || host.endsWith(".reddit.com")) {
    return "reddit";
  }
  return null;
}
