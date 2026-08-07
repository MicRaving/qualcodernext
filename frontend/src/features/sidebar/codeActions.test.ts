import { describe, expect, it } from "vitest";
import type { CodeTreeItem } from "@/lib/api";
import { clampToViewport, matchTargetByName } from "@/features/sidebar/codeActions";

function makeItem(overrides: Partial<CodeTreeItem>): CodeTreeItem {
  return {
    kind: "code",
    id: 1,
    name: "Theme",
    color: null,
    parent_id: null,
    memo: "",
    ...overrides,
  };
}

const TREE: CodeTreeItem[] = [
  makeItem({ kind: "category", id: 1, name: "Interviews" }),
  makeItem({ kind: "code", id: 2, name: "Happiness", parent_id: 1 }),
  makeItem({ kind: "code", id: 3, name: "happiness", parent_id: 1 }),
  makeItem({ kind: "category", id: 4, name: "Happiness" }),
];

describe("matchTargetByName", () => {
  it("finds a code by exact name, case-insensitively", () => {
    expect(matchTargetByName(TREE, "HAPPINESS")).toBe(2);
    expect(matchTargetByName(TREE, "happiness")).toBe(2);
  });

  it("only matches items of the requested kind", () => {
    expect(matchTargetByName(TREE, "Interviews", "category")).toBe(1);
    expect(matchTargetByName(TREE, "Interviews", "code")).toBeNull();
    expect(matchTargetByName(TREE, "Happiness", "category")).toBe(4);
  });

  it("returns null when no item matches", () => {
    expect(matchTargetByName(TREE, "Nonexistent")).toBeNull();
  });

  it("returns null for blank names", () => {
    expect(matchTargetByName(TREE, "   ")).toBeNull();
    expect(matchTargetByName(TREE, "")).toBeNull();
  });
});

describe("clampToViewport", () => {
  it("keeps coordinates unchanged when there is room", () => {
    expect(clampToViewport(100, 100, 176, 100, 1024, 768)).toEqual({ x: 100, y: 100 });
  });

  it("clamps the menu inside the viewport", () => {
    expect(clampToViewport(1000, 760, 176, 100, 1024, 768)).toEqual({
      x: 1024 - 176 - 4,
      y: 768 - 100 - 4,
    });
  });

  it("never goes negative for huge positions", () => {
    expect(clampToViewport(-50, -50, 176, 100, 1024, 768)).toEqual({ x: 4, y: 4 });
  });
});
