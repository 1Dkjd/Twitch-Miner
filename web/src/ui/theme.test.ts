import { PALETTES, THEMES, applyTheme, savedTheme, themeCss } from "./theme";

afterEach(() => { localStorage.clear(); delete document.documentElement.dataset.theme; });

test("every colour theme sets every token the page uses", () => {
  const css = themeCss();
  for (const id of Object.keys(PALETTES)) {
    const rule = css.slice(css.indexOf(`[data-theme="${id}"]`));
    for (const token of ["--bg", "--surface", "--surface-2", "--line", "--fg", "--muted", "--accent", "--accent-text",
      "--accent-ink", "--accent-soft", "--ok", "--alert", "--warn", "--note", "--art", "--fill", "color-scheme"]) {
      expect(rule.slice(0, rule.indexOf("}"))).toContain(`${token}:`);
    }
  }
});

test("a colour theme is applied, styled once and remembered; System clears it", () => {
  applyTheme("dracula");
  expect(document.documentElement.dataset.theme).toBe("dracula");
  expect(document.querySelectorAll("#dw-themes")).toHaveLength(1);
  expect(savedTheme()).toBe("dracula");
  applyTheme("nord");
  expect(document.querySelectorAll("#dw-themes")).toHaveLength(1);
  applyTheme("system");
  expect(document.documentElement.dataset.theme).toBeUndefined();
  expect(savedTheme()).toBe("system");
});

test("an unknown saved theme falls back to System", () => {
  localStorage.setItem("dw-theme", "retired-theme");
  expect(savedTheme()).toBe("system");
  expect(THEMES.length).toBe(11);
});
