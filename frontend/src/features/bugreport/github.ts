/**
 * GitHub submission helpers for the bug report (no dependencies).
 *
 * Two paths:
 *  - Token configured (OPTIONAL): upload the screenshot through the issues
 *    web editor's attachment endpoint, then POST the issue via the REST API.
 *  - No token (the default): build the prefilled `issues/new` URL and open
 *    it in the system browser via `openExternal` — no account or token is
 *    needed inside QCnext; the user completes the issue on GitHub (and can
 *    attach the screenshot downloaded from the report view).
 */

/** Whether the app runs inside the Tauri WebView2 shell (vs. dev browser). */
function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * Open a URL in the system browser.
 *
 * Packaged app: Tauri's WebView2 blocks `window.open` popups, so the opener
 * plugin's `openUrl` is used (permission `opener:default`, registered in
 * `src-tauri/capabilities/default.json`). Dev/browser: falls back to
 * `window.open` (the plugin is only imported when running under Tauri).
 *
 * Throws when the browser cannot be opened (popup blocked / plugin error).
 */
export async function openExternal(url: string): Promise<void> {
  if (inTauri()) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
    return;
  }
  const win = window.open(url, "_blank", "noopener,noreferrer");
  if (!win) throw new Error("The browser could not be opened (popup blocked)");
}

export interface GitHubIssueDraft {
  title: string;
  body: string;
  labels: string[];
  assignee: string;
  milestone: string;
}

/** Default target repository — derived from the updater manifest's endpoint
 *  (tauri.conf.json → plugins.updater.endpoints, github.com/MicRaving/QCnext). */
export const DEFAULT_GITHUB_REPO = "MicRaving/QCnext";

/** Normalize an "owner/repo" string (strips scheme/host noise). */
export function splitRepo(repo: string): { owner: string; name: string } {
  const clean = repo.trim().replace(/^https?:\/\/[^/]+\//, "").replace(/\.git$/, "");
  const [owner, ...rest] = clean.split("/");
  const name = rest.join("/") || owner;
  return { owner: owner ?? "", name: name || "" };
}

/** Parse a non-ok GitHub response into a readable error message. */
async function githubError(res: Response, fallback: string): Promise<string> {
  try {
    const data = (await res.json()) as {
      message?: string;
      errors?: { message?: string }[];
    };
    if (typeof data.message === "string") {
      const detail = (data.errors ?? [])
        .map((e) => e.message)
        .filter(Boolean)
        .join("; ");
      return detail ? `${data.message} (${detail})` : data.message;
    }
  } catch {
    /* non-JSON error body */
  }
  return `${fallback} (HTTP ${res.status})`;
}

/**
 * Upload an image to the issue composer's attachment store:
 * `POST https://github.com/{owner}/{repo}/issues/attachments` (multipart,
 * bearer token). The endpoint is the same one the issues web editor uses;
 * it is not part of the public REST docs. On success it returns a markdown
 * image snippet (or the fields to build one) — verify the response shape
 * defensively and fall back to a data-URI embed when anything is off.
 */
export async function uploadIssueAttachment(
  repo: string,
  file: Blob,
  fileName: string,
  token: string,
): Promise<string | null> {
  const { owner, name } = splitRepo(repo);
  if (!owner || !name) throw new Error("Invalid repository");
  const form = new FormData();
  form.append("file", file, fileName);
  const res = await fetch(`https://github.com/${owner}/${name}/issues/attachments`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    throw new Error(await githubError(res, "Screenshot upload failed"));
  }
  let data: unknown;
  try {
    data = await res.json();
  } catch {
    throw new Error("Screenshot upload returned no usable response");
  }
  const obj = Array.isArray(data) ? (data[0] ?? {}) : (data as Record<string, unknown>);
  if (typeof obj.markdown === "string" && obj.markdown) return obj.markdown;
  if (typeof obj.url === "string" && obj.url) {
    const name = typeof obj.name === "string" && obj.name ? obj.name : fileName;
    return `![${name}](${obj.url})`;
  }
  return null;
}

export interface GitHubIssueResult {
  htmlUrl: string;
  number: number;
}

/** POST /repos/{owner}/{repo}/issues with the draft + bearer token. */
export async function createGitHubIssue(
  repo: string,
  draft: GitHubIssueDraft,
  token: string,
): Promise<GitHubIssueResult> {
  const { owner, name } = splitRepo(repo);
  if (!owner || !name) throw new Error("Invalid repository");
  const payload: Record<string, unknown> = {
    title: draft.title,
    body: draft.body,
    labels: draft.labels.filter((l) => l.trim() !== ""),
  };
  if (draft.assignee.trim()) payload.assignees = [draft.assignee.trim()];
  if (draft.milestone.trim()) payload.milestone = draft.milestone.trim();
  const res = await fetch(`https://api.github.com/repos/${owner}/${name}/issues`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await githubError(res, "Could not create the GitHub issue"));
  }
  const data = (await res.json()) as { html_url?: string; number?: number };
  if (typeof data.html_url !== "string" || !data.html_url) {
    throw new Error("GitHub did not return an issue URL");
  }
  return { htmlUrl: data.html_url, number: data.number ?? 0 };
}

/** The `issues/new` fallback URL with the prefilled title + body. */
export function githubNewIssueUrl(repo: string, title: string, body: string): string {
  const { owner, name } = splitRepo(repo);
  const params = new URLSearchParams();
  if (title) params.set("title", title);
  if (body) params.set("body", body);
  return `https://github.com/${owner}/${name}/issues/new?${params.toString()}`;
}
