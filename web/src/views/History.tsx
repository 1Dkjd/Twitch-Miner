import { useEffect, useState } from "react";
import { api, type Claim, type History, type State } from "../api/client";
import { useApp } from "../store";
import { boxArt } from "../ui/format";
import { Icon } from "../ui/Icons";

export interface DayGroup {
  key: string;
  label: string;
  rows: { campaign_id: string; campaign: string; game: string; first: Date; last: Date; rewards: Claim["rewards"] }[];
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
    if (!row) { row = { campaign_id: c.campaign_id, campaign: c.campaign, game: c.game, first: at, last: at, rewards: [] }; g.rows.push(row); }
    row.rewards.push(...c.rewards);
    if (at < row.first) row.first = at;
    if (at > row.last) row.last = at;
  }
  return [...days.values()];
}

const PERIODS: [number, string][] = [[30, "Last 30 days"], [90, "Last 90 days"], [365, "Last year"]];
const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });

export function HistoryView() {
  const { state } = useApp();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<History | null>(null);
  useEffect(() => {
    let live = true;
    api.get<History>(`/history?days=${days}`).then((h) => { if (live) setData(h); }).catch(() => undefined);
    return () => { live = false; };
  }, [days, state?.last_refresh]);

  const groups = data ? groupByDay(data.claims) : [];
  const campaigns = new Set(data?.claims.map((c) => c.campaign_id)).size;
  const art = artLookup(state);
  return (
    <section className="view" id="v-history" aria-labelledby="h-history">
      <div className="view-h">
        <h1 id="h-history" className="disp" tabIndex={-1}>History</h1>
        <select className="period" aria-label="Time period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {PERIODS.map(([d, l]) => <option key={d} value={d}>{l}</option>)}
        </select>
      </div>
      {data && (
        <div className="hist-lead"><svg aria-hidden="true"><use href="#i-check" /></svg>
          <span>{data.total_rewards
            ? <><b>{data.total_rewards} {data.total_rewards === 1 ? "reward" : "rewards"}</b> claimed from {campaigns} {campaigns === 1 ? "campaign" : "campaigns"}.</>
            : <>Nothing claimed in this period yet.</>}</span></div>
      )}
      {groups.length > 0 && (
        <section aria-labelledby="h-claimed">
          <div className="sec-h"><h2 id="h-claimed">Claimed</h2></div>
          <div className="list">
            {groups.map((g) => [
              <div className="day" key={`d-${g.key}`}>{g.label}</div>,
              ...g.rows.map((r) => {
                const a = art.get(r.campaign_id) ?? art.get(`game:${r.game}`);
                const span = r.first.getTime() === r.last.getTime() ? TIME.format(r.first) : `${TIME.format(r.first)}–${TIME.format(r.last)}`;
                return (
                  <div className="row" key={`${g.key}-${r.campaign_id}`}>
                    {a ? <img className="box" src={a} alt="" /> : <span className="box ph" aria-hidden="true" />}
                    <div>
                      <div className="row-t">{r.campaign}</div>
                      <div className="row-s">{r.game}<span className="sep">·</span>{r.rewards.length} {r.rewards.length === 1 ? "reward" : "rewards"}</div>
                      <div className="row-art">{r.rewards.map((x, i) => <img key={i} src={x.image_url} alt={x.name} />)}</div>
                      <div className="names" aria-hidden="true">{r.rewards.map((x) => x.name).join(", ")}</div>
                    </div>
                    <span className="when">claimed {span}</span>
                  </div>
                );
              }),
            ])}
          </div>
        </section>
      )}
      {!data && <p className="lead"><Icon name="clock" /> Loading…</p>}
    </section>
  );
}

/** Claims don't carry box art; borrow it from campaigns the miner currently knows. */
function artLookup(state: State | null): Map<string, string> {
  const m = new Map<string, string>();
  if (!state) return m;
  const all = [state.current?.campaign, ...state.needs_you, ...state.up_next, ...state.done].filter(Boolean);
  for (const c of all) {
    if (!c?.box_art_url) continue;
    m.set(c.id, boxArt(c.box_art_url));
    m.set(`game:${c.game}`, boxArt(c.box_art_url));
  }
  return m;
}
