import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, api, type Settings } from "../api/client";
import { go } from "../router";
import { useApp } from "../store";
import { applyTheme, savedTheme, type Theme } from "../ui/theme";

/** Settings (approved mockup), limited to what works today. Notifications, channel points and the
 * password off-switch arrive with their features (phase 3 plan, decision 3). */
export function SettingsView() {
  const { state, refreshState, refreshMe, say } = useApp();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [theme, setTheme] = useState<Theme>(savedTheme());
  const [confirm, setConfirm] = useState(false);
  const signOutBtn = useRef<HTMLButtonElement>(null);
  const stayBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => { api.get<Settings>("/settings").then(setSettings).catch(() => undefined); }, []);
  useEffect(() => { if (confirm) stayBtn.current?.focus(); }, [confirm]);

  async function put(change: Partial<Settings>) {
    try { setSettings(await api.put<Settings>("/settings", change)); say("Saved"); }
    catch (e) { say(e instanceof ApiError ? e.message : "Couldn't save."); }
  }
  async function twitchSignOut() {
    setConfirm(false);
    await api.post("/twitch/signout").catch(() => undefined);
    say("Signed out of Twitch");
    void refreshState();
  }

  return (
    <section className="view" id="v-settings" aria-labelledby="h-settings">
      <div className="view-h"><h1 id="h-settings" className="disp" tabIndex={-1}>Settings</h1></div>
      <Set title="Twitch account">
        {state?.signed_in ? (
          <div className="opt">
            <div><div>Signed in as <b>{state.login}</b></div>
              <div className="d">Twitch reported no end date for this sign-in. If it ever ends, Overview says so.</div></div>
            <button ref={signOutBtn} className="btn" type="button" onClick={() => setConfirm(true)}>Sign out</button>
            {confirm && (
              <div className="confirm"><span>Mining stops until you sign in again with a new code.</span>
                <span className="acts">
                  <button ref={stayBtn} className="btn quiet" type="button" onClick={() => { setConfirm(false); signOutBtn.current?.focus(); }}>Stay signed in</button>
                  <button className="btn" type="button" onClick={twitchSignOut}>Sign out</button>
                </span></div>
            )}
          </div>
        ) : (
          <div className="opt">
            <div><div>Not signed in to Twitch</div><div className="d">Nothing is mined until you sign in.</div></div>
            <button className="btn strong" type="button" onClick={() => go("connect")}>Get a sign-in code</button>
          </div>
        )}
      </Set>
      <Set title="Mining">
        <div className="opt">
          <div><label htmlFor="m-badges">Also mine badge and emote campaigns</label>
            <div className="d">Campaigns whose rewards are only Twitch badges or emotes. They need no game account.</div></div>
          <input type="checkbox" className="sw" id="m-badges" disabled={!settings} checked={!!settings?.mine_badges}
            onChange={(e) => void put({ mine_badges: e.target.checked })} />
        </div>
      </Set>
      <Set title="This page">
        <div className="opt"><div>Theme</div>
          <div className="seg" role="group" aria-label="Theme">
            {(["system", "light", "dark"] as Theme[]).map((t) => (
              <button key={t} type="button" aria-pressed={theme === t} onClick={() => { setTheme(t); applyTheme(t); }}>
                {t.charAt(0).toUpperCase() + t.slice(1)}</button>
            ))}
          </div></div>
        <div className="opt">
          <div><div>Sign out of this page</div><div className="d">This browser will ask for the page password again. Mining carries on.</div></div>
          <button className="btn" type="button" onClick={async () => { await api.post("/logout").catch(() => undefined); await refreshMe(); }}>Sign out</button>
        </div>
      </Set>
    </section>
  );
}

function Set({ title, children }: { title: string; children: ReactNode }) {
  return <div className="set"><h2>{title}</h2>{children}</div>;
}
