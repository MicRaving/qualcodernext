// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { getSelectionOffsets } from "@/features/coding/selection";

function selectRange(
  startNode: Node,
  startOffset: number,
  endNode: Node,
  endOffset: number,
): Selection {
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  const range = document.createRange();
  range.setStart(startNode, startOffset);
  range.setEnd(endNode, endOffset);
  selection.addRange(range);
  return selection;
}

function textDoc(chunks: string[]): { container: HTMLElement; nodes: Node[] } {
  const container = document.createElement("div");
  for (const chunk of chunks) container.appendChild(document.createTextNode(chunk));
  document.body.appendChild(container);
  return { container, nodes: Array.from(container.childNodes) };
}

describe("getSelectionOffsets", () => {
  it("returns null for a collapsed selection", () => {
    const { container, nodes } = textDoc(["hello world"]);
    const selection = selectRange(nodes[0]!, 2, nodes[0]!, 2);
    expect(getSelectionOffsets(container, selection)).toBeNull();
  });

  it("computes offsets within a single text node", () => {
    const { container, nodes } = textDoc(["hello world"]);
    const selection = selectRange(nodes[0]!, 2, nodes[0]!, 7);
    expect(getSelectionOffsets(container, selection)).toEqual({ start: 2, end: 7 });
  });

  it("computes offsets spanning multiple text nodes", () => {
    const { container, nodes } = textDoc(["abc", "def", "ghi"]);
    const selection = selectRange(nodes[0]!, 1, nodes[2]!, 2);
    expect(getSelectionOffsets(container, selection)).toEqual({ start: 1, end: 8 });
  });

  it("walks into nested spans", () => {
    const container = document.createElement("div");
    container.appendChild(document.createTextNode("ab"));
    const span = document.createElement("span");
    span.appendChild(document.createTextNode("cd"));
    span.appendChild(document.createTextNode("ef"));
    container.appendChild(span);
    container.appendChild(document.createTextNode("gh"));
    document.body.appendChild(container);
    const nodes = [container.childNodes[0], span.childNodes[0], span.childNodes[1], container.childNodes[2]];
    const selection = selectRange(nodes[1]!, 1, nodes[3]!, 1);
    expect(getSelectionOffsets(container, selection)).toEqual({ start: 3, end: 7 });
  });

  it("handles backward selections (base after extent)", () => {
    const { container, nodes } = textDoc(["hello world"]);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.setBaseAndExtent(nodes[0]!, 7, nodes[0]!, 2);
    expect(getSelectionOffsets(container, selection)).toEqual({ start: 2, end: 7 });
  });

  it("returns null for selections outside the container", () => {
    const { container } = textDoc(["inside"]);
    const other = document.createElement("div");
    other.appendChild(document.createTextNode("outside"));
    document.body.appendChild(other);
    const selection = selectRange(other.childNodes[0]!, 0, other.childNodes[0]!, 3);
    expect(getSelectionOffsets(container, selection)).toBeNull();
  });
});
