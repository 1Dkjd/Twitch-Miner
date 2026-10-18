import { useEffect, useRef, useState } from "react";
import { api, type Lists } from "../api/client";
import type { components } from "../api/types";
import { useLists } from "../lists";
import { useApp } from "../store";
import { NB, boxArt, clock, day, dur } from "../ui/format";
import { Icon } from "../ui/Icons";
import { LinkedButton } from "./LinkedButton";

type Inventory = components["schemas"]["InventoryOut"];
type InvGame = components["schemas"]["InventoryGame"];
type InvCampaign = components["schemas"]["InventoryCampaign"];
type InvDrop = InvCampaign["drops"][number];
type InvReward = InvDrop["rewards"][number];
type Detail = { c: InvCampaign; d: InvDrop; r: InvReward };

const STATUS: Record<string, [string, string]> = {
  mining: ["Mining now", "gold"], needs_link: ["Needs account link", "red"], active: ["Running", ""],
  upcoming: ["Coming up", ""], done: ["All claimed", "green"], never: ["Never mined", ""], ended: ["Ended", ""],
};
const VERDICT: Record<string, [string, string]> = { wont_finish: ["Won't finish in time", "red"], tight: ["Tight on time", "gold"] };

// tile size slider (2026-10-18): this browser's choice, kept in localStorage; a blocked storage just forgets
const SIZE_KEY = "dropwatch.inventory.tile", SIZE_MIN = 72, SIZE_MAX = 200, SIZE_DEFAULT = 112;
function savedSize(): number {
  try {
    const n = Number(localStorage.getItem(SIZE_KEY));
    return n >= SIZE_MIN && n <= SIZE_MAX ? n : SIZE_DEFAULT;
  } catch { return SIZE_DEFAULT; }
}

const FILTERS = [["all", "All"], ["open", "Still to earn"], ["claimed", "Claimed"]] as const;
const FILTER_HINT: Record<string, string> = {
  open: "Only what Dropwatch will mine: not Never games, not rewards that need a sub, and with Priority only on, just Priority games.",
};
type Filter = (typeof FILTERS)[number][0];
const SORTS = [["game", "By game"], ["ending", "Ending soonest"]] as const;
type Sort = (typeof SORTS)[number][0];

/** One reward's state, as on Twitch's inventory page. "late" is in progress but can't reach its minutes before
 * its window closes, even watched non-stop from now. */
export function dropState(d: InvDrop, c: InvCampaign, now = Date.now()): "claimed" | "progress" | "late" | "locked" | "missed" {
  if (d.claimed) return "claimed";
  if (new Date(d.starts_at).getTime() > now || c.status === "upcoming") return "locked";
  const end = new Date(d.ends_at).getTime();
  if (end <= now) return "missed";
  const left = d.required_minutes - d.current_minutes;
  if (d.required_minutes > 0 && !d.required_subs && left > (end - now) / 60_000) return "late";
  return "progress";
}

const fullyClaimed = (c: InvCampaign) => c.drops.length > 0 && c.drops.every((d) => d.claimed);

/** Inventory (2026-10-18): every campaign Dropwatch can see, by game, with each reward and its progress.
 * Claims from campaigns Twitch no longer lists show under their game too. Games can be triaged here
 * (Prioritise, Never, Mine now) without going to Priorities. */
export function InventoryView() {
  const { state, say, sayError, refreshState } = useApp();
  const { lists, save } = useLists();
  const [data, setData] = useState<Inventory | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("game");
  const [needle, setNeedle] = useState("");
  const [showNever, setShowNever] = useState(false);
  const [showBadges, setShowBadges] = useState(false);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [size, setSize] = useState(savedSize);
  const resize = (n: number) => { setSize(n); try { localStorage.setItem(SIZE_KEY, String(n)); } catch { /* storage blocked */ } };
  const reload = () => api.get<Inventory>("/inventory").then(setData).catch(() => undefined);
  useEffect(() => {
    let live = true;
    api.get<Inventory>("/inventory").then((d) => { if (live) setData(d); }).catch(() => undefined);
    return () => { live = false; };
  }, [state?.last_refresh]);

  async function change(next: (l: Lists) => Lists, done: string) {
    if (!lists) return;
    const err = await save(next(lists));
    if (err) { say({ title: "Couldn't save", detail: err, tone: "bad" }); return; }
    say(done);
    void reload();
  }
  const acts: GameActs = {
    prioritise: (g) => change((l) => ({ ...l, never: l.never.filter((x) => x !== g), priority: [...l.priority.filter((x) => x !== g), g] }), `${g} added to Priority`),
    unprioritise: (g) => change((l) => ({ ...l, priority: l.priority.filter((x) => x !== g) }), `${g} removed from Priority`),
    never: (g) => change((l) => ({ ...l, priority: l.priority.filter((x) => x !== g), never: [...l.never.filter((x) => x !== g), g] }), `${g} won't be mined`),
    allow: (g) => change((l) => ({ ...l, never: l.never.filter((x) => x !== g) }), `${g} can be mined again`),
    mineNow: async (c) => {
      try { await api.post("/mine-now", { campaign_id: c.id }); say(`Mining ${c.name}`); }
      catch (e) { sayError(e, "Couldn't start it"); }
      void refreshState(); void reload();
    },
  };

  const q = needle.trim().toLowerCase();
  // badge and emote campaigns aren't mined unless that setting is on, so they're hidden to match (2026-10-18)
  const badgesHidden = !!data && !data.mine_badges && !showBadges;
  const visible = (data?.games ?? [])
    .map((g) => (badgesHidden ? { ...g, campaigns: g.campaigns.filter((c) => !c.badge) } : g))
    .filter((g) => g.campaigns.length || g.claimed_earlier.length);
  const badgeCount = (data?.games ?? []).reduce((n, g) => n + g.campaigns.filter((c) => c.badge).length, 0);
  const counted = visible.filter((g) => showNever || !g.never);
  const rewardsIn = (g: InvGame, claimedOnly: boolean) =>
    g.campaigns.reduce((n, c) => n + c.drops.filter((d) => !claimedOnly || d.claimed).reduce((k, d) => k + d.rewards.length, 0), 0);
  const sum = { total: counted.reduce((n, g) => n + rewardsIn(g, false), 0), claimed: counted.reduce((n, g) => n + rewardsIn(g, true), 0),
    games: counted.filter((g) => g.campaigns.length).length };
  const neverCount = (data?.games ?? []).filter((g) => g.never).length;
  const games = visible
    .filter((g) => showNever || !g.never)
    .filter((g) => !q || g.game.toLowerCase().includes(q) || g.campaigns.some((c) => c.name.toLowerCase().includes(q)))
    .map((g) => ({ ...g, campaigns: g.campaigns.filter((c) => keep(c, filter)), claimed_earlier: filter === "open" ? [] : g.claimed_earlier }))
    .filter((g) => g.campaigns.length || g.claimed_earlier.length)
    .sort((a, b) => gameRank(a) - gameRank(b) || (a.priority ?? 0) - (b.priority ?? 0) || a.game.localeCompare(b.game));
  // Ending soonest: every campaign still open, one flat list by end time (claimed-out and ended ones last)
  const flat = games.flatMap((g) => g.campaigns.map((c) => ({ c, g })))
    .sort((a, b) => Number(closed(a.c)) - Number(closed(b.c)) || +new Date(a.c.ends_at) - +new Date(b.c.ends_at));
  return (
    <section className="view" id="v-inventory" aria-labelledby="h-inventory" style={{ "--inv-tile": `${size}px` } as React.CSSProperties}>
      <div className="view-h">
        <h1 id="h-inventory" className="disp" tabIndex={-1}>Inventory</h1>
        <div className="seg" role="group" aria-label="Show">
          {FILTERS.map(([k, label]) => (
            <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>
          ))}
        </div>
        <div className="seg" role="group" aria-label="Sort">
          {SORTS.map(([k, label]) => (
            <button key={k} type="button" aria-pressed={sort === k} onClick={() => setSort(k)}>{label}</button>
          ))}
        </div>
        <label className="inv-size" title="Reward size">
          <span aria-hidden="true" className="inv-size-s">▪</span>
          <input type="range" min={SIZE_MIN} max={SIZE_MAX} step={4} value={size} aria-label="Reward size"
            onChange={(e) => resize(Number(e.target.value))} />
          <span aria-hidden="true" className="inv-size-l">■</span>
        </label>
        <label className="filter"><input type="search" aria-label="Filter Inventory" placeholder="Filter by game or campaign"
          value={needle} onChange={(e) => setNeedle(e.target.value)} /></label>
      </div>
      {FILTER_HINT[filter] && <p className="inv-sum">{FILTER_HINT[filter]}</p>}
      {sum.total > 0 && (
        <p className="inv-sum"><b>{sum.claimed}</b> of {sum.total} rewards claimed across {sum.games} {sum.games === 1 ? "game" : "games"}</p>
      )}
      {data && !games.length && <div className="list"><p className="empty">{data.games.length ? "Nothing matches." : "No campaigns yet. They show here once Dropwatch has checked Twitch."}</p></div>}
      {sort === "game"
        ? games.map((g) => <GameCard key={g.game} g={g} acts={acts} onDetail={setDetail} />)
        : flat.length > 0 && (
          <div className="list">
            {flat.map(({ c, g }) => <CampaignBlock key={c.id} c={c} game={g} acts={acts} onDetail={setDetail} />)}
          </div>
        )}
      {data && !data.mine_badges && badgeCount > 0 && (
        <button className="btn quiet inv-never" type="button" aria-pressed={showBadges} onClick={() => setShowBadges(!showBadges)}>
          {showBadges ? "Hide badge and emote campaigns" : `Show badge and emote campaigns (${badgeCount})`}
        </button>
      )}
      {neverCount > 0 && (
        <button className="btn quiet inv-never" type="button" aria-pressed={showNever} onClick={() => setShowNever(!showNever)}>
          {showNever ? "Hide Never games" : `Show Never games (${neverCount})`}
        </button>
      )}
      {detail && <RewardDetail {...detail} onClose={() => setDetail(null)} />}
    </section>
  );
}

type GameActs = {
  prioritise: (g: string) => void; unprioritise: (g: string) => void; never: (g: string) => void; allow: (g: string) => void;
  mineNow: (c: InvCampaign) => void;
};

const closed = (c: InvCampaign) => c.status === "ended" || c.status === "done" || fullyClaimed(c);

/** Priority games first, then what needs attention or is earning: the long tail of untouched games last. */
function gameRank(g: InvGame): number {
  if (g.priority) return 0;
  if (g.never) return 6;
  const st = new Set(g.campaigns.map((c) => c.status));
  if (st.has("mining")) return 1;
  if (st.has("needs_link")) return 2;
  if (g.campaigns.some((c) => c.status === "active" && c.drops.some((d) => d.current_minutes > 0 && !d.claimed))) return 3;
  if (st.has("active") || st.has("upcoming")) return 4;
  return 5;
}

function keep(c: InvCampaign, f: Filter): boolean {
  if (f === "all") return true;
  const claimed = c.drops.some((d) => d.claimed);
  // Still to earn: only what the miner will actually mine (or will once linked or started)
  return f === "claimed" ? claimed : !!c.will_mine && c.drops.some((d) => !d.claimed && !(d.required_subs ?? 0));
}

function GameCard({ g, acts, onDetail }: { g: InvGame; acts: GameActs; onDetail: (d: Detail) => void }) {
  const [earlierOpen, setEarlierOpen] = useState(false);
  const claimed = g.campaigns.reduce((n, c) => n + c.drops.filter((d) => d.claimed).reduce((k, d) => k + d.rewards.length, 0), 0);
  const total = g.campaigns.reduce((n, c) => n + c.drops.reduce((k, d) => k + d.rewards.length, 0), 0);
  const earlier = g.claimed_earlier.flatMap((cl) => cl.rewards.map((r) => ({ r, cl })));
  return (
    <section className="inv-game" aria-labelledby={`inv-${slug(g.game)}`}>
      <div className="inv-head">
        {g.box_art_url ? <img className="box" src={boxArt(g.box_art_url)} alt="" /> : <span className="box ph" aria-hidden="true" />}
        <div className="inv-head-t">
          <h2 id={`inv-${slug(g.game)}`}>{g.game}</h2>
          <div className="row-s">
            {g.priority && <><span className="chip gold">Priority {g.priority}</span> </>}
            {g.never && <><span className="chip">Never</span> </>}
            {total > 0 && <>{claimed} of {total} claimed</>}
          </div>
        </div>
        <div className="inv-game-acts">
          {g.priority
            ? <button className="btn quiet" type="button" aria-label={`Remove ${g.game} from Priority`} onClick={() => acts.unprioritise(g.game)}>Unprioritise</button>
            : <button className="btn quiet" type="button" aria-label={`Move ${g.game} to Priority`} onClick={() => acts.prioritise(g.game)}>Prioritise</button>}
          {g.never
            ? <button className="btn quiet" type="button" aria-label={`Allow ${g.game} again`} onClick={() => acts.allow(g.game)}>Allow again</button>
            : <button className="btn quiet" type="button" aria-label={`Never mine ${g.game}`} onClick={() => acts.never(g.game)}>Never</button>}
        </div>
      </div>
      <div className="list">
        {g.campaigns.map((c) => <CampaignBlock key={c.id} c={c} acts={acts} onDetail={onDetail} />)}
        {earlier.length > 0 && (
          <div className="inv-camp">
            <button className="inv-fold" type="button" aria-expanded={earlierOpen} onClick={() => setEarlierOpen(!earlierOpen)}>
              <span className="row-t">Claimed earlier</span>
              <span className="chip green">{earlier.length} {earlier.length === 1 ? "reward" : "rewards"}</span>
              <span className="inv-fold-art" aria-hidden="true">{earlier.slice(0, 8).map(({ r }, i) => r.image_url ? <img key={i} src={r.image_url} alt="" /> : null)}</span>
              <Icon name="down" className="chev" />
            </button>
            {earlierOpen && (
              <div className="inv-grid">
                {earlier.map(({ r, cl }, i) => (
                  <figure className="inv-item claimed" key={`${cl.campaign_id}-${cl.at}-${i}`} title={`${r.name} · ${cl.campaign} · ${day(cl.at)}`}>
                    <span className="inv-img">{r.image_url ? <img src={r.image_url} alt="" /> : null}</span>
                    <figcaption><span className="inv-n">{r.name}</span><span className="inv-m">{day(cl.at)}</span></figcaption>
                  </figure>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function CampaignBlock({ c, game, acts, onDetail }: { c: InvCampaign; game?: InvGame; acts: GameActs; onDetail: (d: Detail) => void }) {
  const done = fullyClaimed(c);
  const [open, setOpen] = useState(!done);
  const [label, tone] = STATUS[c.status] ?? [c.status, ""];
  const verdict = c.status !== "upcoming" && !done ? VERDICT[c.verdict ?? ""] : undefined;
  const drops = [...c.drops].sort((a, b) => a.required_minutes - b.required_minutes);
  const rewards = drops.flatMap((d) => d.rewards.map((r) => ({ d, r })));
  const canMine = !!c.will_mine && (c.status === "active" || c.status === "needs_link");
  const title = <>{game && <span className="inv-camp-game">{game.game}<span className="sep">·</span></span>}{c.name}</>;
  if (done && !open) {
    // fully claimed: one line, like Done on Overview
    return (
      <div className="inv-camp">
        <button className="inv-fold" type="button" aria-expanded={false} aria-label={`Show ${c.name}, all ${rewards.length} claimed`} onClick={() => setOpen(true)}>
          {game?.box_art_url ? <img className="inv-fold-box" src={boxArt(game.box_art_url)} alt="" /> : null}
          <span className="row-t">{title}</span>
          <span className="chip green">All {rewards.length} claimed</span>
          <span className="inv-fold-art" aria-hidden="true">{rewards.slice(0, 8).map(({ r }, i) => r.image_url ? <img key={i} src={r.image_url} alt="" /> : null)}</span>
          <Icon name="down" className="chev" />
        </button>
      </div>
    );
  }
  return (
    <div className="inv-camp">
      <div className="inv-camp-h">
        <div className="inv-camp-t">
          {game?.box_art_url ? <img className="inv-fold-box" src={boxArt(game.box_art_url)} alt="" /> : null}
          <div>
            <div className="row-t">{title}</div>
            <div className="row-s">
              {c.status === "upcoming" && c.starts_at ? <>starts {day(c.starts_at)}<span className="sep">·</span></> : null}
              {c.status === "ended" ? "ended" : "ends"} {day(c.ends_at)}
              {c.allowed_channels.length === 1 && <><span className="sep">·</span>only on <b>{c.allowed_channels[0]}</b></>}
            </div>
          </div>
        </div>
        <div className="inv-acts">
          {verdict && <span className={`chip ${verdict[1]}`}>{verdict[0]}</span>}
          <span className={`chip${tone ? ` ${tone}` : ""}`}>{label}</span>
          {c.link_url && c.linked !== true && (c.status === "needs_link" || c.status === "upcoming") && (
            <a className="btn" href={c.link_url} target="_blank" rel="noopener noreferrer" aria-label={`Link your ${c.game} account (opens the game's site)`}>
              <Icon name="link" />Link<Icon name="ext" /></a>
          )}
          {c.link_url && c.linked !== true && (c.status === "needs_link" || c.status === "upcoming") && <LinkedButton game={c.game} compact />}
          {canMine && <button className="btn" type="button" aria-label={`Mine ${c.name} now`} onClick={() => acts.mineNow(c)}>Mine now</button>}
          {done && <button className="btn quiet" type="button" aria-label={`Fold ${c.name}`} onClick={() => setOpen(false)}>Fold</button>}
        </div>
      </div>
      <div className="inv-grid">
        {rewards.map(({ d, r }, i) => {
          const st = dropState(d, c);
          const pct = Math.min(100, Math.round((d.current_minutes / Math.max(1, d.required_minutes)) * 100));
          return (
            <button type="button" className={`inv-item ${st}`} key={`${d.id}-${i}`} title={r.name}
              aria-label={`${r.name}: details`} onClick={() => onDetail({ c, d, r })}>
              <span className="inv-img">{r.image_url ? <img src={r.image_url} alt="" /> : null}</span>
              <span className="inv-cap">
                <span className="inv-n">{r.name}</span>
                <span className="inv-m">{rewardLine(d, st)}</span>
                {(st === "progress" || st === "late") && d.required_minutes > 0 && !d.required_subs && (
                  <span className="inv-bar" role="progressbar" aria-label={`${r.name} progress`} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                    <span style={{ width: `${pct}%` }} /></span>
                )}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function rewardLine(d: InvDrop, st: ReturnType<typeof dropState>): string {
  if (st === "claimed") return "Claimed";
  if (st === "missed") return "Missed";
  if ((d.required_subs ?? 0) > 0) return `Needs ${d.required_subs === 1 ? "a sub" : `${d.required_subs} subs`}`;
  if (d.required_minutes <= 0) return "No watch time";
  if (st === "locked") return `${dur(d.required_minutes)} watch`;
  if (st === "late") return "Won't finish in time";
  return `${dur(d.current_minutes)}${NB}/${NB}${dur(d.required_minutes)}`;
}

const when = (d: string) => `${day(d)} ${clock(d)}`;

/** A reward's details: its window, what it takes, which channels count and what has to come first. */
function RewardDetail({ c, d, r, onClose }: Detail & { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("keydown", esc); prev?.focus?.(); };
  }, [onClose]);
  const st = dropState(d, c);
  const left = Math.max(0, d.required_minutes - d.current_minutes);
  return (
    <div className="inv-dlg-back" onClick={onClose}>
      <div className="inv-dlg" role="dialog" aria-modal="true" aria-labelledby="inv-dlg-h" tabIndex={-1} ref={ref} onClick={(e) => e.stopPropagation()}>
        <div className="inv-dlg-top">
          <span className="inv-img">{r.image_url ? <img src={r.image_url} alt="" /> : null}</span>
          <div>
            <h2 id="inv-dlg-h">{r.name}</h2>
            <div className="row-s">{c.game}<span className="sep">·</span>{c.name}</div>
            <div className="inv-dlg-state"><span className={`chip ${st === "claimed" ? "green" : st === "late" || st === "missed" ? "red" : ""}`}>{rewardLine(d, st)}</span></div>
          </div>
          <button className="btn quiet inv-dlg-x" type="button" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <dl className="inv-dl">
          <dt>Window</dt><dd>{when(d.starts_at)} – {when(d.ends_at)}</dd>
          <dt>Takes</dt>
          <dd>
            {(d.required_subs ?? 0) > 0 ? `${d.required_subs === 1 ? "A sub" : `${d.required_subs} subs`} (gifted or bought)` : null}
            {(d.required_subs ?? 0) > 0 && d.required_minutes > 0 ? " and " : null}
            {d.required_minutes > 0 ? `${dur(d.required_minutes)} of watching` : (d.required_subs ?? 0) > 0 ? null : "Nothing to watch"}
            {d.required_minutes > 0 && !d.claimed && <> · {dur(d.current_minutes)} done, {dur(left)} to go</>}
          </dd>
          {d.requires.length > 0 && <><dt>Earn first</dt><dd>{d.requires.join(", ")}</dd></>}
          <dt>Channels</dt>
          <dd>{c.allowed_channels.length ? c.allowed_channels.slice(0, 12).join(", ") + (c.allowed_channels.length > 12 ? ` and ${c.allowed_channels.length - 12} more` : "")
            : `Any ${c.game} stream with drops on`}</dd>
          <dt>Account</dt>
          <dd>{c.linked === true ? "Linked" : c.linked === false ? "Not linked" : "Unknown until the campaign starts"}
            {c.link_url && c.linked !== true && <> · <a href={c.link_url} target="_blank" rel="noopener noreferrer">Link account<Icon name="ext" /></a></>}</dd>
        </dl>
      </div>
    </div>
  );
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-");
