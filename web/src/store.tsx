import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, api, setUnauthorizedHandler, type Me, type SignIn, type State } from "./api/client";
import { connectLive, type EventKind } from "./api/live";

/** A notice at the bottom of the page (picked 2026-10-11, docs/design/toast-mockup.html variant B): a title,
 * an optional quieter detail line, an optional action, and a line along the bottom that drains until it
 * closes. A plain string is a title. */
export interface ToastSpec {
  title: string;
  detail?: string;
  tone?: "ok" | "bad";
  action?: { label: string; run: () => void };
}
interface ToastItem extends Required<Pick<ToastSpec, "title" | "tone">> {
  id: number;
  detail?: string;
  action?: ToastSpec["action"];
  ms: number;
}
const TOAST_MS = 4000; // a plain notice
const TOAST_LONG_MS = 8000; // one with Undo / Retry (time to reach the button) or an error (time to read it)
const TOAST_MAX = 3;
const TOAST_KEY = "KeyN"; // Alt+N moves focus to the newest notice (Alt+T is Firefox's Tools menu)
let toastSeq = 0;

/** Newest first, at most TOAST_MAX: when one has to go, the oldest plain notice goes before any with an
 * action, so a fresh burst of "Setting saved" can't take an Undo away (polish 2026-10-12). The new notice
 * (index 0) is never the one dropped: with three Undos showing, the oldest Undo goes instead. */
function trimDeck(ts: ToastItem[]): ToastItem[] {
  const out = [...ts];
  while (out.length > TOAST_MAX) {
    let drop = out.length - 1;
    for (let i = out.length - 1; i >= 1; i--) {
      if (!out[i]!.action) { drop = i; break; }
    }
    out.splice(drop, 1);
  }
  return out;
}

/** One store for the page (spec §11): who is signed in to the page, the miner's state, whether the
 * miner is reachable, and the latest sign-in event. Views read it; only actions write. */
interface Store {
  me: Me | null;
  state: State | null;
  connection: "live" | "lost";
  lostSince: Date | null;
  signin: SignIn | null;
  clearSignin: () => void;
  refreshMe: () => Promise<void>;
  refreshState: () => Promise<void>;
  /** Show (and announce) a notice. `undo` is shorthand for an "Undo" action. */
  say: (what: string | ToastSpec, undo?: () => void) => void;
  /** An error notice: `title` names what failed, the detail is the server's reason when it gave one. */
  sayError: (e: unknown, title: string) => void;
  announcement: string;
  toasts: ToastItem[];
  dismissToast: (id: number) => void;
  updated: boolean; // the server runs a newer build than this page was loaded with
}

const Ctx = createContext<Store | null>(null);

export function useApp(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useApp outside <AppProvider>");
  return s;
}

export function AppProvider({ children, initialMe = null, retryMs = 5000 }: { children: ReactNode; initialMe?: Me | null; retryMs?: number }) {
  const [me, setMe] = useState<Me | null>(initialMe);
  const [state, setState] = useState<State | null>(null);
  const [connection, setConnection] = useState<"live" | "lost">("live");
  const [lostSince, setLostSince] = useState<Date | null>(null);
  const [signin, setSignin] = useState<SignIn | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const firstBuild = useRef<string | null>(null);
  const [updated, setUpdated] = useState(false);
  const sayTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const refreshMe = useCallback(async () => {
    setMe(await api.get<Me>("/me"));
  }, []);
  const refreshState = useCallback(async () => {
    try {
      const s = await api.get<State>("/state");
      setState(s);
      if (s.build) {
        if (firstBuild.current === null) firstBuild.current = s.build;
        else if (s.build !== firstBuild.current) setUpdated(true);
      }
    } catch {
      /* the live connection decides reachability; a 401 is handled by the client */
    }
  }, []);
  const dismissToast = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);
  const say = useCallback((what: string | ToastSpec, undo?: () => void) => {
    const spec: ToastSpec = typeof what === "string" ? { title: what } : what;
    const action = spec.action ?? (undo ? { label: "Undo", run: undo } : undefined);
    const said = spec.detail ? `${spec.title}. ${spec.detail}` : spec.title;
    const text = action ? `${said} Alt+N to reach ${action.label}.` : said;
    // clear first so repeating the same message is announced again (as in the mockup)
    setAnnouncement("");
    clearTimeout(sayTimer.current);
    sayTimer.current = setTimeout(() => setAnnouncement(text), 30);
    const tone = spec.tone ?? "ok";
    const item: ToastItem = { id: ++toastSeq, title: spec.title, detail: spec.detail, tone, action,
      ms: action || tone === "bad" ? TOAST_LONG_MS : TOAST_MS };
    setToasts((ts) => trimDeck([item, ...ts]));
  }, []);
  const sayError = useCallback((e: unknown, title: string) => {
    say({ title, detail: e instanceof ApiError ? e.message : undefined, tone: "bad" });
  }, [say]);

  useEffect(() => {
    setUnauthorizedHandler(() => setMe((m) => (m ? { ...m, authenticated: false } : m)));
    if (!initialMe) refreshMe().catch(() => { setConnection("lost"); setLostSince(new Date()); });
  }, [initialMe, refreshMe]);

  // the miner was unreachable when the page loaded: keep asking until it answers (spec §9)
  useEffect(() => {
    if (me) return;
    const t = setInterval(() => {
      refreshMe().then(() => { setConnection("live"); setLostSince(null); }).catch(() => undefined);
    }, retryMs);
    return () => clearInterval(t);
  }, [me, refreshMe, retryMs]);
  const clearSignin = useCallback(() => setSignin(null), []);

  const authed = !!me?.authenticated;
  useEffect(() => {
    if (!authed) return;
    void refreshState();
    return connectLive({
      onRefetch: () => void refreshState(),
      onConnection: (live) => {
        setConnection(live ? "live" : "lost");
        setLostSince(live ? null : new Date());
      },
      // a 401 closes the stream: if the page session has expired, /me says so and the page shows
      // sign-in; if the miner is really gone, /me fails too and the lost timer carries on
      onClosed: () => void refreshMe().catch(() => undefined),
      onEvent: (kind: EventKind, data) => {
        if (kind === "signin" && data && typeof data === "object") setSignin(data as SignIn);
      },
    });
  }, [authed, refreshState, refreshMe]);

  const value = useMemo(
    () => ({ me, state, connection, lostSince, signin, clearSignin, refreshMe, refreshState, say, sayError, announcement,
      toasts, dismissToast, updated }),
    [me, state, connection, lostSince, signin, clearSignin, refreshMe, refreshState, say, sayError, announcement, toasts,
      dismissToast, updated],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** The notices, bottom right (centred above the tab bar on phones), newest in front. Each closes when the line
 * along its bottom runs out (a CSS animation, so its end is the timer); pointing at or tabbing into the deck
 * pauses every line. Not a live region: the store's announcement already speaks each one once. */
export function Toasts() {
  const { toasts, dismissToast } = useApp();
  // pointer and focus pause separately: a button that closes its notice takes focus with it and no blur
  // arrives, so closing counts as focus leaving; the pointer still has its own leave event
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const paused = hover || focus;
  const deck = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null); // where Alt+N came from, to go back after a button closes
  const close = (id: number) => {
    setFocus(false);
    dismissToast(id);
    const back = returnTo.current;
    returnTo.current = null;
    if (back?.isConnected) back.focus();
  };
  // the deck unmounts under the pointer when its last notice closes, so no leave arrives either
  useEffect(() => { if (!toasts.length) setHover(false); }, [toasts.length]);
  // a newer notice can push out the one holding focus: no blur arrives then either, so check, and hand
  // focus back to where Alt+N came from
  useEffect(() => {
    if (!focus || deck.current?.contains(document.activeElement)) return;
    setFocus(false);
    const back = returnTo.current;
    returnTo.current = null;
    if (back?.isConnected) back.focus();
  }, [toasts, focus]);
  // Alt+N: keyboard and screen-reader users reach Undo without tabbing across the page (the announcement
  // says so). Focusing the deck also pauses its timers.
  useEffect(() => {
    if (!toasts.length) return;
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey || e.code !== TOAST_KEY) return;
      // on a Mac, Option+N is the dead key for ˜: leave it alone while someone is typing
      const t = e.target as HTMLElement | null;
      if (e.key === "Dead" && t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      const first = deck.current?.querySelector<HTMLButtonElement>(".toast button");
      if (!first) return;
      e.preventDefault();
      const from = document.activeElement;
      if (from instanceof HTMLElement && !deck.current!.contains(from)) returnTo.current = from;
      first.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toasts.length]);
  if (!toasts.length) return null;
  return (
    <div ref={deck} className="toasts" role="region" aria-label="Notices" data-paused={paused || undefined}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      onFocus={() => setFocus(true)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) { setFocus(false); returnTo.current = null; } }}>
      {toasts.map((t, i) => (
        <div key={t.id} className={`toast ${t.tone}`} role="group" aria-label={t.title} data-depth={i}>
          <svg className="toast-i" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />{t.tone === "bad" ? <path d="M12 7v6M12 16.5v.5" /> : <path d="m8 12 3 3 5-6" />}
          </svg>
          <div className="toast-t"><b>{t.title}</b>{t.detail && <span className="toast-d">{t.detail}</span>}</div>
          {t.action && (
            <button className="toast-a" type="button" onClick={() => { t.action!.run(); close(t.id); }}>{t.action.label}</button>
          )}
          <button className="toast-x" type="button" aria-label={`Dismiss: ${t.title}`} onClick={() => close(t.id)}>×</button>
          <DrainBar ms={t.ms} onDone={() => dismissToast(t.id)} />
        </div>
      ))}
    </div>
  );
}

/** The line that drains along a notice's bottom edge; its animation's end closes the notice. */
function DrainBar({ ms, onDone }: { ms: number; onDone: () => void }) {
  const ref = useRef<HTMLSpanElement>(null);
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    const el = ref.current;
    const end = () => done.current();
    el?.addEventListener("animationend", end);
    return () => el?.removeEventListener("animationend", end);
  }, []);
  return <span ref={ref} className="toast-bar" aria-hidden="true" style={{ animationDuration: `${ms}ms` }} />;
}
