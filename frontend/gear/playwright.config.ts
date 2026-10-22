import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: { baseURL: "http://127.0.0.1:8766", browserName: "chromium" },
  webServer: {
    command: "../../.venv/bin/python e2e/server.py",
    url: "http://127.0.0.1:8766/healthz",
    reuseExistingServer: false,
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1600, height: 1000 } } },
    {
      name: "mobile",
      use: { viewport: { width: 390, height: 844 }, isMobile: true },
    },
  ],
});
