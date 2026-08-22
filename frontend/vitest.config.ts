import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * Every module under test here is pure — reducers over frames, landmarks, and
 * activation arrays — so there is no jsdom and no browser environment. That is
 * deliberate: the audio and camera plumbing is deliberately kept thin and
 * untested, and all the logic worth asserting on lives in functions that take
 * data and return data.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
