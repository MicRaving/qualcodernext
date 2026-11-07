// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { invalidateApiBase, localRequest } from "@/lib/api/transport";

afterEach(() => {
  vi.unstubAllGlobals();
  invalidateApiBase();
});

describe("localRequest retry (audit)", () => {
  it("does not re-send a request whose 2xx body fails to parse", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError("Unexpected token <");
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(localRequest("/x", { method: "POST", body: "{}" })).rejects.toBeInstanceOf(SyntaxError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("still retries once on a transport failure", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({ a: 1 }) });
    vi.stubGlobal("fetch", fetchMock);
    await expect(localRequest("/x")).resolves.toEqual({ a: 1 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
