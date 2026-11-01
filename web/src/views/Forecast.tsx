import { useState } from "react";
import type { State } from "../api/client";
import { boxArt, clock, day } from "../ui/format";
import { Icon } from "../ui/Icons";

const SHOWN = 5;
const at = (d: string) => (new Date(d).toDateString() === new Date().toDateString() ? clock(d) : `${day(d)} ${clock(d)}`);
const rewards = (n: number) => `${n} ${n === 1 ? "reward" : "rewards"}`;
const CHIP: Record<string, [string, string]> = { partial: ["warn", "Some rewards at risk"], miss: ["red", "Won't make it"] };

/** Forecast: what gets mined when, and what won't make it (src/dropwatch/forecast.py). Anything at risk always
 * shows; the rest folds after the first few. The server sends nothing when it can't say (signed out, say). */
export function Forecast({ state }: { state: State }) {
  const [all, setAll] = useState(false);
  const f = state.forecast;
  if (!f?.steps.length) return null;
  const shown = all ? f.steps : f.steps.filter((s, i) => i < SHOWN || s.status !== "ok");
  return (
    <section id="sec-forecast" aria-labelledby="h-forecast">
      <div className="sec-h"><h2 id="h-forecast">Forecast</h2>
        {f.missed > 0
          ? <span className="chip red"><Icon name="alert" />{rewards(f.missed)} won't make it</span>
          : <span className="chip green"><Icon name="check" />Everything finishes{f.finishes_at ? ` by ${at(f.finishes_at)}` : ""}</span>}
        <span className="aside">An estimate: assumes streams stay live and this order holds</span></div>
      <ol className="list fc-list" id="forecast-list">
        {f.steps.filter((s) => shown.includes(s)).map((s, i) => {
          const chip = CHIP[s.status];
          return (
            <li className="row" key={s.campaign_id}>
              <img className="box" src={boxArt(s.box_art_url)} alt="" />
              <div>
                <div className="row-t">{s.name}</div>
                <div className="row-s">{s.game}<span className="sep">·</span>
                  {s.alongside ? "earned alongside" : i === 0 && new Date(s.starts_at) <= new Date() ? "now" : `from ${at(s.starts_at)}`}
                  {s.rewards_earned > 0 && <><span className="sep">·</span>{rewards(s.rewards_earned)} by {at(s.finishes_at)}</>}</div>
                {s.missed.length > 0 && <div className="why">Won't make it: {s.missed.join(", ")}</div>}
              </div>
              {chip && <span className={`chip ${chip[0]}`}>{chip[1]}</span>}
            </li>
          );
        })}
      </ol>
      {f.steps.length > shown.length || all ? (
        <button className="btn quiet more" type="button" aria-expanded={all} aria-controls="forecast-list" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${f.steps.length}`}<Icon name="down" className="chev" /></button>
      ) : null}
      {f.waiting.length > 0 && <p className="hint fc-wait">Not scheduled, waiting for a live channel: {f.waiting.join(", ")}</p>}
    </section>
  );
}
