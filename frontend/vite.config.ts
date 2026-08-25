import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const dir = path.dirname(fileURLToPath(import.meta.url));

// Single source of truth for the UI-displayed version: frontend/package.json.
// The release flow bumps this file and src-tauri/tauri.conf.json together, so
// builds always carry the released version without manual edits to version.ts
// (which previously drifted at "0.1.0" across releases).
const pkg = JSON.parse(
  readFileSync(path.resolve(dir, "package.json"), "utf-8"),
) as { version: string };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  resolve: {
    alias: {
      "@": path.resolve(dir, "src"),
    },
  },
  server: {
    // allow importing tokens.json which lives at the monorepo root
    fs: { allow: [path.resolve(dir, "..")] },
    port: 5173,
    strictPort: false,
  },
});
