import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
    oxc: { jsx: { runtime: "automatic" } },
    resolve: { alias: { "@": path.resolve(import.meta.dirname) } },
    test: {
        environment: "jsdom",
        globals: true,
        setupFiles: ["./tests/setup.ts"],
        include: ["tests/**/*.test.{ts,tsx}"],
        coverage: {
            provider: "v8",
            include: [
                "lib/**/*.{ts,tsx}",
                "features/**/*.{ts,tsx}",
                "components/**/*.{ts,tsx}",
                "proxy.ts",
            ],
            thresholds: { lines: 85, functions: 85, branches: 85, statements: 85 },
        },
    },
});
