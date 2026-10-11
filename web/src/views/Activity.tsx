import { useEffect, useState, type ReactNode } from "react";
import { api, type Activity, type ActivityEvent } from "../api/client";
import { useApp } from "../store";
import { clock, day } from "../ui/format";

/** Activity (approved mockup docs/design/pre-docker-mockup.html, 2026-10-10): what Dropwatch did, newest
 * first, one plain sentence per event, grouped by the viewer's day. The server keeps 7 days (store.py). */
type Group = "mining" | "rewards" | "problems" | "notifications";
const FILTERS: [Group | "all", string][] = [
  ["all", "All"], ["mining", "Mining"], ["rewards", "Rewards"], ["problems", "Problems"], ["notifications", "Notifications"],
];

export interface Line { text: ReactNode; d?: string; tone: "ok" | "gold" | "bad" | "note" | ""; group: Group }

const s = (v: unknown) => (typeof v === "string" ? v : "");
const QUIET = new Set(["mining", "switched"]);

function why(d: ActivityEvent["data"]): string {
  if (d.from_live === false) return `${s(d.from)} went offline`;
  const r = s(d.reason);
  if (r === "you picked it") return "You picked it";
  if (r === "you pinned it") return "Pinned in Up next";
  if (r.startsWith("priority ")) return `Priority ${r.slice(9)}`;
  if (r === "most urgent") return d.channel_reason === "favourite" ? "A favourite channel came online" : "Most urgent campaign";
  return "";
}

/** One event as a sentence, or null for one that only repeats what the line before it said. `older` is the
 * event logged just before it. */
export function describe(e: ActivityEvent, older: ActivityEvent | undefined): Line | null {
  const d = e.data;
  switch (e.kind) {
    case "started":
      return { text: <>Dropwatch started{d.commit ? <> <span className="mono">{s(d.commit)}</span></> : null}</>,
        d: d.version ? `Version ${s(d.version)}` : undefined, tone: "", group: "mining" };
    case "state": {
      const st = s(d.state);
      if (st === "switched") return null; // the switched event says it
      if (st === "mining") {
        if (older && (older.kind === "switched" || (older.kind === "state" && QUIET.has(s(older.data.state))))) return null;
        return { text: older?.kind === "state" ? "Mining again" : "Mining", tone: "ok", group: "mining" };
      }
      if (older?.kind === "state" && s(older.data.state) === st) return null;
      if (st === "idle") return { text: "Nothing to mine: none of your campaigns has a live channel", tone: "", group: "mining" };
      if (st === "paused") return { text: "Paused", tone: "", group: "mining" };
      if (st === "twitch_unreachable") return { text: "Couldn't reach Twitch", d: s(d.error) || undefined, tone: "bad", group: "problems" };
      if (st === "signed_out") return { text: "Signed out of Twitch", tone: "bad", group: "problems" };
      return null;
    }
    case "switched": {
      const game = s(d.game);
      const parts = [why(d), game && (d.campaign ? `${game} · ${s(d.campaign)}` : game)].filter(Boolean);
      return { text: <>Switched to <b>{s(d.to)}</b> from {s(d.from)}</>, d: parts.join(" · ") || undefined, tone: "note", group: "mining" };
    }
    case "claimed":
      return { text: <>Claimed <b>{s(d.reward)}</b> from {s(d.campaign)}</>, d: s(d.game) || undefined, tone: "ok", group: "rewards" };
    case "claim_failed":
      return { text: <>Couldn't claim a reward from {s(d.campaign)}</>, d: "Twitch turned it down", tone: "bad", group: "problems" };
    case "needs_you":
      return { text: <>{s(d.campaign)} may need its game account linked</>, tone: "bad", group: "problems" };
    case "channel_dropped":
      return { text: <>Stopped watching <b>{s(d.channel)}</b>: its stream wouldn't play</>, tone: "bad", group: "problems" };
    case "points_claimed":
      return { text: d.channel ? <>Opened a channel points chest on <b>{s(d.channel)}</b></> : "Opened a channel points chest",
        tone: "gold", group: "rewards" };
    case "points_claim_failed":
      return { text: d.channel ? <>Couldn't open a channel points chest on <b>{s(d.channel)}</b></> : "Couldn't open a channel points chest",
        tone: "bad", group: "problems" };
    case "notified": {
      const title = s(d.title).replace(/^Dropwatch: /, "");
      const sent = Array.isArray(d.sent) ? d.sent : [];
      const failed = Array.isArray(d.failed) ? d.failed : [];
      return sent.length
        ? { text: <>Sent “{title}” to {sent.join(", ")}</>, d: failed.length ? `Couldn't reach ${failed.join(", ")}` : undefined,
          tone: "", group: "notifications" }
        : { text: <>Couldn't send “{title}”</>, d: failed.length ? `Tried ${failed.join(", ")}` : undefined, tone: "bad", group: "notifications" };
    }
    default:
      return null;
  }
}

export function ActivityView() {
  const { state } = useApp();
  const [data, setData] = useState<Activity | null>(null);
  const [filter, setFilter] = useState<Group | "all">("all");
  useEffect(() => {
    let live = true;
    api.get<Activity>("/activity").then((a) => { if (live) setData(a); }).catch(() => undefined);
    return () => { live = false; };
  }, [state]); // every live event re-reads the state: re-read Activity with it

  const lines: { e: ActivityEvent; line: Line }[] = [];
  const events = data?.events ?? [];
  events.forEach((e, i) => {
    const line = describe(e, events[i + 1]);
    if (line && (filter === "all" || line.group === filter)) lines.push({ e, line });
  });
  const rows: ReactNode[] = [];
  let lastDay = "";
  for (const [i, { e, line }] of lines.entries()) {
    const label = day(e.at);
    if (label !== lastDay) { rows.push(<div className="day" key={`d-${label}`}>{label}</div>); lastDay = label; }
    rows.push(
      <div className="act" key={`${i}-${e.at}-${e.kind}`}>
        <span className="t">{clock(e.at)}</span><span className={`adot ${line.tone}`} aria-hidden="true" />
        <div><div className="s">{line.text}</div>{line.d && <div className="d">{line.d}</div>}</div>
      </div>,
    );
  }
  return (
    <section className="view" id="v-activity" aria-labelledby="h-activity">
      <div className="view-h">
        <h1 id="h-activity" className="disp" tabIndex={-1}>Activity</h1>
        <div className="chips" role="group" aria-label="Show">
          {FILTERS.map(([g, label]) => (
            <button key={g} type="button" aria-pressed={filter === g} onClick={() => setFilter(g)}>{label}</button>
          ))}
        </div>
      </div>
      {!data && <p className="lead">Loading…</p>}
      {data && rows.length > 0 && <div className="list act-list">{rows}</div>}
      {data && !rows.length && <p className="hint">{filter === "all" ? "Nothing yet." : `Nothing like that in the last ${data.kept_days} days.`}</p>}
      {data && <p className="keep">Kept for {data.kept_days} days.</p>}
    </section>
  );
}
