import { defineConfig, devices } from "@playwright/test";

const playwrightOutput = "../../build/map-atlas/playwright";

export default defineConfig({
  testDir: "./e2e",
  outputDir: `${playwrightOutput}/test-results`,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: `${playwrightOutput}/report` }],
  ],
  use: {
    baseURL: "http://127.0.0.1:42000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  workers: process.env.CI ? 1 : undefined,
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run preview -- --host 127.0.0.1 --port 42000 --strictPort",
    url: "http://127.0.0.1:42000",
    reuseExistingServer: false,
  },
});
