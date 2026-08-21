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

describe("collaboration endpoints", () => {
  it("reads the project mode", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ mode: "collaboration", uuid: "abc123" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const res = await api.projectMode();
    expect(res.mode).toBe("collaboration");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/projects/mode");
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("activates collaboration via POST", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, reason: "ok", uuid: "xyz" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const res = await api.activateCollaboration();
    expect(res.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/projects/activate-collaboration");
    expect(init?.method).toBe("POST");
  });

  it("reverts and consolidates via POST", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, reason: "ok" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, reason: "ok" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.revertCollaboration()).resolves.toMatchObject({ ok: true });
    expect(String(fetchMock.mock.calls[0][0])).toContain("/projects/revert-collaboration");
    await expect(api.consolidateProject()).resolves.toMatchObject({ ok: true });
    expect(String(fetchMock.mock.calls[1][0])).toContain("/projects/consolidate");
  });
});

describe("aiMcpTools endpoint", () => {
  it("fetches the MCP tool catalog from /ai/mcp-tools", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          permissions: "write",
          write_enabled: true,
          read_tools: [{ name: "get_code_tree", description: "codebook" }],
          write_tools: [{ name: "create_code", description: "create" }],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const res = await api.aiMcpTools();
    expect(res.write_enabled).toBe(true);
    expect(res.read_tools[0].name).toBe("get_code_tree");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/ai/mcp-tools");
    expect(init?.method ?? "GET").toBe("GET");
  });
});
