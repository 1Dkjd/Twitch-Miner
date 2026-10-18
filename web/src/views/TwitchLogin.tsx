import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import { useApp } from "../store";

type Status = { status: "idle" | "starting" | "open" | "done" | "failed" | string; message: string; available: boolean };

/** Characters as X keysyms: Latin-1 maps to itself, everything else to the Unicode keysym range. */
export function keysymFor(ch: string): number {
  const cp = ch.codePointAt(0)!;
  if (ch === "\n") return 0xff0d; // Return
  if ((cp >= 0x20 && cp <= 0x7e) || (cp >= 0xa0 && cp <= 0xff)) return cp;
  return 0x01000000 + cp;
}

type RfbLike = { scaleViewport: boolean; focusOnClick: boolean; background: string;
  sendKey(keysym: number, code: string | null, down?: boolean): void; focus(): void; disconnect(): void;
  addEventListener(type: string, fn: (e: Event) => void): void };

/** Sign in on Twitch's real login page (2026-10-18). The container runs Chromium on a virtual screen; this shows
 * it live (noVNC over Dropwatch's own WebSocket) so the owner signs in as usual, and Dropwatch keeps the
 * Android-app token Twitch issues, which lists every campaign and its account links. */
export function TwitchLogin({ kind }: { kind: string | null }) {
  const { say, refreshState } = useApp();
  const [st, setSt] = useState<Status | null>(null);
  const [open, setOpen] = useState(false);
  const poll = useCallback(async () => {
    try { setSt(await api.get<Status>("/twitch/browser")); } catch { /* shown as unavailable */ }
  }, []);
  useEffect(() => { void poll(); }, [poll]);
  useEffect(() => {
    if (!open) return;
    const t = setInterval(() => void poll(), 1000);
    return () => clearInterval(t);
  }, [open, poll]);
  useEffect(() => {
    if (!open || !st) return;
    if (st.status === "done") {
      setOpen(false);
      say(st.message || "Signed in");
      void refreshState();
    } else if (st.status === "idle") setOpen(false);
  }, [st, open, say, refreshState]);

  async function start() {
    try { setSt(await api.post<Status>("/twitch/browser")); setOpen(true); }
    catch (e) { say({ title: e instanceof ApiError ? e.message : "Couldn't start the sign-in browser", tone: "bad" }); }
  }
  async function cancel() {
    try { await api.del("/twitch/browser"); } catch { /* closes anyway */ }
    setOpen(false);
    void poll();
  }

  if (st && !st.available) return null; // a dev install without Chromium: nothing to offer
  return (
    <div className="opt">
      <div><div>Sign in on Twitch's login page {kind === "android" && <span className="chip green">In use</span>}</div>
        <div className="d">Shows every campaign straight from Twitch, and whether each game account is linked, before it
          starts. The code sign-in can't: Twitch hides that from it. Twitch's login page opens right here; sign in as usual.</div>
        {st?.status === "failed" && !open && <div className="d bad" role="status">{st.message}</div>}</div>
      <button className="btn strong" type="button" onClick={() => void start()}>Sign in on Twitch's page</button>
      {open && <LoginWindow st={st} onCancel={() => void cancel()} />}
    </div>
  );
}

function LoginWindow({ st, onCancel }: { st: Status | null; onCancel: () => void }) {
  const screen = useRef<HTMLDivElement>(null);
  const rfb = useRef<RfbLike | null>(null);
  const [lost, setLost] = useState(false);
  const [text, setText] = useState("");
  const live = st?.status === "open";

  useEffect(() => {
    if (!live || !screen.current) return;
    let gone = false;
    void import("@novnc/novnc").then(({ default: RFB }) => {
      if (gone || !screen.current) return;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const r = new RFB(screen.current, `${proto}//${location.host}/api/twitch/browser/vnc`, { wsProtocols: ["binary"] }) as unknown as RfbLike;
      r.scaleViewport = true;
      r.focusOnClick = true;
      r.background = "transparent";
      r.addEventListener("disconnect", () => setLost(true));
      r.addEventListener("connect", () => { setLost(false); r.focus(); });
      rfb.current = r;
    });
    return () => { gone = true; rfb.current?.disconnect(); rfb.current = null; };
  }, [live]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape" && e.target === document.body) onCancel(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onCancel]);

  function typeIt() {
    const r = rfb.current;
    if (!r || !text) return;
    for (const ch of text) r.sendKey(keysymFor(ch), null);
    setText("");
    r.focus();
  }

  return (
    <div className="tl-back">
      <div className="tl" role="dialog" aria-modal="true" aria-labelledby="tl-h">
        <div className="tl-top">
          <div>
            <h2 id="tl-h">Sign in to Twitch</h2>
            <div className="d" role="status">{lost && live ? "Reconnecting to the sign-in browser…" : st?.message}</div>
          </div>
          <button className="btn quiet" type="button" onClick={onCancel}>Cancel</button>
        </div>
        <div className="tl-screen" ref={screen} aria-label="Twitch's login page, running in Dropwatch">
          {!live && <div className="tl-wait">{st?.status === "failed" ? st.message : "Starting the sign-in browser…"}</div>}
        </div>
        <form className="tl-type" onSubmit={(e) => { e.preventDefault(); typeIt(); }}>
          <label htmlFor="tl-text">Password manager?</label>
          <input id="tl-text" type="password" autoComplete="current-password" value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Paste here, then click Type it" disabled={!live} />
          <button className="btn" type="submit" disabled={!live || !text}>Type it</button>
          <span className="d">Click the field on Twitch's page first. This page can't paste into it directly.</span>
        </form>
      </div>
    </div>
  );
}
