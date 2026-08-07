import { describe, expect, it } from "vitest";
import { addToast, removeToast, type Toast } from "@/lib/toast-core";

describe("toast core", () => {
  it("addToast appends a toast with a fresh id", () => {
    const next = addToast([], "success", "hello");
    expect(next).toHaveLength(1);
    expect(next[0]?.kind).toBe("success");
    expect(next[0]?.message).toBe("hello");
    expect(next[0]?.id).toBeGreaterThan(0);
  });

  it("removeToast filters out the toast with the given id", () => {
    const a: Toast = { id: 1, kind: "info", message: "a" };
    const b: Toast = { id: 2, kind: "error", message: "b" };
    const next = removeToast([a, b], 1);
    expect(next).toEqual([b]);
  });

  it("auto ids increment across calls", () => {
    const first = addToast([], "success", "one")[0];
    const second = addToast([], "info", "two")[0];
    const third = addToast([], "error", "three")[0];
    expect(second?.id).toBe((first?.id ?? 0) + 1);
    expect(third?.id).toBe((second?.id ?? 0) + 1);
  });

  it("removeToast is a no-op for an unknown id", () => {
    const a: Toast = { id: 5, kind: "info", message: "a" };
    expect(removeToast([a], 99)).toEqual([a]);
  });
});
