import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests-e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60000,
  expect: { timeout: 10000 },
  globalSetup: "./tests-e2e/global-setup.ts",
  globalTeardown: "./tests-e2e/global-teardown.ts",
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    headless: true,
  },
});
