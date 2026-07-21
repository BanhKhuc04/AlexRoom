import js from "@eslint/js";
import globals from "globals";

export default [
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "ALEX_NEXUS_OS_MARK_II_v2.0/**",
      "ALEX_NEXUS_OS_MARK_II_v2.0.1_FIXED/**",
      "ALEX_NEXUS_UI_v0.4/**",
      "esphome/**",
    ],
  },
  js.configs.recommended,
  {
    files: ["static/**/*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: globals.browser,
    },
    rules: {
      "no-console": ["warn", { "allow": ["warn", "error"] }],
    },
  },
  {
    files: ["tests/**/*.mjs", "scripts/**/*.mjs", "eslint.config.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: globals.node,
    },
  },
];
