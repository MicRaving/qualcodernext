import { describe, expect, it } from "vitest";
import { describePendingTool, describeToolCall } from "@/features/ai/format";

describe("describeToolCall", () => {
  it("summarizes write tools", () => {
    expect(describeToolCall({ tool: "create_code", arguments: { name: "X" }, result: null })).toBe(
      'Created code "X"',
    );
    expect(
      describeToolCall({
        tool: "rename_code",
        arguments: { cid: 5, name: "Y" },
        result: null,
      }),
    ).toBe('Renamed code 5 to "Y"');
    expect(
      describeToolCall({
        tool: "set_attribute_value",
        arguments: { name: "Age", attr_type: "numeric", value: "42" },
        result: null,
      }),
    ).toBe('Set numeric "Age" to "42"');
  });

  it("summarizes read tools", () => {
    expect(describeToolCall({ tool: "get_code_tree", arguments: {}, result: null })).toBe(
      "Read the code tree",
    );
    expect(
      describeToolCall({ tool: "get_source_text", arguments: { source_id: 3 }, result: null }),
    ).toBe("Read source 3");
  });

  it("falls back to the raw name for unknown tools", () => {
    expect(describeToolCall({ tool: "mystery_tool", arguments: {}, result: null })).toBe(
      "Ran mystery_tool",
    );
  });
});

describe("describePendingTool", () => {
  it("describes a proposed write like an executed one", () => {
    expect(
      describePendingTool({ name: "create_category", arguments: { name: "Theme" } }),
    ).toBe('Created category "Theme"');
  });
});