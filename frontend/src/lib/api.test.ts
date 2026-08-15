// @vitest-environment jsdom
/**
 * Error-path tests for the API client: backend 500s must surface as
 * readable ApiErrors carrying the JSON `detail` (FastAPI) — never as a
 * bare "Failed to fetch" — and transport-level failures must retry once
 * against a freshly resolved base before giving up with a clear message.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, fetchSourceFile } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request error-body parsing", () => {
  it("parses the JSON detail of a 500 into the ApiError (no retry for HTTP errors)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "internal error: RuntimeError: boom" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.sources()).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      detail: "internal error: RuntimeError: boom",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("parses the detail on the retry attempt after a network failure", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "internal error: RuntimeError: boom" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.sources()).rejects.toMatchObject({
      status: 500,
      detail: "internal error: RuntimeError: boom",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("wraps a double transport failure in a readable ApiError instead of 'Failed to fetch'", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.sources()).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      message: "Backend unreachable — Failed to fetch",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("fetchSourceFile error-body parsing", () => {
  it("throws an ApiError carrying the backend detail on a 500", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "internal error: boom" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchSourceFile(1)).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      detail: "internal error: boom",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("resolves the response on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("pdf-bytes", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await fetchSourceFile(1);
    expect(res.ok).toBe(true);
    expect(await res.text()).toBe("pdf-bytes");
  });
});
