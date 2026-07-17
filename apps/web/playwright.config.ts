import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config. Assumes the API (:8000) and web (:3000) servers are
 * already running (see `make dev` / docker compose). Point BASE_URL elsewhere
 * to test another deployment. Uses the pre-installed Chromium when present.
 */
const CHROME = process.env.PLAYWRIGHT_CHROMIUM_PATH || "/opt/pw-browsers/chromium";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 45000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL || "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: { executablePath: CHROME },
      },
    },
    // Responsive checks (tablet + mobile) reuse the same specs.
    { name: "tablet", use: { ...devices["iPad Pro 11"], launchOptions: { executablePath: CHROME } } },
    { name: "mobile", use: { ...devices["Pixel 7"], launchOptions: { executablePath: CHROME } } },
  ],
});
