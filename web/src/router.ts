import { useEffect, useRef, useState } from "react";

export const VIEWS = ["overview", "priorities", "history", "activity", "settings"] as const;
export type View = (typeof VIEWS)[number] | "connect";
const TITLES: Record<View, string> = {
  overview: "Overview", priorities: "Priorities", history: "History", activity: "Activity", settings: "Settings", connect: "Sign in to Twitch",
};

export function parseView(hash: string): View {
  const v = hash.replace(/^#/, "");
  return v === "connect" || (VIEWS as readonly string[]).includes(v) ? (v as View) : "overview";
}

/** Hash routing as in the mockup: the title follows the view, and after navigation (not on first
 * load) focus moves to the view's heading so keyboard and screen-reader users land in it (spec §11). */
export function useView(): View {
  const [view, setView] = useState<View>(() => parseView(location.hash));
  const first = useRef(true);
  useEffect(() => {
    const on = () => setView(parseView(location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    document.title = `${TITLES[view]} · Dropwatch`;
    if (first.current) {
      first.current = false;
      return;
    }
    const h = document.getElementById(`h-${view}`);
    h?.focus({ preventScroll: true });
    window.scrollTo?.(0, 0);
  }, [view]);
  return view;
}

export function go(view: View) {
  location.hash = view;
}
