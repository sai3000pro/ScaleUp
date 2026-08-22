import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";

/** @type {import("eslint").Linter.Config[]} */
export default [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  js.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parser: (await import("@typescript-eslint/parser")).default,
      parserOptions: { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true } },
      globals: { window: "readonly", document: "readonly", localStorage: "readonly", console: "readonly",
                 fetch: "readonly", setTimeout: "readonly", clearTimeout: "readonly", FormData: "readonly",
                 File: "readonly", HTMLInputElement: "readonly", HTMLFormElement: "readonly",
                 process: "readonly", URLSearchParams: "readonly", AbortController: "readonly" },
    },
    // `eslint-config-next` is installed but is still eslintrc-format, so it
    // cannot be spread into a flat config. Registering the hooks plugin
    // directly gets the two rules that actually catch bugs; without them
    // `next build` only prints a warning that the plugin is missing, and stale
    // closures and missing effect dependencies go unlinted entirely.
    plugins: { "react-hooks": reactHooks },
    rules: {
      // Mirrors the Python AST guard in backend/tests/test_no_continue.py.
      // See CLAUDE.md: explicit branching only, so every path through a loop is
      // visible at the point of decision.
      "no-continue": "error",
      "no-unused-vars": "off",
      "no-undef": "off",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
    },
  },
];
