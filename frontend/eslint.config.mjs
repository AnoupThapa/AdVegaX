import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const forbiddenStorage = {
  message:
    "Browser storage is forbidden for tokens and personal data (PHASE_01C_PLAN §7). Keep state in memory.",
};

const config = [
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    ignores: [".next/**", "node_modules/**", "coverage/**", "next-env.d.ts"],
  },
  {
    rules: {
      "react/no-danger": "error",
      "no-restricted-globals": [
        "error",
        { name: "localStorage", ...forbiddenStorage },
        { name: "sessionStorage", ...forbiddenStorage },
      ],
      "no-restricted-properties": [
        "error",
        { object: "window", property: "localStorage", ...forbiddenStorage },
        { object: "window", property: "sessionStorage", ...forbiddenStorage },
        {
          object: "document",
          property: "cookie",
          message: "The web app never reads or writes cookies.",
        },
      ],
      "no-eval": "error",
      "no-implied-eval": "error",
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
];

export default config;
