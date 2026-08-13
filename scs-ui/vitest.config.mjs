import { defineConfig } from "vitest/config";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
export default defineConfig({
  resolve: {alias: {"@": root}},
  test: {environment: "jsdom", globals: true, setupFiles: ["./vitest.setup.ts"]},
});
