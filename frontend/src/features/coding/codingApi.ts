/**
 * Local-fetch client for coding-segment weight updates.
 *
 * The weight PATCH calls (text/image/AV) are not in lib/api.ts, so they
 * follow the same local-fetch pattern as statsApi.ts: initApiBase +
 * fetchWithTimeout, with a single retry on network-level failure (the
 * packaged backend may have restarted on a new port).
 */

import { ApiError, fetchWithTimeout, initApiBase } from "@/lib/api";

export type CodingKind = "text" | "image" | "av";

const PATCH_PATHS: Record<CodingKind, (id: number) => string> = {
  text: (id) => `/codings/text/${id}`,
  image: (id) => `/codings/image/${id}`,
  av: (id) => `/codings/av/${id}`,
};

/** PATCH a segment's weight (0-100; 0 = no weight) and return the row. */
export async function patchCodingWeight(
  kind: CodingKind,
  id: number,
  weight: number,
): Promise<unknown> {
  const path = PATCH_PATHS[kind](id);
  const doFetch = async (): Promise<unknown> => {
    const base = await initApiBase();
    const res = await fetchWithTimeout(`${base}${path}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ weight }),
    });
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = (await res.json()).detail;
      } catch {
        /* non-JSON error body */
      }
      const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
      throw new ApiError(res.status, `API error ${res.status} on ${path}${suffix}`, detail);
    }
    return (await res.json()) as unknown;
  };
  try {
    return await doFetch();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    // Network-level failure (packaged backend restarted): retry once so the
    // base URL is resolved afresh.
    return doFetch();
  }
}
