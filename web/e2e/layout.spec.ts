import { expect, test, type Page } from "@playwright/test";

/* What jsdom can't see: the page as laid out by a browser, with the real stylesheets. */

const VIEWS = ["overview", "priorities", "inventory", "history", "activity", "settings/mining", "settings/notifications",
  "settings/account", "settings/appearance", "settings/backup", "settings/widget", "settings/about"];

const isPhone = (page: Page) => page.viewportSize()!.width <= 720;

/** Open a view with the web font stubbed (no network in tests), collecting anything the page logs as an error. */
async function open(page: Page, view: string, theme?: string) {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.fulfill({ contentType: "text/css", body: "" }));
  if (theme) await page.addInitScript((t) => localStorage.setItem("dw-theme", t), theme);
  await page.goto(`/#${view}`);
  await expect(page.locator("h1").first()).toBeAttached();
  await page.waitForLoadState("networkidle").catch(() => undefined); // the live event stream may keep it from settling
  await page.waitForTimeout(300);
  return errors;
}

/** Visible elements sticking out past the screen's sides, even inside a box that clips them. Rows that scroll
 * sideways on purpose don't count. Measured against the configured size: a phone zooms out to fit a page that's too
 * wide, and window.innerWidth grows with it. */
const outOfBounds = (page: Page) => page.evaluate((innerWidth) => {
  const scrolls = (e: Element) => { for (let p: Element | null = e; p; p = p.parentElement) { if (/auto|scroll/.test(getComputedStyle(p).overflowX)) return true; } return false; };
  return [...document.querySelectorAll("header *, main *, nav *")].filter((e) => {
    if (e.closest(".sr, svg") || scrolls(e)) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && (r.right > innerWidth + 1 || r.left < -1);
  }).slice(0, 5).map((e) => `${e.tagName}.${e.getAttribute("class")}: ${(e.textContent ?? "").slice(0, 40)}`);
}, page.viewportSize()!.width);

for (const view of VIEWS) {
  test(`${view}: nothing overflows the window and the page logs no errors`, async ({ page }) => {
    const errors = await open(page, view);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
    expect(await outOfBounds(page)).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("the approved tokens and font are in force", async ({ page }) => {
  await open(page, "overview");
  const css = await page.evaluate(() => {
    const body = getComputedStyle(document.body);
    const num = getComputedStyle(document.querySelector(".wnum")!);
    return { bg: body.backgroundColor, fg: body.color, font: body.fontFamily, nums: num.fontVariantNumeric,
      button: getComputedStyle(document.querySelector(".now-foot a.btn")!).backgroundColor };
  });
  expect(css).toMatchObject({ bg: "rgb(14, 14, 16)", fg: "rgb(239, 239, 241)", nums: "tabular-nums", button: "rgb(145, 70, 255)" });
  expect(css.font).toMatch(/^"?Inter/);
});

test("the top tabs are underlined in purple on desktop", async ({ page }) => {
  test.skip(isPhone(page), "desktop layout");
  await open(page, "history");
  const nav = page.getByRole("navigation", { name: "Views" });
  await expect(nav.getByRole("link")).toHaveCount(6);
  const current = nav.getByRole("link", { name: "History" });
  await expect(current).toHaveCSS("border-bottom-color", "rgb(145, 70, 255)");
  await expect(nav.getByRole("link", { name: "Overview" })).toHaveCSS("border-bottom-color", "rgba(0, 0, 0, 0)");
  expect((await nav.boundingBox())!.y).toBeLessThan(10);
});

test("Mining now sits beside Needs you on desktop", async ({ page }) => {
  test.skip(isPhone(page), "desktop layout");
  await open(page, "overview");
  const now = (await page.getByRole("article").boundingBox())!;
  const side = (await page.locator(".ov-side").boundingBox())!;
  expect(side.x).toBeGreaterThanOrEqual(now.x + now.width);
  expect(Math.abs(side.y - now.y)).toBeLessThan(2);
});

test("Priorities has its two columns on desktop", async ({ page }) => {
  test.skip(isPhone(page), "desktop layout");
  await open(page, "priorities");
  const main = (await page.locator(".pri-main").boundingBox())!;
  const side = (await page.locator(".pri-side").boundingBox())!;
  expect(side.x).toBeGreaterThanOrEqual(main.x + main.width);
  expect(main.width).toBeGreaterThan(side.width);
});

test("phones get a bottom tab bar, and More opens the rest", async ({ page }) => {
  test.skip(!isPhone(page), "phone layout");
  await open(page, "overview");
  const nav = page.getByRole("navigation", { name: "Views" });
  const box = (await nav.boundingBox())!;
  expect(box.y + box.height).toBeCloseTo(page.viewportSize()!.height, 0);
  await expect(nav.getByRole("link")).toHaveCount(4);
  await nav.getByRole("button", { name: "More" }).click();
  const item = page.getByRole("menuitem", { name: "Activity" });
  const r = (await item.boundingBox())!;
  expect(r.y + r.height).toBeLessThanOrEqual(box.y); // opens upwards, above the bar
  expect(r.x + r.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  await item.click();
  await expect(page.getByRole("heading", { level: 1, name: "Activity" })).toBeVisible();
  await expect(nav.getByRole("button", { name: /More, Activity is open/ })).toBeVisible();
});

test("on phones Needs you comes first as one line that opens", async ({ page }) => {
  test.skip(!isPhone(page), "phone layout");
  await open(page, "overview");
  const line = page.getByRole("button", { name: /2 campaigns need you/ });
  expect((await line.boundingBox())!.y).toBeLessThan((await page.getByRole("article").boundingBox())!.y);
  const link = page.locator("#needs-list").getByRole("link", { name: /Link your Eternal Return/ });
  await expect(link).toBeHidden();
  await line.click();
  await expect(link).toBeVisible();
});

test("the tab bar never covers the end of a page", async ({ page }) => {
  test.skip(!isPhone(page), "phone layout");
  for (const view of ["overview", "history", "priorities"]) {
    await open(page, view);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const gap = await page.evaluate(() => {
      const last = [...document.querySelectorAll<HTMLElement>("main .view > *")].filter((e) => e.offsetHeight).at(-1)!;
      return document.querySelector("nav[aria-label='Views']")!.getBoundingClientRect().top - last.getBoundingClientRect().bottom;
    });
    expect(gap, view).toBeGreaterThanOrEqual(0);
  }
});

test("controls are big enough to tap on phones", async ({ page }) => {
  test.skip(!isPhone(page), "phone layout");
  for (const view of ["overview", "priorities", "inventory", "history"]) {
    await open(page, view);
    const small = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("main .btn, main .ib, nav[aria-label='Views'] a")]
      .filter((e) => e.offsetHeight > 0 && e.offsetHeight < 40).slice(0, 5).map((e) => `${e.className}: ${e.textContent}`));
    expect(small, view).toEqual([]);
  }
});

test("open menus aren't clipped or covered", async ({ page }) => {
  await open(page, "overview");
  for (const button of ["Pause", "Mine something else"]) {
    await page.getByRole("button", { name: button, exact: true }).click();
    const items = page.getByRole("menuitem");
    await expect(items.first()).toBeFocused();
    for (const it of await items.all()) {
      const onTop = await it.evaluate((e) => {
        const r = e.getBoundingClientRect();
        return e.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2));
      });
      expect(onTop, await it.innerText()).toBe(true);
      const r = (await it.boundingBox())!;
      expect(r.x).toBeGreaterThanOrEqual(0);
      expect(r.x + r.width).toBeLessThanOrEqual(page.viewportSize()!.width);
    }
    await page.keyboard.press("Escape");
    await expect(items).toHaveCount(0);
  }
});

test("the forecast says what will be missed, in view and inside its card", async ({ page }) => {
  await open(page, "overview");
  const sec = page.getByRole("region", { name: "Forecast" });
  await expect(sec.getByText("2 rewards won't make it")).toBeVisible();
  await expect(sec.getByText(/^Won't make it: A reward with a long name/)).toBeVisible();
  const chip = (await sec.getByText("Won't make it", { exact: true }).boundingBox())!;
  expect(chip.height).toBeLessThan(40); // one line, not squeezed into the art's column
  const card = (await sec.locator(".fc-list").boundingBox())!;
  for (const row of await sec.getByRole("listitem").all()) {
    const r = (await row.boundingBox())!;
    expect(r.x + r.width).toBeLessThanOrEqual(card.x + card.width + 1);
  }
});

test("History's chart keeps its bars plain, the newest in the accent", async ({ page }) => {
  await open(page, "history");
  const chart = page.getByRole("img", { name: /^Rewards per day/ });
  const newest = chart.locator(".newest");
  await expect(newest).toHaveCSS("border-top-width", "0px"); // a class clash once gave this bar the Mining now card's box
  await expect(newest.locator("i")).toHaveCSS("background-color", "rgb(145, 70, 255)");
  const heights = await chart.locator("i").evaluateAll((bars) => bars.map((b) => b.getBoundingClientRect().height));
  expect(Math.max(...heights)).toBeGreaterThan(50);
  const box = (await chart.boundingBox())!;
  const labels = await chart.locator("> div").evaluateAll((d) => d.map((e) => e.getBoundingClientRect().right));
  expect(Math.max(...labels)).toBeLessThanOrEqual(box.x + box.width + 1);
});

test("a reward's details open inside the window and close with Escape", async ({ page }) => {
  await open(page, "inventory");
  await page.getByRole("button", { name: "Cold Blooded: details" }).click();
  const dlg = page.getByRole("dialog");
  const r = (await dlg.boundingBox())!;
  const vp = page.viewportSize()!;
  expect(r.x).toBeGreaterThanOrEqual(0);
  expect(r.x + r.width).toBeLessThanOrEqual(vp.width);
  expect(r.y + r.height).toBeLessThanOrEqual(vp.height);
  await page.keyboard.press("Escape");
  await expect(dlg).toHaveCount(0);
});

test("keyboard focus shows a ring", async ({ page }) => {
  await open(page, "overview");
  await page.keyboard.press("Tab");
  const width = await page.evaluate(() => getComputedStyle(document.activeElement!).outlineWidth);
  expect(parseFloat(width)).toBeGreaterThanOrEqual(2);
});

for (const [theme, bg, fg] of [["light", "rgb(247, 247, 248)", "rgb(14, 14, 16)"], ["dracula", "rgb(33, 34, 44)", "rgb(248, 248, 242)"]] as const) {
  test(`the ${theme} theme recolours the page and every surface token resolves`, async ({ page }) => {
    await open(page, "overview", theme);
    await expect(page.locator("body")).toHaveCSS("background-color", bg);
    await expect(page.locator("body")).toHaveCSS("color", fg);
    await expect(page.locator(".now-foot .btn").nth(1)).not.toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    expect(await outOfBounds(page)).toEqual([]);
  });
}
