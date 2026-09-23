import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  // `@/` is what tsconfig maps to the project root; vitest does not read
  // tsconfig paths, so it has to be repeated here or every import breaks.
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: { environment: "jsdom", setupFiles: ["./vitest.setup.ts"] },
});
