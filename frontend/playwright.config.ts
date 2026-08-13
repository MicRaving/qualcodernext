import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests-e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // Generous: the first navigation cold-transforms the whole app (vite dev
  // re-optimizes dependencies on fresh checkouts, incl. the ~1.2 MB pdf.js
  // worker), which can exceed 60 s on CI runners. global-setup pre-warms the
  // vite transform cache so the very first test does not pay the full cost.
  timeout: 120000,
  expect: { timeout: 10000 },
  globalSetup: "./tests-e2e/global-setup.ts",
  globalTeardown: "./tests-e2e/global-teardown.ts",
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    headless: true,
    // CSS animations/transitions are pure test latency (flyouts, drags,
    // flash highlights). Kill them globally — the app's own reduced-motion
    // mode does the same; assertions never depend on transition duration.
    // (The kill switch itself is injected via tests-e2e/helpers.ts.)
    contextOptions: {
      reducedMotion: "reduce",
    },
  },
});
