import { defaultExclude, defineConfig } from "vitest/config";
import viteConfig from "./vite.config";

export default defineConfig({
  ...viteConfig,
  test: {
    exclude: [...defaultExclude, "tests-e2e/**"],
  },
});
