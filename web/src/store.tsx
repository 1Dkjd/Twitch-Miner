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
  say: (text: string) => void;
  announcement: string;
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
  const sayTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const refreshMe = useCallback(async () => {
    setMe(await api.get<Me>("/me"));
  }, []);
  const refreshState = useCallback(async () => {
    try {
      setState(await api.get<State>("/state"));
    } catch {
      /* the live connection decides reachability; a 401 is handled by the client */
    }
  }, []);
  const say = useCallback((text: string) => {
    // clear first so repeating the same message is announced again (as in the mockup)
    setAnnouncement("");
    clearTimeout(sayTimer.current);
    sayTimer.current = setTimeout(() => setAnnouncement(text), 30);
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
      onEvent: (kind: EventKind, data) => {
        if (kind === "signin" && data && typeof data === "object") setSignin(data as SignIn);
      },
    });
  }, [authed, refreshState]);

  const value = useMemo(
    () => ({ me, state, connection, lostSince, signin, clearSignin, refreshMe, refreshState, say, announcement }),
    [me, state, connection, lostSince, signin, clearSignin, refreshMe, refreshState, say, announcement],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
