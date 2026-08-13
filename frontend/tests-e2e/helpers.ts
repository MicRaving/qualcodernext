/**
 * Shared E2E test helpers: a re-exported `test` that installs the global
 * animation kill-switch on every page. CSS animations/transitions are pure
 * test latency — Playwright's actionability checks wait for "stable"
 * elements, so a transitioning flyout/drag target adds real seconds across
 * the suite. The app's own reduced-motion a11y mode does the same thing
 * (see frontend/src/stores/project.ts applyA11yMode); here we force it.
 */
import { expect, test as base } from "@playwright/test";

export const KILL_ANIMATIONS = () => {
  const style = document.createElement("style");
  style.textContent =
    "*{animation:none!important;transition:none!important;scroll-behavior:auto!important}";
  document.head.appendChild(style);
};

export const test = base.extend<{ killAnimations: void }>({
  killAnimations: [
    async ({ page }, use) => {
      await page.addInitScript(KILL_ANIMATIONS);
      await use();
    },
    { auto: true },
  ],
});

export { expect };
