import { describe, expect, it } from "vitest";
import { deriveModeLabel } from "@/features/ai/aiModes";

describe("deriveModeLabel", () => {
  it("falls back to general when nothing is selected", () => {
    expect(deriveModeLabel({})).toBe("general");
    expect(deriveModeLabel({ memoIds: [], codeIds: [], sourceIds: [] })).toBe("general");
  });

  it("derives memo_analysis from memos only", () => {
    expect(deriveModeLabel({ memoIds: [1] })).toBe("memo_analysis");
  });

  it("derives code_analysis from codes only", () => {
    expect(deriveModeLabel({ codeIds: [2] })).toBe("code_analysis");
  });

  it("derives text_analysis from sources only", () => {
    expect(deriveModeLabel({ sourceIds: [3] })).toBe("text_analysis");
  });

  it("derives topic_exploration when several kinds are selected", () => {
    expect(deriveModeLabel({ memoIds: [1], codeIds: [2] })).toBe("topic_exploration");
    expect(deriveModeLabel({ codeIds: [2], sourceIds: [3] })).toBe("topic_exploration");
    expect(deriveModeLabel({ memoIds: [1], codeIds: [2], sourceIds: [3] })).toBe(
      "topic_exploration",
    );
  });
});
