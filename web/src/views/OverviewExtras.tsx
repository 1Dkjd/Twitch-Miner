import { useEffect, useState } from "react";
import { api, type History, type State } from "../api/client";
import { NB, clock, day } from "../ui/format";
import { Icon } from "../ui/Icons";
import { watchMinutes } from "./History";

function useHistory(days: number, state: State) {
  const [data, setData] = useState<History | null>(null);
  useEffect(() => {
    let live = true;
    api.get<History>(`/history?days=${days}`).then((h) => { if (live) setData(h); }).catch(() => undefined);
    return () => { live = false; };
  }, [days, state.last_refresh]);
  return data;
}

/** The mockup's "Today" tiles. The server counts the last 24 hours rather than the viewer's day, so it says so. */
export function LastDay({ state }: { state: State }) {
  const data = useHistory(1, state);
  if (!data) return null;
  const { minutes, partial } = watchMinutes(data.claims);
  const watched = `${minutes >= 60 ? `${Math.floor(minutes / 60)}${NB}h${minutes % 60 ? `${NB}${minutes % 60}` : ""}` : `${minutes}${NB}min`}${partial ? "+" : ""}`;
  const minable = state.up_next.length + (state.current ? 1 : 0);
  return (
    <section className="today" aria-labelledby="h-today">
      <h2 id="h-today">Last 24 hours</h2>
      <dl className="today-grid">
        <div><dt>Rewards claimed</dt><dd>{data.total_rewards}</dd></div>
        <div><dt>Watched</dt><dd>{watched}</dd></div>
        <div><dt>Channel points</dt><dd>{(data.points?.points ?? 0).toLocaleString("en-US")}</dd></div>
        <div><dt>Minable campaigns</dt><dd>{minable}</dd></div>
      </dl>
    </section>
  );
}

const RECENT = 5;

/** The newest rewards claimed, one tile each; History has the rest. */
export function RecentlyClaimed({ state }: { state: State }) {
  const data = useHistory(30, state);
  const today = new Date().toDateString();
  const recent = [...(data?.claims ?? [])].sort((a, b) => +new Date(b.at) - +new Date(a.at))
    .flatMap((c) => c.rewards.map((r) => ({ r, c }))).slice(0, RECENT);
  if (!recent.length) return null;
  return (
    <section id="sec-recent" aria-labelledby="h-recent">
      <div className="sec-h"><h2 id="h-recent">Recently claimed</h2><a className="sec-link" href="#history">All history</a></div>
      <ul className="recent">
        {recent.map(({ r, c }, i) => (
          <li key={`${c.at}-${i}`}>
            <img src={r.image_url} alt="" />
            <div><div className="t">{r.name}</div><div className="s">{c.game}</div></div>
            <div className="w"><Icon name="check" />{new Date(c.at).toDateString() === today ? clock(c.at) : day(c.at)}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}
