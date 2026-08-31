import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // .vite is Vite's pre-bundled dependency cache - third-party code, already
  // built, and it trips rules from plugins this project does not load.
  { ignores: ["dist", "node_modules", ".vite"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Enabled for route components below. Shared modules deliberately
      // export constants and hooks next to components, which is fine.
      "react-refresh/only-export-components": "off",
      // The spec forbids `any` outright, so it is an error here rather than a
      // warning nobody reads.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    // A page that also exports a constant genuinely breaks fast refresh during
    // development, and pages are the files being edited most.
    files: ["src/pages/**/*.tsx"],
    rules: {
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
);
