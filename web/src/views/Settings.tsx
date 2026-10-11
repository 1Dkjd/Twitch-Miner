import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, api, type About, type Settings } from "../api/client";
import { go } from "../router";
import { useApp } from "../store";
import { clock, day } from "../ui/format";
import { applyTheme, savedTheme, type Theme } from "../ui/theme";
import { Notifications } from "./Notifications";

/** Settings (approved mockup), limited to what works today. Notifications follow their own approved mockup
 * (docs/design/notifications-mockup.html); channel points and the password off-switch arrive with their features. */
export function SettingsView() {
  const { state, refreshState, refreshMe, say } = useApp();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [about, setAbout] = useState<About | null>(null);
  const [restored, setRestored] = useState(0); // remounts Notifications so it re-reads its channels
  const [theme, setTheme] = useState<Theme>(savedTheme());
  const [confirm, setConfirm] = useState(false);
  const signOutBtn = useRef<HTMLButtonElement>(null);
  const stayBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => { api.get<Settings>("/settings").then(setSettings).catch(() => undefined); }, []);
  useEffect(() => { api.get<About>("/about").then(setAbout).catch(() => undefined); }, []);
  useEffect(() => { if (confirm) stayBtn.current?.focus(); }, [confirm]);

  async function put(change: Partial<Settings>) {
    try { setSettings(await api.put<Settings>("/settings", change)); say("Saved"); }
    catch (e) { say(e instanceof ApiError ? e.message : "Couldn't save."); }
  }
  async function twitchSignOut() {
    setConfirm(false);
    try { await api.post("/twitch/signout"); say("Signed out of Twitch"); }
    catch (e) { say(e instanceof ApiError ? e.message : "Couldn't sign out."); }
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
      <Notifications key={restored} settings={settings} put={put} serverTz={about?.server_tz} />
      <Set title="Mining">
        <div className="opt">
          <div><label htmlFor="m-badges">Also mine badge and emote campaigns</label>
            <div className="d">Campaigns whose rewards are only Twitch badges or emotes. They need no game account.</div></div>
          <input type="checkbox" className="sw" id="m-badges" disabled={!settings} checked={!!settings?.mine_badges}
            onChange={(e) => void put({ mine_badges: e.target.checked })} />
        </div>
        <div className="opt">
          <div><label htmlFor="m-points">Also claim channel points</label>
            <div className="d">Opens the bonus chest on whichever channel is being watched.</div></div>
          <input type="checkbox" className="sw" id="m-points" disabled={!settings} checked={!!settings?.claim_points}
            onChange={(e) => void put({ claim_points: e.target.checked })} />
        </div>
        <div className="opt">
          <div><label htmlFor="m-every">Check Twitch for campaign changes</label>
            <div className="d">How often Dropwatch re-reads the campaign list, so new campaigns and accounts you've just linked can take this long (plus a few minutes) to show up. Check Twitch at the top checks now.</div></div>
          <select id="m-every" className="inline-sel" disabled={!settings} value={settings?.campaigns_every_minutes ?? 60}
            onChange={(e) => void put({ campaigns_every_minutes: Number(e.target.value) as 15 | 30 | 60 | 120 | 240 })}>
            {EVERY.map(([m, label]) => <option key={m} value={m}>{label}</option>)}
          </select>
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
          <button className="btn" type="button" onClick={async () => {
            try { await api.post("/logout"); } catch (e) { say(e instanceof ApiError ? e.message : "Couldn't sign out."); }
            await refreshMe().catch(() => undefined);
          }}>Sign out</button>
        </div>
      </Set>
      <Backup onRestored={() => {
        setRestored((n) => n + 1);
        api.get<Settings>("/settings").then(setSettings).catch(() => undefined);
        void refreshState();
      }} />
      {about && (
        <Set title="About">
          <div className="opt"><div>
            <div>Dropwatch <b>{about.version}</b>{about.commit && <> <span className="mono">{about.commit}</span></>}</div>
            <div className="d">Running since {day(about.started_at)} {clock(about.started_at)}
              {about.campaigns_at ? ` · Campaign list updated ${clock(about.campaigns_at)}` : ""}</div>
          </div></div>
        </Set>
      )}
    </section>
  );
}

/** Settings › Backup (approved mockup docs/design/pre-docker-mockup.html, 2026-10-10). Saving is a plain
 * download link (the page cookie goes with it); restoring reads the file here and asks before replacing. */
function Backup({ onRestored }: { onRestored: () => void }) {
  const { say } = useApp();
  const [secrets, setSecrets] = useState(false);
  const [pending, setPending] = useState<{ data: unknown; made: string | null } | null>(null);
  const [note, setNote] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const tell = (text: string) => { setNote(text); say(text); };

  async function pick(file: File | undefined) {
    if (!file) return;
    if (fileRef.current) fileRef.current.value = ""; // the same file can be picked again
    let data: unknown;
    try { data = JSON.parse(await file.text()); } catch { tell("That file isn't a Dropwatch backup."); return; }
    const made = data && typeof data === "object" && "made_at" in data && typeof data.made_at === "string" ? data.made_at : null;
    setNote("");
    setPending({ data, made });
  }
  async function replace() {
    if (!pending) return;
    const { data } = pending;
    setPending(null);
    try {
      const r = await api.post<{ skipped: string[] }>("/restore", data);
      tell(r.skipped.length ? `Backup restored. Skipped what this version doesn't know: ${r.skipped.join(", ")}.` : "Backup restored.");
      onRestored();
    } catch (e) { tell(e instanceof ApiError ? e.message : "Couldn't restore it."); }
  }

  return (
    <Set title="Backup">
      <div className="opt">
        <div><div>Save a backup</div>
          <div className="d">Priority, Never, pins, favourite channels, settings and notification channels, in one file.</div>
          <label className="chk"><input type="checkbox" checked={secrets} onChange={(e) => setSecrets(e.target.checked)} />
            Include notification secrets (tokens and webhook URLs)</label></div>
        <a className="btn" href={secrets ? "/api/backup?secrets=true" : "/api/backup"} download>Save a backup</a>
      </div>
      <div className="opt">
        <div><div>Restore from a backup</div>
          <div className="d">Replaces your lists and settings with the file's. Your Twitch sign-in, page password and History stay as they are.</div>
          {note && <div className="d" role="status">{note}</div>}</div>
        <label className="btn">Choose a file…<input ref={fileRef} type="file" accept="application/json,.json" className="sr"
          aria-label="Restore from a backup" onChange={(e) => void pick(e.target.files?.[0])} /></label>
        {pending && (
          <div className="confirm"><span>Replace your lists, settings and notification channels with this backup
            {pending.made ? ` from ${day(pending.made)} ${clock(pending.made)}` : ""}?</span>
            <span className="acts">
              <button className="btn quiet" type="button" onClick={() => setPending(null)}>Keep mine</button>
              <button className="btn" type="button" onClick={() => void replace()}>Replace</button>
            </span></div>
        )}
      </div>
    </Set>
  );
}

const EVERY: [number, string][] = [[15, "Every 15 min"], [30, "Every 30 min"], [60, "Every hour"], [120, "Every 2 hours"], [240, "Every 4 hours"]];

function Set({ title, children }: { title: string; children: ReactNode }) {
  return <div className="set"><h2>{title}</h2>{children}</div>;
}
