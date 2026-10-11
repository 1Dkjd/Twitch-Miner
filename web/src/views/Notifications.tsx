import { useEffect, useRef, useState } from "react";
import { ApiError, api, type NotifyChannel, type NotifyChannels, type NotifyTest, type Settings } from "../api/client";
import { useApp } from "../store";
import { zones } from "../ui/zones";
import { MenuButton } from "./Menu";

type Toggle = { key: keyof Settings & `notify_${string}`; label: string; d: string; minutes?: { key: keyof Settings; min: number; max: number; before: string; after: string } };

/** The approved mockup (docs/design/notifications-mockup.html, 2026-10-10): failures on by default, "a campaign
 * needs you" off; each alert is sent once when the problem starts and once when it's fixed (alerts.py). */
const TOGGLES: Toggle[] = [
  { key: "notify_signin", label: "Twitch sign-in stops working", d: "Mining stops until you sign in again with a new code." },
  { key: "notify_unreachable", label: "Twitch can't be reached", d: "",
    minutes: { key: "notify_unreachable_minutes", min: 5, max: 240, before: "Checks have been failing for", after: "minutes." } },
  { key: "notify_not_earning", label: "Mining isn't earning", d: "",
    minutes: { key: "notify_not_earning_minutes", min: 10, max: 240, before: "", after: "minutes of watching with no new minutes. Usually means Twitch changed something." } },
  { key: "notify_claim_failed", label: "A reward couldn't be claimed", d: "Twitch turned down a finished drop." },
  { key: "notify_stopped", label: "Mining stopped on an error", d: "Something inside Dropwatch failed and mining stopped." },
  { key: "notify_needs_you", label: "A campaign needs you", d: "A campaign's game account isn't linked, so it can't be mined." },
];

/** The weekly summary's day (0 = Monday, as the server counts) and hour, in the chosen zone ("" = the server's). */
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const HOURS = Array.from({ length: 24 }, (_, h) => h);

export function Notifications({ settings, put, serverTz }: {
  settings: Settings | null; put: (c: Partial<Settings>) => Promise<void>; serverTz?: string;
}) {
  const { say } = useApp();
  const [chans, setChans] = useState<NotifyChannels | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [test, setTest] = useState<NotifyTest | null>(null);
  const [testing, setTesting] = useState(false);
  useEffect(() => { api.get<NotifyChannels>("/notify/channels").then(setChans).catch(() => undefined); }, []);

  async function change(kind: string, values: Record<string, string>) {
    try { setChans(await api.put<NotifyChannels>(`/notify/channels/${kind}`, { values })); return true; }
    catch (e) { say(e instanceof ApiError ? e.message : "Couldn't save."); return false; }
  }
  async function add(kind: string, name: string) {
    if (await change(kind, {})) { setEditing(kind); say(`${name} added`); }
  }
  async function remove(c: NotifyChannel) {
    try { setChans(await api.del<NotifyChannels>(`/notify/channels/${c.type}`)); say(`${c.name} removed`); }
    catch (e) { say(e instanceof ApiError ? e.message : "Couldn't remove it."); }
  }
  async function sendTest() {
    setTesting(true);
    try { const r = await api.post<NotifyTest>("/notify/test"); setTest(r); say(r.message); }
    catch (e) { say(e instanceof ApiError ? e.message : "Couldn't send."); }
    finally { setTesting(false); }
  }

  return (
    <div className="set">
      <h2>Notifications</h2>
      <p className="nt-hint">Dropwatch tells you when something stops it mining. Each alert is sent once when the problem starts and once when it's fixed.</p>
      <div className="nt-lab">What to notify</div>
      {TOGGLES.map((t) => (
        <div className="opt" key={t.key}>
          <div><label htmlFor={t.key}>{t.label}</label>
            <div className="d">{t.minutes ? <Minutes t={t} settings={settings} put={put} /> : t.d}</div></div>
          <input type="checkbox" className="sw" id={t.key} disabled={!settings} checked={!!settings?.[t.key]}
            onChange={(e) => void put({ [t.key]: e.target.checked })} />
        </div>
      ))}
      <div className="nt-lab">Summaries and rewards</div>
      <div className="opt">
        <div><label htmlFor="notify_weekly">Weekly summary</label>
          <div className="d">Every <select className="inline-sel" aria-label="Day" disabled={!settings} value={settings?.notify_weekly_day ?? 6}
            onChange={(e) => void put({ notify_weekly_day: Number(e.target.value) })}>
            {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select> at <select className="inline-sel" aria-label="Time"
            disabled={!settings} value={settings?.notify_weekly_hour ?? 18} onChange={(e) => void put({ notify_weekly_hour: Number(e.target.value) })}>
            {HOURS.map((h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}</select> in <select className="inline-sel"
            aria-label="Time zone" disabled={!settings} value={settings?.notify_weekly_tz ?? ""}
            onChange={(e) => void put({ notify_weekly_tz: e.target.value })}>
            <option value="">{serverTz ? `Server time (${serverTz})` : "Server time"}</option>
            {settings?.notify_weekly_tz && !zones().some((z) => z.id === settings.notify_weekly_tz) && (
              <option value={settings.notify_weekly_tz}>{settings.notify_weekly_tz}</option>)}
            {zones().map((z) => <option key={z.id} value={z.id}>{z.label}</option>)}</select>: what was claimed, what was
            missed, and anything that needs you.</div></div>
        <input type="checkbox" className="sw" id="notify_weekly" disabled={!settings} checked={!!settings?.notify_weekly}
          onChange={(e) => void put({ notify_weekly: e.target.checked })} />
      </div>
      <div className="opt">
        <div><label htmlFor="notify_claimed">A reward is claimed</label>
          <div className="d">One message per reward; several within a minute arrive as one.</div></div>
        <input type="checkbox" className="sw" id="notify_claimed" disabled={!settings} checked={!!settings?.notify_claimed}
          onChange={(e) => void put({ notify_claimed: e.target.checked })} />
      </div>
      <div className="nt-lab">How you're notified</div>
      <div className="nt-how">
        {chans?.channels.map((c) => (
          <ChannelCard key={c.type} c={c} open={editing === c.type} onToggle={() => setEditing(editing === c.type ? null : c.type)}
            onSave={(values) => change(c.type, values)} onRemove={() => remove(c)} />
        ))}
        {chans && chans.available.length > 0 && (
          <MenuButton id="add-channel" label="Add a channel" wrapClass="nt-add" buttonClass="btn"
            buttonContent={<>+ Add a channel</>}
            items={chans.available.map((a) => ({ key: a.type, content: a.name, onSelect: () => void add(a.type, a.name) }))} />
        )}
        <div className="nt-test">
          <button className="btn" type="button" disabled={testing} onClick={sendTest}>Send test notification</button>
          {test && <span className={test.ok ? "ok" : "bad"}>{test.message}</span>}
        </div>
      </div>
    </div>
  );
}

function Minutes({ t, settings, put }: { t: Toggle; settings: Settings | null; put: (c: Partial<Settings>) => Promise<void> }) {
  const { say } = useApp();
  const m = t.minutes!;
  const saved = settings ? Number(settings[m.key]) : null;
  const [draft, setDraft] = useState<string>(saved == null ? "" : String(saved));
  useEffect(() => { if (saved != null) setDraft(String(saved)); }, [saved]);
  function commit() {
    const n = Number(draft);
    if (draft === "" || !Number.isInteger(n) || n < m.min || n > m.max) {
      say(`Pick ${m.min} to ${m.max} minutes.`);
      if (saved != null) setDraft(String(saved));
      return;
    }
    if (n !== saved) void put({ [m.key]: n });
  }
  return (
    <>{m.before && `${m.before} `}<input className="mins" type="number" inputMode="numeric" min={m.min} max={m.max} step={1}
      aria-label={`Minutes before the ${t.label} alert`} disabled={!settings} value={draft}
      onChange={(e) => setDraft(e.target.value)} onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} /> {m.after}</>
  );
}

function ChannelCard({ c, open, onToggle, onSave, onRemove }: {
  c: NotifyChannel; open: boolean; onToggle: () => void;
  onSave: (values: Record<string, string>) => Promise<boolean>; onRemove: () => void;
}) {
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => { if (open) first.current?.focus(); }, [open]);
  return (
    <div className="ch">
      <div className="ch-head">
        <span className={`ch-dot${c.configured ? "" : " off"}`} aria-hidden="true" />
        <span className="ch-name">{c.name}</span><span className="ch-sum">{c.summary}</span>
        <span className="ch-acts">
          <button className="btn quiet" type="button" aria-expanded={open} aria-controls={`ch-${c.type}`} onClick={onToggle}>{open ? "Done" : "Edit"}</button>
          <button className="btn quiet" type="button" aria-label={`Remove ${c.name}`} onClick={onRemove}>✕</button>
        </span>
      </div>
      <div className="ch-ed" id={`ch-${c.type}`} hidden={!open}>
        {c.fields.map((f, i) => (
          <Field key={f.key} f={f} inputRef={i === 0 ? first : undefined} onSave={(v) => onSave({ [f.key]: v })} />
        ))}
        <div className="d">{c.hint}</div>
      </div>
    </div>
  );
}

/** A secret is never sent back by the server: its box starts empty and saving clears it again. */
function Field({ f, inputRef, onSave }: {
  f: NotifyChannel["fields"][number]; inputRef?: React.Ref<HTMLInputElement>; onSave: (v: string) => Promise<boolean>;
}) {
  const [v, setV] = useState(f.value);
  useEffect(() => { setV(f.value); }, [f.value]);
  async function commit() {
    if (f.secret ? v === "" : v === f.value) return; // nothing typed: keep what is saved
    if (await onSave(v) && f.secret) setV("");
  }
  return (
    <input ref={inputRef} className="field" type={f.secret ? "password" : "text"} aria-label={f.label} autoComplete="off"
      spellCheck={false} value={v} placeholder={f.secret && f.set ? "Saved. Type a new one to replace it." : f.label}
      onChange={(e) => setV(e.target.value)} onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
  );
}
