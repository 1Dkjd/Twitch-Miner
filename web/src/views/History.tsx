import { useEffect, useState, type ReactNode } from "react";
import { api, type Claim, type History, type State } from "../api/client";
import type { components } from "../api/types";
import { useApp } from "../store";
import { NB, boxArt, clock, day, dur } from "../ui/format";
import { Icon } from "../ui/Icons";

export interface DayGroup {
  key: string;
  label: string;
  rows: { campaign_id: string; campaign: string; game: string; first: Date; last: Date; rewards: Claim["rewards"]; claims: Claim[] }[];
}

/** Claims arrive flat in UTC; days are the VIEWER's days (the server can't know the zone), newest first,
 * one row per campaign per day. */
export function groupByDay(claims: Claim[], timeZone?: string): DayGroup[] {
  const keyFmt = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" });
  const labelFmt = new Intl.DateTimeFormat("en-GB", { timeZone, weekday: "short", day: "numeric", month: "short" });
  const days = new Map<string, DayGroup>();
  for (const c of [...claims].sort((a, b) => +new Date(b.at) - +new Date(a.at))) {
    const at = new Date(c.at);
    const key = keyFmt.format(at);
    let g = days.get(key);
    if (!g) { g = { key, label: labelFmt.format(at).replace(",", ""), rows: [] }; days.set(key, g); }
    let row = g.rows.find((r) => r.campaign_id === c.campaign_id);
    if (!row) { row = { campaign_id: c.campaign_id, campaign: c.campaign, game: c.game, first: at, last: at, rewards: [], claims: [] }; g.rows.push(row); }
    row.rewards.push(...c.rewards);
    row.claims.push(c);
    if (at < row.first) row.first = at;
    if (at > row.last) row.last = at;
  }
  return [...days.values()];
}

const PERIODS: [number, string, string][] = [[1, "24 hours", "Last 24 hours"], [7, "7 days", "Last 7 days"], [30, "30 days", "Last 30 days"], [90, "90 days", "Last 90 days"], [365, "Year", "Last year"]];
const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });

export function HistoryView() {
  const { state } = useApp();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<History | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  useEffect(() => {
    let live = true;
    api.get<History>(`/history?days=${days}`).then((h) => { if (live) setData(h); }).catch(() => undefined);
    return () => { live = false; };
  }, [days, state?.last_refresh]);

  const needle = filter.trim().toLowerCase();
  const matches = (x: { campaign?: string; name?: string; game: string }) =>
    !needle || `${x.campaign ?? x.name ?? ""} ${x.game}`.toLowerCase().includes(needle);
  const groups = data ? groupByDay(data.claims.filter(matches)) : [];
  const missed = (data?.missed ?? []).filter(matches);
  const notable = (data?.missed ?? []).filter(isNotable).length;
  const campaigns = new Set(data?.claims.map((c) => c.campaign_id)).size;
  // "3 of 10 rewards in this campaign": every claim of the campaign in the period, not just this day's
  const claimedIn = new Map<string, number>();
  for (const c of data?.claims ?? []) claimedIn.set(c.campaign_id, (claimedIn.get(c.campaign_id) ?? 0) + c.rewards.length);
  const toggle = (key: string) => setOpen((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const art = artLookup(state);
  return (
    <section className="view" id="v-history" aria-labelledby="h-history">
      <div className="view-h">
        <div className="view-t"><h1 id="h-history" className="disp" tabIndex={-1}>History</h1>
          <p>What Dropwatch claimed, and what it missed and why.</p></div>
        <div className="seg" role="group" aria-label="Time period">
          {PERIODS.map(([d, l]) => <button key={d} type="button" aria-pressed={days === d} onClick={() => setDays(d)}>{l}</button>)}
        </div>
        <label className="filter"><input type="search" aria-label="Filter History" placeholder="Filter by game or campaign"
          value={filter} onChange={(e) => setFilter(e.target.value)} /></label>
      </div>
      {data && (data.total_rewards > 0 || (data.points?.points ?? 0) > 0) && <Stats data={data} label={PERIODS.find(([d]) => d === days)?.[2] ?? ""} days={days} />}
      {data && !data.total_rewards && !(data.points?.points ?? 0) && (
        <div className="hist-lead"><svg aria-hidden="true"><use href="#i-check" /></svg>
          <span>{data.total_rewards
            ? <><b>{data.total_rewards} {data.total_rewards === 1 ? "reward" : "rewards"}</b> claimed from {campaigns} {campaigns === 1 ? "campaign" : "campaigns"}.</>
            : <>Nothing claimed in this period yet.</>}
            {notable > 0 && <> <b>{notable} {notable === 1 ? "campaign" : "campaigns"}</b> missed.</>}</span></div>
      )}
      {groups.length > 0 && (
        <section aria-labelledby="h-claimed">
          <div className="sec-h"><h2 id="h-claimed">Claimed</h2></div>
          <div className="list">
            {groups.map((g) => [
              <div className="day" key={`d-${g.key}`}>{g.label}</div>,
              ...g.rows.map((r) => {
                const key = `${g.key}-${r.campaign_id}`;
                const isOpen = open.has(key);
                const saved = r.claims.find((c) => c.box_art_url)?.box_art_url;
                const a = saved ? boxArt(saved) : art.get(r.campaign_id) ?? art.get(`game:${r.game}`);
                const span = r.first.getTime() === r.last.getTime() ? TIME.format(r.first) : `${TIME.format(r.first)}–${TIME.format(r.last)}`;
                return (
                  <div className="hx-item" key={key}>
                    <button type="button" className="row hx" aria-expanded={isOpen} aria-controls={`hx-${key}`} onClick={() => toggle(key)}>
                      {a ? <img className="box" src={a} alt="" /> : <span className="box ph" aria-hidden="true" />}
                      <span className="hx-main">
                        <span className="row-t">{r.campaign}</span>
                        <span className="row-s">{r.game}<span className="sep">·</span>{r.rewards.length} {r.rewards.length === 1 ? "reward" : "rewards"}</span>
                        {!isOpen && <span className="row-art">{r.rewards.map((x, i) => <img key={i} src={x.image_url} alt={x.name} />)}</span>}
                      </span>
                      <span className="end"><span className="when">claimed {span}</span><Icon name="down" className="chev" /></span>
                    </button>
                    <div className="hx-body" id={`hx-${key}`} hidden={!isOpen}>
                      {isOpen && <Details claims={r.claims} claimed={claimedIn.get(r.campaign_id) ?? 0} />}
                    </div>
                  </div>
                );
              }),
            ])}
          </div>
        </section>
      )}
      {missed.length > 0 && <Missed missed={missed} />}
      {needle && data && !groups.length && !missed.length && <p className="hint">Nothing in this period matches "{filter.trim()}".</p>}
      {!data && <p className="lead"><Icon name="clock" /> Loading…</p>}
    </section>
  );
}

/** One open History row: the campaign's size and end, then each reward oldest first with the watch time its
 * drop needed and the channel it was mined on (approved mockup docs/design/history-detail-mockup.html). */
function Details({ claims, claimed }: { claims: Claim[]; claimed: number }) {
  const oldest = [...claims].sort((a, b) => +new Date(a.at) - +new Date(b.at));
  const total = claims.map((c) => c.campaign_rewards).find((n) => n != null);
  const ends = claims.map((c) => c.campaign_ends).find((e) => e != null);
  const sum: ReactNode[] = [];
  if (total) sum.push(<><b>{Math.min(claimed, total)} of {total}</b> rewards in this campaign</>);
  if (ends) {
    const running = new Date(ends) > new Date();
    const verb = sum.length ? (running ? "campaign ends" : "campaign ended") : (running ? "Campaign ends" : "Campaign ended");
    sum.push(running ? `${verb} ${day(ends)}, ${clock(ends)}` : `${verb} ${day(ends)}`);
  }
  const unrecorded = claims.some((c) => c.minutes == null && c.channel == null);
  return (
    <>
      {sum.length > 0 && (
        <div className="hx-sum">{sum.map((s, i) => <span key={i}>{i > 0 && <span className="sep">·</span>}{s}</span>)}</div>
      )}
      <ol className="hx-list">
        {oldest.flatMap((c) => c.rewards.map((x, i) => (
          <li key={`${c.at}-${i}`}>
            <img src={x.image_url} alt="" />
            <div><div className="n">{x.name}</div>
              {(c.minutes != null || c.channel) && (
                <div className="d">{c.minutes != null && `after ${dur(c.minutes)} watched`}
                  {c.minutes != null && c.channel && <span className="sep">·</span>}
                  {c.channel && <>on <span className="ch">{c.channel}</span></>}</div>
              )}</div>
            <span className="when">{TIME.format(new Date(c.at))}</span>
          </li>
        )))}
      </ol>
      {unrecorded && <div className="hx-old">Claimed before Dropwatch saved watch time and channel.</div>}
    </>
  );
}

/** For claims saved before box art was (2026-10-10): borrow it from campaigns the miner currently knows. */
function artLookup(state: State | null): Map<string, string> {
  const m = new Map<string, string>();
  if (!state) return m;
  const all = [state.current?.campaign, ...state.needs_you, ...state.up_next, ...state.done, ...(state.never ?? [])].filter(Boolean);
  for (const c of all) {
    if (!c?.box_art_url) continue;
    m.set(c.id, boxArt(c.box_art_url));
    m.set(`game:${c.game}`, boxArt(c.box_art_url));
  }
  return m;
}

type MissedRow = components["schemas"]["MissedOut"];

/** Worth a full row: something Dropwatch started, a Priority or pinned game, or an account to link. The
 * catalogue lists ~140 campaigns and most end unstarted, so those fold away with the Never ones. */
const isNotable = (m: MissedRow) =>
  m.reason !== "never_list" && (m.started || m.priority || m.pinned || m.reason === "not_linked");

const REASON: Record<string, { chip: string; tone: string; why: (m: MissedRow) => string }> = {
  not_linked: { chip: "Account not linked", tone: "red", why: (m) => m.minutes_watched > 0
    ? `Twitch counted ${dur(m.minutes_watched)} but won't give rewards until ${m.game} is linked.`
    : `${m.game} needs its account linked before Twitch gives rewards.` },
  ran_out_of_time: { chip: "Ran out of time", tone: "warn", why: () => "It was listed with less time left than its rewards need." },
  outranked: { chip: "Other campaigns came first", tone: "", why: (m) => m.priority
    ? "Other Priority games came first; move it up in Priority to mine it sooner."
    : `Not in Priority; add ${m.game} there, or pin it in Up next, to mine it sooner.` },
  no_live_channels: { chip: "No live channels", tone: "", why: () => "No channel with drops for it was live near the end." },
  priority_only: { chip: "Priority only was on", tone: "", why: (m) => `${m.game} isn't in Priority, so it wasn't mined. Add it to Priority to mine it next time.` },
  // no look in its last hour: off, paused, signed out or unable to reach Twitch (review fix 2026-10-10)
  dropwatch_off: { chip: "Dropwatch wasn't mining", tone: "", why: () => "Dropwatch was off, paused or signed out when it ended." },
};

const TONE: Record<string, string> = { red: "var(--alert)", warn: "var(--warn)", "": "var(--muted)" };

/** Watch time behind the claims: per campaign, its longest claimed drop (Twitch counts every drop's time from
 * the campaign's start, so adding them up would count the same watching twice). */
export function watchMinutes(claims: Claim[]): { minutes: number; partial: boolean } {
  const per = new Map<string, number | null>();
  for (const c of claims) {
    const m = c.minutes ?? null;
    const had = per.get(c.campaign_id);
    per.set(c.campaign_id, m === null ? had ?? null : Math.max(had ?? 0, m));
  }
  let minutes = 0;
  let partial = false;
  for (const m of per.values()) { if (m === null) partial = true; else minutes += m; }
  return { minutes, partial };
}

/** History stats for the chosen period (approved mockup docs/design/pre-docker-mockup.html, 2026-10-10). */
function Stats({ data, label, days }: { data: History; label: string; days: number }) {
  const notable = (data.missed ?? []).filter(isNotable).length;
  const campaigns = new Set(data.claims.map((c) => c.campaign_id)).size;
  const { minutes, partial } = watchMinutes(data.claims);
  const watched = `${minutes >= 60 ? `${Math.round(minutes / 60)}${NB}h` : `${minutes}${NB}min`}${partial ? "+" : ""}`;
  const byGame = new Map<string, number>();
  for (const c of data.claims) byGame.set(c.game, (byGame.get(c.game) ?? 0) + c.rewards.length);
  const games = [...byGame].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const byReason = new Map<string, number>();
  for (const m of (data.missed ?? []).filter(isNotable)) byReason.set(m.reason, (byReason.get(m.reason) ?? 0) + 1);
  const reasons = [...byReason].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const bars = (title: string, rows: [string, number][], fill: (key: string) => string | undefined, name: (key: string) => string) => {
    const top = Math.max(1, ...rows.map(([, n]) => n));
    return <>
      <div className="day" aria-hidden="true">{title}</div>
      <ul className="bars" aria-label={title}>
        {rows.map(([k, n]) => (
          <li className="sbar" key={k}><span className="name">{name(k)}</span>
            <span className="rail" aria-hidden="true"><span className="fill" style={{ width: `${(n / top) * 100}%`, background: fill(k) }} /></span>
            <span className="v">{n}</span></li>
        ))}
      </ul>
    </>;
  };
  return (
    <section aria-labelledby="h-stats">
      <div className="sec-h"><h2 id="h-stats">{label}</h2></div>
      <div className="stats">
        <div className="stat"><div className="n">{data.total_rewards}</div><div className="l">rewards claimed</div></div>
        <div className="stat"><div className="n">{campaigns}</div><div className="l">{campaigns === 1 ? "campaign" : "campaigns"}</div></div>
        <div className="stat"><div className="n">{watched}</div>
          <div className="l" title={partial ? "Claims from before 10 Oct didn't record their watch time" : undefined}>of watching behind them</div></div>
        <div className="stat"><div className="n">{(data.points?.points ?? 0).toLocaleString("en-US")}</div>
          <div className="l">channel points</div>
          {(data.points?.chests ?? 0) > 0 && <div className="l">{data.points!.chests} {data.points!.chests === 1 ? "chest" : "chests"} opened</div>}</div>
        {notable > 0 && <div className="stat"><div className="n warn">{notable}</div><div className="l">missed</div></div>}
      </div>
      {days > 1 && <RewardsPerDay claims={data.claims} days={Math.min(days, CHART_DAYS)} />}
      <div className="list stats-list">
        {bars("Rewards by game", games, () => undefined, (k) => k)}
        {reasons.length > 0 && bars("Missed, by reason", reasons, (k) => TONE[REASON[k]?.tone ?? ""],
          (k) => REASON[k]?.chip ?? k)}
      </div>
    </section>
  );
}

const CHART_DAYS = 14;

/** Rewards per viewer's day, oldest to newest (days with none included). The labels are visible and the whole
 * chart reads as one sentence to a screen reader; each bar's count is printed above it. */
export function RewardsPerDay({ claims, days }: { claims: Claim[]; days: number }) {
  const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  const counts = new Map<string, number>();
  for (const c of claims) { const k = dayKey(new Date(c.at)); counts.set(k, (counts.get(k) ?? 0) + c.rewards.length); }
  const fmt = new Intl.DateTimeFormat("en-GB", { weekday: "short" });
  const full = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
  const bars = Array.from({ length: days }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (days - 1 - i));
    return { key: dayKey(d), label: fmt.format(d), title: full.format(d).replace(",", ""), n: counts.get(dayKey(d)) ?? 0 };
  });
  const top = Math.max(1, ...bars.map((b) => b.n));
  return (
    <section className="perday" aria-labelledby="h-perday">
      <div className="perday-h"><h3 id="h-perday">Rewards per day</h3><span>{bars[0]!.title} – {bars.at(-1)!.title}</span></div>
      <div className="perday-bars" role="img" aria-label={`Rewards per day: ${bars.map((b) => `${b.title} ${b.n}`).join(", ")}`}>
        {bars.map((b, i) => (
          <div key={b.key} className={i === bars.length - 1 ? "newest" : undefined} title={`${b.title}: ${b.n}`}>
            <b>{b.n}</b><i style={{ height: `${(b.n / top) * 100}px` }} /><span>{days > 7 ? b.title.split(" ")[1] : b.label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** History's "Missed" (approved mockup docs/design/next-features-mockup.html, 2026-10-10). */
function Missed({ missed }: { missed: MissedRow[] }) {
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const rows = missed.filter(isNotable);
  const skipped = missed.filter((m) => m.reason === "never_list");
  const unstarted = missed.filter((m) => m.reason !== "never_list" && !isNotable(m));
  const dayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
  const byDay = new Map<string, MissedRow[]>();
  for (const m of rows) {
    const k = dayFmt.format(new Date(m.ends_at)).replace(",", "");
    byDay.set(k, [...(byDay.get(k) ?? []), m]);
  }
  const fold = (key: string, label: string, list: MissedRow[], note: (m: MissedRow) => string) => list.length > 0 && (
    <div key={key}>
      <button className="done-h" type="button" aria-expanded={openGroup === key} aria-controls={`miss-${key}`}
        onClick={() => setOpenGroup(openGroup === key ? null : key)}>
        <span className="done-sum"><span className="chip">{label} · {list.length}</span>
          <span className="hint">{list.slice(0, 3).map((m) => `${m.name} (${m.game})`).join(", ")}{list.length > 3 ? ", …" : ""}</span></span>
        <Icon name="down" className="chev" /></button>
      <div className="done-body" id={`miss-${key}`} hidden={openGroup !== key}>
        {list.map((m) => (
          <div className="row" key={m.campaign_id}>
            {m.box_art_url ? <img className="box" src={boxArt(m.box_art_url)} alt="" /> : <span className="box ph" aria-hidden="true" />}
            <div><div className="row-t">{m.name}</div><div className="row-s">{m.game}<span className="sep">·</span>{note(m)}</div></div>
            <span className="when">ended {TIME.format(new Date(m.ends_at))}</span>
          </div>
        ))}
      </div>
    </div>
  );
  return (
    <section aria-labelledby="h-missed">
      <div className="sec-h"><h2 id="h-missed">Missed</h2><span className="count">{rows.length}</span>
        <span className="aside">Ended with rewards left, and why</span></div>
      <div className="list">
        {[...byDay.entries()].map(([label, list]) => [
          <div className="day" key={`md-${label}`}>{label}</div>,
          ...list.map((m) => {
            const r = REASON[m.reason] ?? REASON.outranked!;
            const left = m.rewards.filter((x) => !x.claimed);
            return (
              <div className="row" key={m.campaign_id}>
                {m.box_art_url ? <img className="box" src={boxArt(m.box_art_url)} alt="" /> : <span className="box ph" aria-hidden="true" />}
                <div>
                  <div className="row-t">{m.name}</div>
                  <div className="row-s">{m.game}<span className="sep">·</span>{m.rewards_claimed} of {m.rewards_total} {m.rewards_total === 1 ? "reward" : "rewards"}<span className="sep">·</span>ended {TIME.format(new Date(m.ends_at))}</div>
                  {left.length > 0 && <div className="row-art gone">{left.slice(0, 6).map((x, i) => <img key={i} src={x.image_url} alt={x.name} />)}</div>}
                  <div className="why"><span className={`chip${r.tone ? ` ${r.tone}` : ""}`}>{r.chip}</span> {r.why(m)}</div>
                </div>
                {m.reason === "not_linked" && m.link_url
                  ? <a className="btn" href={m.link_url} target="_blank" rel="noreferrer">Link account</a>
                  : <span />}
              </div>
            );
          }),
        ])}
        {fold("skipped", "Skipped on purpose", skipped, () => "in Never")}
        {fold("unstarted", "Never started", unstarted, (m) => REASON[m.reason]?.chip.toLowerCase() ?? "not started")}
      </div>
    </section>
  );
}
