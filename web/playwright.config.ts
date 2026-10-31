import { defineConfig } from "@playwright/test";

/** Layout tests in a real browser, against web/dist and made-up API data (e2e/fake-api.mjs). Set PW_CHANNEL=msedge
 * or chrome to use an installed browser instead of Playwright's own Chromium. */
const channel = process.env.PW_CHANNEL;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["github"], ["list"]] : "list", // github: failures show as annotations on the run
  use: { baseURL: "http://127.0.0.1:4177", channel, colorScheme: "dark" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 900 } } },
    { name: "phone", use: { viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true } },
    { name: "small-phone", use: { viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true } },
  ],
  webServer: { command: "node e2e/fake-api.mjs", url: "http://127.0.0.1:4177/api/me", reuseExistingServer: !process.env.CI },
});
