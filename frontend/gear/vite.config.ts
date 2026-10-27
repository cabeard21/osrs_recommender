import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/gear-ui/",
  build: { outDir: "../../tracker/ui/gear_static", emptyOutDir: true },
  server: {
    proxy: {
      "/gear-sprites":
        process.env.GEAR_BACKEND_ORIGIN ?? "http://127.0.0.1:8000",
      "/ui-api": process.env.GEAR_BACKEND_ORIGIN ?? "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/tests/setup.ts",
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: [
        "src/api/httpClient.ts",
        "src/api/contextualAlternatives.ts",
        "src/components/LiveResultWorkspace.tsx",
        "src/components/TrialComparison.tsx",
        "src/components/PurchaseListCopy.tsx",
        "src/state/scenario.ts",
        "src/state/GearProvider.tsx",
      ],
      thresholds: { lines: 80, statements: 80, functions: 80, branches: 80 },
    },
  },
});
