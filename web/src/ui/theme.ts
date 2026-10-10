/** Theme: System (no attribute), Light or Dark, remembered per browser (spec §11 / mockup Settings). */
export type Theme = "system" | "light" | "dark";

export function savedTheme(): Theme {
  try {
    const t = localStorage.getItem("dw-theme");
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(t: Theme) {
  const root = document.documentElement;
  if (t === "system") delete root.dataset.theme;
  else root.dataset.theme = t;
  try {
    if (t === "system") localStorage.removeItem("dw-theme");
    else localStorage.setItem("dw-theme", t);
  } catch {
    /* storage blocked: the choice lasts for this visit */
  }
}
