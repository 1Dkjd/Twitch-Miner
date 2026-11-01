// Retakes docs/screenshots/ from web/dist with the made-up data in fake-api.mjs: npm run build, then
// node e2e/screenshots.mjs (PW_CHANNEL=msedge or chrome to use an installed browser).
import { spawn } from "node:child_process";
import { chromium } from "@playwright/test";

const server = spawn(process.execPath, ["e2e/fake-api.mjs"], { stdio: "ignore" });
const SHOTS = [
  ["overview", "overview", 1280, 1000], ["priorities", "priorities", 1280, 900],
  ["history", "history", 1280, 1000], ["settings/notifications", "settings", 1280, 900], ["overview", "phone", 390, 844],
];
try {
  await new Promise((r) => setTimeout(r, 800));
  const browser = await chromium.launch({ channel: process.env.PW_CHANNEL });
  for (const [view, name, width, height] of SHOTS) {
    const page = await browser.newPage({ viewport: { width, height }, colorScheme: "dark", isMobile: width < 720, deviceScaleFactor: 2 });
    await page.goto(`http://127.0.0.1:4177/#${view}`);
    await page.waitForTimeout(800);
    await page.screenshot({ path: `../docs/screenshots/${name}.png` });
    await page.close();
  }
  await browser.close();
} finally {
  server.kill();
}
