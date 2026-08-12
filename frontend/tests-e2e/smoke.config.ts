import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: ".",
  testMatch: "smoke-features.spec.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 120000,
  expect: { timeout: 10000 },
  reporter: "list",
  use: { baseURL: "http://localhost:5173", headless: true },
});
