import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:4731",
    viewport: { width: 1280, height: 860 },
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:4731",
    reuseExistingServer: true,
    timeout: 120000,
  },
});
