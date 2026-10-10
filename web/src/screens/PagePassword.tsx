import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";
import { go } from "../router";
import { useApp } from "../store";
import { Icon } from "../ui/Icons";

export function Steps({ now }: { now: 1 | 2 }) {
  return (
    <ol className="auth-steps" aria-label="Setup steps">
      <li data-st={now === 1 ? "now" : "done"}>
        <span className="n">{now === 1 ? "1" : "✓"}</span>Page password
      </li>
      <li aria-hidden="true"><span className="auth-sep" /></li>
      <li data-st={now === 2 ? "now" : "todo"}>
        <span className="n">2</span>Twitch account
      </li>
    </ol>
  );
}

function PasswordInput(props: { id: string; value: string; onChange: (v: string) => void; autoComplete: string; invalid?: boolean; describedBy?: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="auth-inp">
      <input id={props.id} type={show ? "text" : "password"} autoComplete={props.autoComplete} value={props.value}
        aria-invalid={props.invalid || undefined} aria-describedby={props.describedBy}
        onChange={(e) => props.onChange(e.target.value)} />
      <button className="btn quiet show" type="button" onClick={() => setShow(!show)}>{show ? "Hide" : "Show"}</button>
    </div>
  );
}

/** First run, step 1 (docs/design/signin-mockup.html "Protect this page"). */
export function SetupScreen() {
  const { refreshMe } = useApp();
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const checks: [boolean, string][] = [[a.length >= 8, "At least 8 characters"], [a.length > 0 && a === b, "Both entries match"]];
  const ok = checks.every((c) => c[0]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ok || busy) return;
    setBusy(true);
    try {
      await api.post("/setup", { password: a });
      try { sessionStorage.setItem("dw-first-run", "1"); } catch { /* storage blocked: steps just won't show */ }
      go("connect");
      await refreshMe();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the miner. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-stage"><div className="auth-col">
      <Steps now={1} />
      <div className="auth-head"><h1 id="h-setup" tabIndex={-1}>Protect this page</h1>
        <p>Anyone who can open this address on your network could pause mining or change your lists. Choose a password for this page. It isn't your Twitch password.</p></div>
      <form className="auth-card" noValidate onSubmit={submit}>
        <div><label className="auth-label" htmlFor="pw1">Page password</label>
          <PasswordInput id="pw1" value={a} onChange={setA} autoComplete="new-password" /></div>
        <div><label className="auth-label" htmlFor="pw2">Type it again</label>
          <PasswordInput id="pw2" value={b} onChange={setB} autoComplete="new-password" />
          <ul className="auth-checks" aria-live="polite">
            {checks.map(([good, text]) => <li key={text} data-ok={good}><Icon name={good ? "check" : "dot"} />{text}</li>)}
          </ul></div>
        {error && <p className="auth-err" role="alert"><Icon name="alert" />{error}</p>}
        <button className="btn strong wide" type="submit" aria-disabled={!ok || busy}>Set password and continue</button>
      </form>
      <p className="auth-fine">Your browser stays signed in to this page for 30 days.</p>
    </div></div>
  );
}

/** Later visits (signin-mockup.html "Enter the page password"). */
export function LoginScreen() {
  const { refreshMe } = useApp();
  const [pw, setPw] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!pw || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.post("/login", { password: pw });
      await refreshMe();
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401
        ? "That isn't the page password. Check it and try again."
        : "Couldn't reach the miner. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-stage"><div className="auth-col">
      <div className="auth-head"><h1 id="h-login" tabIndex={-1}>Enter the page password</h1>
        <p>This is the password chosen when Dropwatch was set up, not your Twitch password.</p></div>
      <form className="auth-card" noValidate onSubmit={submit}>
        <div><label className="auth-label" htmlFor="pw">Page password</label>
          <PasswordInput id="pw" value={pw} onChange={setPw} autoComplete="current-password" invalid={!!error} describedBy={error ? "pw-err" : undefined} />
          {error && <p className="auth-err" id="pw-err" role="alert"><Icon name="alert" />{error}</p>}</div>
        <button className="btn strong wide" type="submit" aria-disabled={busy}>Sign in</button>
      </form>
      <p className="auth-fine">Stays signed in on this browser for 30 days.</p>
    </div></div>
  );
}
