import QRCode from "qrcode";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, type SignIn } from "../api/client";
import { go } from "../router";
import { useApp } from "../store";
import { Icon } from "../ui/Icons";
import { Steps } from "./PagePassword";

/** Twitch code sign-in (docs/design/signin-options.html option A): Ready -> Code -> Connected,
 * with Expired / Failed. The miner polls Twitch; this page just shows the code and follows the
 * status (SSE `signin` events, with a slow poll as a fallback). */
export function ConnectScreen({ pollMs = 3000 }: { pollMs?: number }) {
  const { state, signin: pushed, clearSignin, refreshState, say } = useApp();
  const [status, setStatus] = useState<SignIn | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  let first = false;
  try { first = sessionStorage.getItem("dw-first-run") === "1"; } catch { /* storage blocked */ }
  const again = !first;

  const read = useCallback(async () => {
    try { setStatus(await api.get<SignIn>("/twitch/signin")); } catch { /* keep the last status */ }
  }, []);
  useEffect(() => { clearSignin(); void read(); }, [read, clearSignin]); // pushes from before now are stale
  useEffect(() => { if (pushed) setStatus(pushed); }, [pushed]);
  useEffect(() => {
    if (status?.status !== "waiting") return;
    const t = setInterval(read, pollMs);
    return () => clearInterval(t);
  }, [status?.status, read, pollMs]);
  // "done" is only believed if this screen saw the wait, or Twitch is actually signed in: the server
  // keeps the last outcome, so a done from an earlier sign-in must not hide the code button
  const sawWaiting = useRef(false);
  if (status?.status === "waiting") sawWaiting.current = true;
  const raw = status?.status ?? "idle";
  const s = raw === "done" && !(sawWaiting.current || state?.signed_in) ? "idle" : raw;
  useEffect(() => {
    if (s === "done") { void refreshState(); say("Connected to Twitch"); }
  }, [s, refreshState, say]);

  async function start() {
    setBusy(true);
    setError("");
    try {
      setStatus(await api.post<SignIn>("/twitch/signin"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) await read();
      else setError(e instanceof ApiError ? e.message : "Couldn't reach the miner. Try again.");
    } finally {
      setBusy(false);
    }
  }
  async function cancel() {
    await api.del("/twitch/signin").catch(() => undefined);
    setStatus({ status: "idle", message: "" });
  }
  function finish() {
    try { sessionStorage.removeItem("dw-first-run"); } catch { /* ignore */ }
    go("overview");
  }

  return (
    <div className="auth-stage"><div className="auth-col">
      {!again && <Steps now={2} />}
      <div className="auth-head">
        <h1 id="h-connect" tabIndex={-1}>{s === "done" && again ? "You're signed back in" : again ? "Sign in to Twitch again" : "Connect your Twitch account"}</h1>
        <p>{again ? (s === "done" ? "Mining picks up where it stopped." : "Twitch ended the session, so mining stopped. Drop progress is kept on Twitch and carries on once you're back.") : "Use the account that should earn the drops."}</p>
      </div>
      {s === "waiting" && status ? <CodeCard status={status} onCancel={cancel} />
        : s === "done" ? (
          <div className="auth-card">
            <div className="auth-status" data-tone="ok"><Icon name="check" /><div>
              <div className="auth-status-t">Connected</div>
              <div className="auth-status-b">Mining starts now. Your campaigns appear on Overview within a minute.</div></div></div>
            {state?.login && <span className="auth-who"><span className="av">{state.login.charAt(0).toUpperCase()}</span>{state.login}</span>}
            <button className="btn strong wide" type="button" onClick={finish}>Go to Overview</button>
          </div>)
        : s === "expired" || s === "failed" ? (
          <div className="auth-card">
            <div className="auth-status" data-tone="alert"><Icon name="alert" /><div>
              <div className="auth-status-t">{s === "expired" ? "That code expired" : "Sign-in didn't finish"}</div>
              <div className="auth-status-b">{s === "expired" ? "Codes last 30 minutes. Get a new one and enter it at twitch.tv/activate." : status?.message}</div></div></div>
            <button className="btn strong wide" type="button" onClick={start} aria-disabled={busy}><Icon name="key" />Get a new code</button>
          </div>)
        : (
          <div className="auth-card">
            <ol className="auth-how">
              <li><div><b>Get a code here.</b> <span>Eight letters, valid for 30 minutes.</span></div></li>
              <li><div><b>Enter it at twitch.tv/activate.</b> <span>On this device or any other, phone included. You sign in to Twitch there as usual.</span></div></li>
              <li><div><b>Click Authorize on Twitch.</b> <span>This page notices on its own and starts mining.</span></div></li>
            </ol>
            {error && <p className="auth-err" role="alert"><Icon name="alert" />{error}</p>}
            <button className="btn strong wide" type="button" onClick={start} aria-disabled={busy}><Icon name="key" />Get a sign-in code</button>
          </div>)}
    </div></div>
  );
}

function CodeCard({ status, onCancel }: { status: SignIn; onCancel: () => void }) {
  const { say } = useApp();
  const code = status.code ?? "";
  const url = status.verification_uri ?? "https://www.twitch.tv/activate";
  const [svg, setSvg] = useState("");
  const [left, setLeft] = useState(() => secondsLeft(status.expires_at));
  const codeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    QRCode.toString(url, { type: "svg", margin: 0, errorCorrectionLevel: "M" })
      .then((s) => { if (live) setSvg(s); })
      .catch(() => setSvg(""));
    return () => { live = false; };
  }, [url]);
  useEffect(() => {
    const t = setInterval(() => setLeft(secondsLeft(status.expires_at)), 1000);
    return () => clearInterval(t);
  }, [status.expires_at]);

  async function copy() {
    try { await navigator.clipboard.writeText(code); say("Code copied"); }
    catch { const sel = getSelection(); if (sel && codeRef.current) sel.selectAllChildren(codeRef.current); }
  }

  return (
    <div className="auth-card">
      <div className="code-box">
        <div>
          <div className="code-lab">Your code</div>
          <div className="code-big" ref={codeRef} aria-label={`Code ${code.split("").join(" ")}`}>
            <span>{code.slice(0, 4)}</span><span>{code.slice(4)}</span>
          </div>
          <div className="code-acts">
            <button className="btn" type="button" onClick={copy}><Icon name="copy" />Copy code</button>
            <a className="btn" href={url} target="_blank" rel="noopener noreferrer">Open twitch.tv/activate<Icon name="ext" /></a>
          </div>
        </div>
        {svg && <div className="qr-w"><div className="qr" role="img" aria-label="QR code for twitch.tv/activate" dangerouslySetInnerHTML={{ __html: svg }} /><div className="qr-cap">Scan with your phone</div></div>}
      </div>
      <div className="wait-row">
        <span className="waiting"><span className="spin" aria-hidden="true" />Waiting for you to authorize on Twitch</span>
        {left !== null && <span className="auth-fine ml-auto">Expires in <span className="num">{fmt(left)}</span></span>}
      </div>
      <button className="btn quiet" type="button" style={{ justifySelf: "start" }} onClick={onCancel}>Cancel</button>
    </div>
  );
}

function secondsLeft(at: string | null | undefined): number | null {
  if (!at) return null;
  return Math.max(0, Math.round((new Date(at).getTime() - Date.now()) / 1000));
}
const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
