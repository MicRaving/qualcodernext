// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { useAsyncEffect } from "./useAsync";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function mount(effect: () => Promise<void | (() => void)>) {
  function Probe() {
    useAsyncEffect(effect, []);
    return null;
  }
  const root = createRoot(document.createElement("div"));
  return {
    render: () => act(async () => root.render(<Probe />)),
    unmount: () => act(async () => root.unmount()),
  };
}

describe("useAsyncEffect cleanup", () => {
  it("runs the cleanup the effect resolves with on unmount", async () => {
    const cleanup = vi.fn();
    const m = mount(async () => cleanup);
    await m.render();
    expect(cleanup).not.toHaveBeenCalled();
    await m.unmount();
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  it("runs the cleanup immediately when the effect resolves after unmount", async () => {
    const cleanup = vi.fn();
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const m = mount(async () => {
      await gate;
      return cleanup;
    });
    await m.render();
    await m.unmount();
    expect(cleanup).not.toHaveBeenCalled();
    await act(async () => release());
    expect(cleanup).toHaveBeenCalledTimes(1);
  });
});
