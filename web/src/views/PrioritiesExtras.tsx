import { useEffect, useState } from "react";
import { api, type Lists } from "../api/client";
import type { components } from "../api/types";
import { useApp } from "../store";
import { boxArt } from "../ui/format";
import { Icon } from "../ui/Icons";

type Inventory = components["schemas"]["InventoryOut"];
type InvGame = components["schemas"]["InventoryGame"];

/** Games with a campaign running or announced, from the Inventory endpoint; re-read after each miner refresh. */
export function useCampaignGames(): InvGame[] | null {
  const { state } = useApp();
  const [games, setGames] = useState<InvGame[] | null>(null);
  useEffect(() => {
    let live = true;
    api.get<Inventory>("/inventory")
      .then((d) => { if (live) setGames(d.games.filter((g) => g.campaigns.some((c) => c.status !== "ended"))); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [state?.last_refresh]);
  return games;
}

/** Every campaign of the game is badge/emote only (never mined while that setting is off). */
export const badgeOnly = (g: InvGame) => g.campaigns.length > 0 && g.campaigns.every((c) => c.badge);

/** Bulk Never (2026-10-18): tick several games with a campaign and move them to Never at once, with a shortcut
 * that ticks every game whose campaigns only give badges or emotes. */
export function BulkNever({ lists, games, onCommit }: {
  lists: Lists; games: InvGame[] | null; onCommit: (next: Lists, message: string) => Promise<void> | void;
}) {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [needle, setNeedle] = useState("");
  const pool = (games ?? []).filter((g) => !lists.never.includes(g.game)).sort((a, b) => a.game.localeCompare(b.game));
  const shown = pool.filter((g) => !needle.trim() || g.game.toLowerCase().includes(needle.trim().toLowerCase()));
  const badgeGames = pool.filter(badgeOnly).map((g) => g.game);
  const toggle = (g: string) => setPicked((s) => { const n = new Set(s); if (n.has(g)) n.delete(g); else n.add(g); return n; });
  if (!open) {
    return (
      <div className="bulk-open">
        <button className="btn quiet" type="button" onClick={() => setOpen(true)} disabled={!pool.length}>Add several games…</button>
      </div>
    );
  }
  async function apply() {
    const names = [...picked];
    if (!names.length) return;
    await onCommit({ ...lists, priority: lists.priority.filter((g) => !picked.has(g)), never: [...lists.never, ...names] },
      `${names.length} ${names.length === 1 ? "game" : "games"} moved to Never`);
    setPicked(new Set());
    setOpen(false);
  }
  return (
    <div className="bulk" role="group" aria-label="Add several games to Never">
      <div className="bulk-h">
        <label className="filter"><input type="search" aria-label="Filter games" placeholder="Filter games"
          value={needle} onChange={(e) => setNeedle(e.target.value)} /></label>
        {badgeGames.length > 0 && (
          <button className="btn quiet" type="button" onClick={() => setPicked((s) => new Set([...s, ...badgeGames]))}>
            Tick badge/emote-only games ({badgeGames.length})</button>
        )}
        {picked.size > 0 && <button className="btn quiet" type="button" onClick={() => setPicked(new Set())}>Clear</button>}
      </div>
      <ul className="bulk-list">
        {shown.map((g) => (
          <li key={g.game}>
            <label>
              <input type="checkbox" checked={picked.has(g.game)} onChange={() => toggle(g.game)} />
              {g.box_art_url ? <img className="bulk-box" src={boxArt(g.box_art_url)} alt="" /> : <span className="bulk-box ph" aria-hidden="true" />}
              <span className="bulk-n">{g.game}</span>
              {g.priority && <span className="chip gold">Priority {g.priority}</span>}
              {badgeOnly(g) && <span className="chip">Badges/emotes only</span>}
            </label>
          </li>
        ))}
        {!shown.length && <li className="empty">No games match.</li>}
      </ul>
      <div className="bulk-f">
        <button className="btn strong" type="button" disabled={!picked.size} onClick={() => void apply()}>
          Never mine {picked.size || ""} {picked.size === 1 ? "game" : "games"}</button>
        <button className="btn quiet" type="button" onClick={() => { setOpen(false); setPicked(new Set()); }}>Cancel</button>
      </div>
    </div>
  );
}

type LinkState = "needs" | "unknown" | "linked";
const LINK_LABEL: Record<LinkState, [string, string]> = {
  needs: ["Needs linking", "red"], unknown: ["Unknown until it starts", ""], linked: ["Linked", "green"],
};

/** A game's account link status across its running and announced campaigns. Badge/emote campaigns need no link. */
export function linkState(g: InvGame): { state: LinkState; url: string } | null {
  const cs = g.campaigns.filter((c) => c.status !== "ended" && !c.badge && c.link_url);
  if (!cs.length) return null;
  const url = cs.find((c) => c.linked !== true)?.link_url ?? cs[0]!.link_url;
  if (cs.some((c) => c.linked === true)) return { state: "linked", url };
  if (cs.some((c) => c.linked === false)) return { state: "needs", url };
  return { state: "unknown", url };
}

/** Linked accounts (2026-10-18): every game with a campaign that needs a game account, its status and a link. */
export function LinkedAccounts({ games, never }: { games: InvGame[] | null; never: string[] }) {
  const [showLinked, setShowLinked] = useState(false);
  const rows = (games ?? [])
    .filter((g) => !never.includes(g.game))
    .map((g) => ({ g, l: linkState(g) }))
    .filter((x): x is { g: InvGame; l: NonNullable<ReturnType<typeof linkState>> } => x.l !== null)
    .sort((a, b) => ORDER[a.l.state] - ORDER[b.l.state] || (a.g.priority ?? 999) - (b.g.priority ?? 999) || a.g.game.localeCompare(b.g.game));
  const linked = rows.filter((r) => r.l.state === "linked").length;
  const shown = showLinked ? rows : rows.filter((r) => r.l.state !== "linked");
  return (
    <div className="bucket" id="linked-accounts">
      <div className="bucket-h"><h2>Linked accounts</h2><span className="count">{rows.length}</span>
        <p>Games whose drops need your game account linked to Twitch. Linking before a campaign starts means it can be mined from the first minute.</p></div>
      <div className="zone">
        {shown.map(({ g, l }) => {
          const [label, tone] = LINK_LABEL[l.state];
          return (
            <div className="g link-row" key={g.game}>
              {g.box_art_url ? <img className="box" src={boxArt(g.box_art_url)} alt="" /> : <span className="box ph" aria-hidden="true" />}
              <div style={{ minWidth: 0 }}><div className="g-t">{g.game}</div>
                <div className="g-s">{g.priority ? `Priority ${g.priority} · ` : ""}<span className={`chip${tone ? ` ${tone}` : ""}`}>{label}</span></div></div>
              <div className="g-act">
                {l.state !== "linked" && (
                  <a className="btn" href={l.url} target="_blank" rel="noopener noreferrer" aria-label={`Link your ${g.game} account (opens the game's site)`}>
                    <Icon name="link" />Link account<Icon name="ext" /></a>
                )}
              </div>
            </div>
          );
        })}
        {!shown.length && <div className="empty">{rows.length ? "Every game is linked." : "No running campaign needs a game account."}</div>}
      </div>
      {linked > 0 && (
        <div className="bulk-open">
          <button className="btn quiet" type="button" aria-pressed={showLinked} onClick={() => setShowLinked(!showLinked)}>
            {showLinked ? "Hide linked games" : `Show linked games (${linked})`}</button>
        </div>
      )}
    </div>
  );
}
const ORDER: Record<LinkState, number> = { needs: 0, unknown: 1, linked: 2 };
