/** Theme: System (no attribute), Light, Dark, or one of the colour themes, remembered per browser (spec §11 /
 * mockup Settings). Colour themes (2026-10-18) are full palettes over the same tokens app.css uses, generated
 * here once so the Settings swatches and the page can never disagree. */
export const BASE = ["system", "light", "dark"] as const;

type Palette = {
  name: string; scheme: "dark" | "light";
  bg: string; surface: string; surface2: string; line: string; fg: string; muted: string;
  accent: string; accentText: string; accentInk: string;
  ok: string; okText: string; alert: string; alertText: string; warn: string; warnText: string; note: string;
  art: string;
};

export const PALETTES: Record<string, Palette> = {
  twitch: { name: "Twitch", scheme: "dark", bg: "#0e0e10", surface: "#18181b", surface2: "#1f1f23", line: "#2f2f35",
    fg: "#efeff1", muted: "#adadb8", accent: "#9147ff", accentText: "#bf94ff", accentInk: "#ffffff",
    ok: "#00c48c", okText: "#3fd8a6", alert: "#eb0400", alertText: "#ff6b66", warn: "#ffb31a", warnText: "#ffc85a", note: "#5c9dff", art: "#26262c" },
  midnight: { name: "Midnight", scheme: "dark", bg: "#000000", surface: "#0b0b0d", surface2: "#141418", line: "#22222a",
    fg: "#e8e8ec", muted: "#8b8b96", accent: "#e3a83f", accentText: "#f0be63", accentInk: "#160f02",
    ok: "#5fbf8a", okText: "#77d39f", alert: "#f0765f", alertText: "#f4907d", warn: "#f0913c", warnText: "#f5a35c", note: "#7d9be0", art: "#121218" },
  nord: { name: "Nord", scheme: "dark", bg: "#2e3440", surface: "#3b4252", surface2: "#434c5e", line: "#4c566a",
    fg: "#eceff4", muted: "#b3bccb", accent: "#88c0d0", accentText: "#8fbcbb", accentInk: "#2e3440",
    ok: "#a3be8c", okText: "#b5cc9f", alert: "#bf616a", alertText: "#d08a91", warn: "#d08770", warnText: "#dfa28f", note: "#81a1c1", art: "#353c4a" },
  dracula: { name: "Dracula", scheme: "dark", bg: "#21222c", surface: "#282a36", surface2: "#343746", line: "#44475a",
    fg: "#f8f8f2", muted: "#a9aecb", accent: "#bd93f9", accentText: "#d6b8ff", accentInk: "#21222c",
    ok: "#50fa7b", okText: "#7dfc9c", alert: "#ff5555", alertText: "#ff8080", warn: "#ffb86c", warnText: "#ffca8f", note: "#8be9fd", art: "#2c2e3b" },
  catppuccin: { name: "Catppuccin", scheme: "dark", bg: "#181825", surface: "#1e1e2e", surface2: "#313244", line: "#45475a",
    fg: "#cdd6f4", muted: "#a6adc8", accent: "#cba6f7", accentText: "#d9bdfa", accentInk: "#1e1e2e",
    ok: "#a6e3a1", okText: "#b9eab5", alert: "#f38ba8", alertText: "#f6a5bc", warn: "#fab387", warnText: "#fbc5a3", note: "#89b4fa", art: "#24243a" },
  gruvbox: { name: "Gruvbox", scheme: "dark", bg: "#1d2021", surface: "#282828", surface2: "#32302f", line: "#3c3836",
    fg: "#ebdbb2", muted: "#a89984", accent: "#fabd2f", accentText: "#fbcb5b", accentInk: "#1d2021",
    ok: "#b8bb26", okText: "#c9cc4c", alert: "#fb4934", alertText: "#fc7262", warn: "#fe8019", warnText: "#fe9a48", note: "#83a598", art: "#2e2b29" },
  forest: { name: "Forest", scheme: "dark", bg: "#0f1512", surface: "#16201a", surface2: "#1d2a22", line: "#2a3a30",
    fg: "#e6efe8", muted: "#97aa9c", accent: "#9bd46a", accentText: "#b3e08c", accentInk: "#0f1a08",
    ok: "#5fbf8a", okText: "#77d39f", alert: "#f0765f", alertText: "#f4907d", warn: "#e8b04a", warnText: "#efc36e", note: "#7fb6d8", art: "#1a2620" },
  rosepine: { name: "Rosé Pine Dawn", scheme: "light", bg: "#faf4ed", surface: "#fffaf3", surface2: "#f2e9e1", line: "#dfdad9",
    fg: "#575279", muted: "#797593", accent: "#d7827e", accentText: "#a0544f", accentInk: "#ffffff",
    ok: "#286983", okText: "#1f566b", alert: "#b4637a", alertText: "#9a4a61", warn: "#ea9d34", warnText: "#a86a12", note: "#907aa9", art: "#f2e9e1" },
};

export type Theme = (typeof BASE)[number] | keyof typeof PALETTES;
export const THEMES: Theme[] = [...BASE, ...Object.keys(PALETTES)];

const soft = (hex: string, a: number) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

/** One rule per colour theme. ":not([data-x])" lifts it above app.css's look and system-light rules. */
export function themeCss(): string {
  return Object.entries(PALETTES).map(([id, p]) => `:root:not([data-x])[data-theme="${id}"] {
  --bg: ${p.bg}; --surface: ${p.surface}; --surface-2: ${p.surface2}; --line: ${p.line};
  --fg: ${p.fg}; --muted: ${p.muted};
  --accent: ${p.accent}; --accent-text: ${p.accentText}; --accent-ink: ${p.accentInk}; --accent-soft: ${soft(p.accent, 0.16)};
  --ok: ${p.ok}; --ok-text: ${p.okText}; --ok-soft: ${soft(p.ok, 0.14)};
  --alert: ${p.alert}; --alert-text: ${p.alertText}; --alert-soft: ${soft(p.alert, 0.13)};
  --warn: ${p.warn}; --warn-text: ${p.warnText}; --warn-soft: ${soft(p.warn, 0.14)};
  --note: ${p.note}; --note-soft: ${soft(p.note, 0.1)};
  --art: ${p.art}; --art-ring: ${soft(p.accent, 0.22)}; --muted-art: ${p.muted};
  --fill: ${p.accent};
  color-scheme: ${p.scheme};
}`).join("\n");
}

function ensureStyles() {
  if (typeof document === "undefined" || document.getElementById("dw-themes")) return;
  const el = document.createElement("style");
  el.id = "dw-themes";
  el.textContent = themeCss();
  document.head.appendChild(el);
}

export function savedTheme(): Theme {
  try {
    const t = localStorage.getItem("dw-theme");
    return t && t !== "system" && (THEMES as string[]).includes(t) ? (t as Theme) : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(t: Theme) {
  ensureStyles();
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

/** The three dots a theme card shows: background, surface and accent. */
export function swatch(t: Theme): [string, string, string] {
  if (t in PALETTES) { const p = PALETTES[t]!; return [p.bg, p.surface2, p.accent]; }
  if (t === "light") return ["#f1f0ec", "#ffffff", "#c98a0b"];
  if (t === "dark") return ["#13110d", "#26221b", "#f2b632"];
  return ["#13110d", "#f1f0ec", "#f2b632"]; // system: the dark and light halves of the default
}

export const themeName = (t: Theme) => (t in PALETTES ? PALETTES[t]!.name : t.charAt(0).toUpperCase() + t.slice(1));
