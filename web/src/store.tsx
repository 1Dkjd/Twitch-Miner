import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler, type Me, type SignIn, type State } from "./api/client";
import { connectLive, type EventKind } from "./api/live";

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
  say: (text: string, undo?: () => void) => void;
  announcement: string;
  toast: { id: number; text: string; undo?: () => void } | null;
  dismissToast: () => void;
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
  const [toast, setToast] = useState<Store["toast"]>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
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
  const dismissToast = useCallback(() => { clearTimeout(toastTimer.current); setToast(null); }, []);
  const say = useCallback((text: string, undo?: () => void) => {
    // clear first so repeating the same message is announced again (as in the mockup)
    setAnnouncement("");
    clearTimeout(sayTimer.current);
    sayTimer.current = setTimeout(() => setAnnouncement(text), 30);
    // and show it (asked for 2026-10-11: confirmations used to reach screen readers only)
    clearTimeout(toastTimer.current);
    setToast({ id: Date.now(), text, undo });
    toastTimer.current = setTimeout(() => setToast(null), undo ? 8000 : 4000);
  }, []);

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
    () => ({ me, state, connection, lostSince, signin, clearSignin, refreshMe, refreshState, say, announcement,
      toast, dismissToast, updated }),
    [me, state, connection, lostSince, signin, clearSignin, refreshMe, refreshState, say, announcement, toast,
      dismissToast, updated],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** The visible confirmation (bottom of the page). Screen readers already hear it through the live region,
 * so this is aria-hidden from the announcement point of view except for its Undo button. */
export function Toast() {
  const { toast, dismissToast } = useApp();
  if (!toast) return null;
  return (
    <div className="toast" role="status" aria-label="Notice" key={toast.id}>
      <span>{toast.text}</span>
      {toast.undo && (
        <button className="btn quiet" type="button" onClick={() => { toast.undo?.(); dismissToast(); }}>Undo</button>
      )}
      <button className="toast-x" type="button" aria-label="Dismiss" onClick={dismissToast}>×</button>
    </div>
  );
}
