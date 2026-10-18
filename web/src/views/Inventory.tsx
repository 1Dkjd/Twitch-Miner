import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { components } from "../api/types";
import { useApp } from "../store";
import { NB, boxArt, day, dur } from "../ui/format";
import { Icon } from "../ui/Icons";

type Inventory = components["schemas"]["InventoryOut"];
type InvGame = components["schemas"]["InventoryGame"];
type InvCampaign = components["schemas"]["InventoryCampaign"];
type InvDrop = InvCampaign["drops"][number];

const STATUS: Record<string, [string, string]> = {
  mining: ["Mining now", "gold"], needs_link: ["Needs account link", "red"], active: ["Running", ""],
  upcoming: ["Coming up", ""], done: ["All claimed", "green"], never: ["Never mined", ""], ended: ["Ended", ""],
};

const FILTERS = [["all", "All"], ["open", "Still to earn"], ["claimed", "Claimed"]] as const;
type Filter = (typeof FILTERS)[number][0];

/** One reward's state, as on Twitch's inventory page. */
export function dropState(d: InvDrop, c: InvCampaign, now = Date.now()): "claimed" | "progress" | "locked" | "missed" {
  if (d.claimed) return "claimed";
  if (new Date(d.starts_at).getTime() > now || c.status === "upcoming") return "locked";
  if (new Date(d.ends_at).getTime() <= now) return "missed";
  return "progress";
}

/** Inventory (2026-10-18): every campaign Dropwatch can see, by game, with each reward and its progress.
 * Claims from campaigns Twitch no longer lists show under their game too. */
export function InventoryView() {
  const { state } = useApp();
  const [data, setData] = useState<Inventory | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [needle, setNeedle] = useState("");
  useEffect(() => {
    let live = true;
    api.get<Inventory>("/inventory").then((d) => { if (live) setData(d); }).catch(() => undefined);
    return () => { live = false; };
  }, [state?.last_refresh]);

  const q = needle.trim().toLowerCase();
  const games = (data?.games ?? [])
    .filter((g) => !q || g.game.toLowerCase().includes(q) || g.campaigns.some((c) => c.name.toLowerCase().includes(q)))
    .map((g) => ({ ...g, campaigns: g.campaigns.filter((c) => keep(c, filter)), claimed_earlier: filter === "open" ? [] : g.claimed_earlier }))
    .filter((g) => g.campaigns.length || g.claimed_earlier.length);
  return (
    <section className="view" id="v-inventory" aria-labelledby="h-inventory">
      <div className="view-h">
        <h1 id="h-inventory" className="disp" tabIndex={-1}>Inventory</h1>
        <div className="seg" role="group" aria-label="Show">
          {FILTERS.map(([k, label]) => (
            <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>
          ))}
        </div>
        <label className="filter"><input type="search" aria-label="Filter Inventory" placeholder="Filter by game or campaign"
          value={needle} onChange={(e) => setNeedle(e.target.value)} /></label>
      </div>
      {data && data.total_rewards > 0 && (
        <p className="inv-sum"><b>{data.claimed_rewards}</b> of {data.total_rewards} rewards claimed across {data.games.filter((g) => g.campaigns.length).length} games</p>
      )}
      {data && !games.length && <div className="list"><p className="empty">{data.games.length ? "Nothing matches." : "No campaigns yet. They show here once Dropwatch has checked Twitch."}</p></div>}
      {games.map((g) => <GameCard key={g.game} g={g} />)}
    </section>
  );
}

function keep(c: InvCampaign, f: Filter): boolean {
  if (f === "all") return true;
  const claimed = c.drops.some((d) => d.claimed);
  return f === "claimed" ? claimed : c.status !== "done" && c.status !== "ended" && c.drops.some((d) => !d.claimed);
}

function GameCard({ g }: { g: InvGame }) {
  const claimed = g.campaigns.reduce((n, c) => n + c.drops.filter((d) => d.claimed).reduce((k, d) => k + d.rewards.length, 0), 0);
  const total = g.campaigns.reduce((n, c) => n + c.drops.reduce((k, d) => k + d.rewards.length, 0), 0);
  return (
    <section className="inv-game" aria-labelledby={`inv-${slug(g.game)}`}>
      <div className="inv-head">
        {g.box_art_url ? <img className="box" src={boxArt(g.box_art_url)} alt="" /> : <span className="box ph" aria-hidden="true" />}
        <div>
          <h2 id={`inv-${slug(g.game)}`}>{g.game}</h2>
          <div className="row-s">
            {g.priority && <><span className="chip gold">Priority {g.priority}</span> </>}
            {g.never && <><span className="chip">Never</span> </>}
            {total > 0 && <>{claimed} of {total} claimed</>}
          </div>
        </div>
      </div>
      <div className="list">
        {g.campaigns.map((c) => <CampaignBlock key={c.id} c={c} />)}
        {g.claimed_earlier.length > 0 && (
          <div className="inv-camp">
            <div className="row-t">Claimed earlier</div>
            <div className="inv-grid">
              {g.claimed_earlier.flatMap((cl) => cl.rewards.map((r, i) => (
                <figure className="inv-item claimed" key={`${cl.campaign_id}-${cl.at}-${i}`} title={`${r.name} · ${cl.campaign} · ${day(cl.at)}`}>
                  <span className="inv-img">{r.image_url ? <img src={r.image_url} alt="" /> : null}</span>
                  <figcaption><span className="inv-n">{r.name}</span><span className="inv-m">{day(cl.at)}</span></figcaption>
                </figure>
              )))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function CampaignBlock({ c }: { c: InvCampaign }) {
  const [label, tone] = STATUS[c.status] ?? [c.status, ""];
  const drops = [...c.drops].sort((a, b) => a.required_minutes - b.required_minutes);
  return (
    <div className="inv-camp">
      <div className="inv-camp-h">
        <div>
          <div className="row-t">{c.name}</div>
          <div className="row-s">
            {c.status === "upcoming" && c.starts_at ? <>starts {day(c.starts_at)}<span className="sep">·</span></> : null}
            {c.status === "ended" ? "ended" : "ends"} {day(c.ends_at)}
            {c.allowed_channels.length === 1 && <><span className="sep">·</span>only on <b>{c.allowed_channels[0]}</b></>}
          </div>
        </div>
        <div className="inv-acts">
          <span className={`chip${tone ? ` ${tone}` : ""}`}>{label}</span>
          {c.link_url && c.linked !== true && (c.status === "needs_link" || c.status === "upcoming") && (
            <a className="btn" href={c.link_url} target="_blank" rel="noopener noreferrer" aria-label={`Link your ${c.game} account (opens the game's site)`}>
              <Icon name="link" />Link<Icon name="ext" /></a>
          )}
        </div>
      </div>
      <div className="inv-grid">
        {drops.flatMap((d) => d.rewards.map((r, i) => {
          const st = dropState(d, c);
          const pct = Math.min(100, Math.round((d.current_minutes / Math.max(1, d.required_minutes)) * 100));
          return (
            <figure className={`inv-item ${st}`} key={`${d.id}-${i}`} title={r.name}>
              <span className="inv-img">{r.image_url ? <img src={r.image_url} alt="" /> : null}</span>
              <figcaption>
                <span className="inv-n">{r.name}</span>
                <span className="inv-m">
                  {st === "claimed" ? "Claimed" : st === "locked" ? `${dur(d.required_minutes)} watch` : st === "missed" ? "Missed"
                    : `${dur(d.current_minutes)}${NB}/${NB}${dur(d.required_minutes)}`}
                </span>
                {st === "progress" && <span className="inv-bar" role="progressbar" aria-label={`${r.name} progress`} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${pct}%` }} /></span>}
              </figcaption>
            </figure>
          );
        }))}
      </div>
    </div>
  );
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-");
