import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

const browserFiles = ["src/**/*.{ts,tsx}"];
const nodeFiles = [
  "eslint.config.js",
  "vite.config.ts",
  "vitest.config.ts",
  "playwright.config.ts",
  "tests-e2e/**/*.ts",
];

export default tseslint.config(
  {
    ignores: [
      "dist/",
      "node_modules/",
      "src-tauri/",
      "playwright-report/",
      "test-results/",
      "*.tsbuildinfo",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: browserFiles,
    languageOptions: {
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      "react-refresh/only-export-components": [
        "error",
        { allowConstantExport: true },
      ],
    },
  },
  {
    // Libraries that intentionally mix components, hooks and helpers.
    files: ["src/lib/i18n.tsx", "src/lib/toast.tsx", "src/features/analyze/AnalyzeView.tsx"],
    rules: {
      "react-refresh/only-export-components": [
        "error",
        {
          allowConstantExport: true,
          allowExportNames: ["translate", "t", "useI18n", "useToast", "REPORT_META"],
        },
      ],
    },
  },
  {
    files: nodeFiles,
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    rules: {
      eqeqeq: ["error", "smart"],
      "prefer-const": "error",
      "no-console": ["error", { allow: ["warn", "error"] }],
      "@typescript-eslint/no-unused-expressions": "error",
    },
  }
);
