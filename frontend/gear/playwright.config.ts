import { defineConfig } from "@playwright/test";
const port = process.env.GEAR_E2E_PORT ?? "8766";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${port}`, browserName: "chromium" },
  webServer: {
    command:
      process.platform === "win32"
        ? '"..\\..\\.venv\\Scripts\\python.exe" e2e/server.py'
        : "../../.venv/bin/python e2e/server.py",
    url: `http://127.0.0.1:${port}/healthz`,
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
