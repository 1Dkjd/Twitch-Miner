import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, type Campaign, type Lists, type State, type Suggestions } from "../api/client";
import { useLists } from "../lists";
import { useApp } from "../store";
import { boxArt, day, dur } from "../ui/format";
import { Icon } from "../ui/Icons";

type Zone = "priority" | "fav" | "never";
const KEY: Record<Zone, keyof Lists> = { priority: "priority", fav: "favourites", never: "never" };
const NAME: Record<Zone, string> = { priority: "Priority", fav: "favourite channels", never: "Never" };
const EMPTY: Record<Zone, string> = {
  never: "Nothing blocked. Add a game below to stop it being mined.",
  priority: "No priority games. Everything is mined most urgent first.",
  fav: "No favourites. For each campaign, any live channel with drops on will do.",
};

/** Priorities (approved mockup): Priority (ordered), Favourite channels (ordered), Never. */
export function PrioritiesView() {
  const { state, say } = useApp();
  const { lists, save } = useLists();
  const [sugg, setSugg] = useState<Suggestions>({ games: [], channels: [] });
  const [focus, setFocus] = useState<[string, string] | null>(null);
  const drag = useRef<string | null>(null);
  useEffect(() => { api.get<Suggestions>("/suggestions").then(setSugg).catch(() => undefined); }, []);
  useEffect(() => {
    if (!focus) return;
    const [name, act] = focus;
    const row = document.querySelector<HTMLElement>(`.g[data-name="${CSS.escape(name)}"]`);
    let el = row?.querySelector<HTMLButtonElement>(`[data-act="${act}"]`) ?? null;
    if (!el || el.disabled) el = row?.querySelector<HTMLButtonElement>("button:not(:disabled)") ?? null;
    (el ?? document.getElementById("h-priorities"))?.focus();
    setFocus(null);
  }, [focus, lists]);

  if (!lists) {
    return <section className="view" aria-labelledby="h-priorities"><div className="view-h"><h1 id="h-priorities" className="disp" tabIndex={-1}>Priorities</h1></div></section>;
  }

  const zoneOf = (name: string): Zone | "pool" =>
    lists.favourites.includes(name) ? "fav" : lists.never.includes(name) ? "never" : lists.priority.includes(name) ? "priority" : "pool";

  /** The mockup's move(): games move between Priority / Never / nowhere; channels only in or out of favourites. */
  function moved(name: string, to: Zone | "pool", index?: number): Lists {
    const next: Lists = { priority: [...lists!.priority], never: [...lists!.never], favourites: [...lists!.favourites] };
    if (to === "fav" || zoneOf(name) === "fav") {
      next.favourites = next.favourites.filter((n) => n !== name);
      if (to !== "fav") return next;
    } else {
      next.priority = next.priority.filter((n) => n !== name);
      next.never = next.never.filter((n) => n !== name);
    }
    if (to === "pool") return next;
    const list = next[KEY[to]];
    if (index === undefined || index > list.length) list.push(name);
    else list.splice(index, 0, name);
    return next;
  }

  async function commit(next: Lists, message: string, f?: [string, string]) {
    const err = await save(next);
    say(err ?? message);
    if (f) setFocus(f);
    else document.getElementById("h-priorities")?.focus();
  }

  function onAct(name: string, act: string) {
    const z = zoneOf(name);
    if (act === "up" || act === "down") {
      if (z === "pool") return;
      const L = [...lists![KEY[z]]];
      const k = L.indexOf(name);
      const j = act === "up" ? k - 1 : k + 1;
      if (j < 0 || j >= L.length) return;
      L.splice(k, 1);
      L.splice(j, 0, name);
      void commit({ ...lists!, [KEY[z]]: L }, `${name} moved to position ${j + 1} of ${L.length}`, [name, act]);
    } else if (act === "never") void commit(moved(name, "never"), `${name} moved to Never`, [name, "remove"]);
    else if (act === "priority") void commit(moved(name, "priority"), `${name} added to Priority at position ${lists!.priority.filter((n) => n !== name).length + 1}`, [name, "up"]);
    else if (act === "remove") {
      void commit(moved(name, "pool"), `${name} removed from ${z === "pool" ? "the list" : NAME[z]}${z === "fav" ? "." : ". It will be mined by urgency."}`);
    }
  }

  // drag and drop between Priority and Never, and within each ordered list (drag ref is above)
  function drop(e: React.DragEvent<HTMLDivElement>, z: Zone) {
    e.preventDefault();
    e.currentTarget.classList.remove("over");
    const name = drag.current;
    if (!name) return;
    if ((z === "fav") !== (zoneOf(name) === "fav")) return; // channels and games don't mix
    let index: number | undefined;
    if (z !== "never") {
      const rows = [...e.currentTarget.querySelectorAll<HTMLElement>(".g")].filter((r) => r.dataset.name !== name);
      index = rows.findIndex((r) => { const b = r.getBoundingClientRect(); return e.clientY < b.top + b.height / 2; });
      if (index < 0) index = rows.length;
    }
    void commit(moved(name, z, index), `${name} moved to ${z === "never" ? "Never" : z === "fav" ? "favourite channels" : "Priority"}`);
  }

  const info = gameInfo(state);
  const liveChannels = new Set([state?.current?.channel.login, ...(state?.current?.channels.map((c) => c.login) ?? [])].filter(Boolean) as string[]);
  const liveGame = state?.current?.campaign.game;
  const pool = sugg.games.filter((g) => !lists.priority.includes(g) && !lists.never.includes(g));
  const knownCh = sugg.channels.filter((c) => !lists.favourites.includes(c));

  const zone = (z: Zone) => {
    const list = lists[KEY[z]];
    return (
      <div className="zone" data-zone={z} id={`z-${z}`}
        onDragOver={(e) => { if (!drag.current) return; e.preventDefault(); e.currentTarget.classList.add("over"); }}
        onDragLeave={(e) => e.currentTarget.classList.remove("over")}
        onDrop={(e) => drop(e, z)}>
        {list.length ? list.map((n, i) => (
          <Row key={n} name={n} zone={z} i={i} n={list.length} info={info} live={liveChannels.has(n) ? liveGame : undefined}
            onAct={onAct} onDragStart={() => { drag.current = n; }} onDragEnd={() => { drag.current = null; }} />
        )) : <div className="empty">{EMPTY[z]}</div>}
      </div>
    );
  };

  return (
    <section className="view" id="v-priorities" aria-labelledby="h-priorities">
      <div className="view-h"><h1 id="h-priorities" className="disp" tabIndex={-1}>Priorities</h1></div>
      <p className="lead">Every game with a drop campaign gets mined. Games in Priority go first, in your order. Games not listed here are mined after them, most urgent first. Overview shows the full order under Up next.</p>
      <datalist id="campaign-games">{pool.map((g) => <option key={g} value={g} />)}</datalist>
      <datalist id="known-channels">{knownCh.map((c) => <option key={c} value={c} />)}</datalist>
      <Bucket title="Priority" count={lists.priority.length} help="Mined first, top to bottom.">
        {zone("priority")}
        <AddForm to="priority" list="campaign-games" placeholder="Add a game" known={sugg.games} label="Add a game to Priority"
          onAdd={(name) => commit(moved(name, "priority"), `${name} added to Priority`)} />
      </Bucket>
      <Bucket title="Favourite channels" count={lists.favourites.length}
        help="When a campaign can be mined on several live channels, these get watched first, top to bottom. Your game order above still decides which campaign.">
        {zone("fav")}
        <AddForm to="fav" list="known-channels" placeholder="Add a channel" known={sugg.channels} label="Add a favourite channel"
          onAdd={(name) => commit(moved(name.toLowerCase(), "fav"), `${name} added to favourite channels`)} />
      </Bucket>
      <Bucket title="Never" count={lists.never.length} help="Never mined, even when nothing else is live.">
        {zone("never")}
        <AddForm to="never" list="campaign-games" placeholder="Add a game" known={sugg.games} label="Add a game to Never"
          onAdd={(name) => commit(moved(name, "never"), `${name} added to Never`)} />
      </Bucket>
    </section>
  );
}

function Bucket({ title, count, help, children }: { title: string; count: number; help: string; children: React.ReactNode }) {
  return (
    <div className="bucket">
      <div className="bucket-h"><h2>{title}</h2><span className="count">{count}</span><p>{help}</p></div>
      {children}
    </div>
  );
}

type Info = Map<string, { text: string; warn?: boolean; art?: string }>;

/** What each game is doing right now, for the row subtitles (as in the mockup). */
function gameInfo(state: State | null): Info {
  const m: Info = new Map();
  if (!state) return m;
  const put = (c: Campaign, text: string, warn = false) => { if (!m.has(c.game)) m.set(c.game, { text, warn, art: boxArt(c.box_art_url) }); };
  if (state.current) put(state.current.campaign, `Mining now · ${dur(state.current.campaign.minutes_needed)} to go · ends ${day(state.current.campaign.ends_at)}`);
  for (const c of state.needs_you) put(c, `${c.maybe_unlinked ? "May need account link" : "Needs account link"} · ends ${day(c.ends_at)}`, true);
  for (const c of state.up_next) put(c, `${dur(c.minutes_needed)} to go · ends ${day(c.ends_at)}`);
  for (const c of state.done) {
    const n = c.drops.reduce((k, d) => k + d.rewards.length, 0);
    put(c, `All ${n} ${n === 1 ? "reward" : "rewards"} claimed`);
  }
  return m;
}

function Row({ name, zone, i, n, info, live, onAct, onDragStart, onDragEnd }: {
  name: string; zone: Zone; i: number; n: number; info: Info; live?: string;
  onAct: (name: string, act: string) => void; onDragStart: () => void; onDragEnd: () => void;
}) {
  const btn = (act: string, label: string, content: React.ReactNode, cls = "ib", disabled = false) => (
    <button className={cls} type="button" data-act={act} aria-label={label} disabled={disabled} onClick={() => onAct(name, act)}>{content}</button>
  );
  const common = {
    className: `g ${zone}`, "data-name": name, draggable: true,
    onDragStart: (e: React.DragEvent) => { e.currentTarget.classList.add("dragging"); try { e.dataTransfer.setData("text/plain", name); e.dataTransfer.effectAllowed = "move"; } catch { /* old browsers */ } onDragStart(); },
    onDragEnd: (e: React.DragEvent) => { e.currentTarget.classList.remove("dragging"); onDragEnd(); },
  };
  if (zone === "fav") {
    return (
      <div {...common}>
        <span className="rank">{i + 1}</span><span className="handle" aria-hidden="true"><Icon name="grip" /></span>
        <span className="avatar" aria-hidden="true">{name.charAt(0)}</span>
        <div style={{ minWidth: 0 }}><div className="g-t">{name}</div>
          <div className="g-s">{live ? <span className="on">Live now · {live}</span> : "Not live with drops right now"}</div></div>
        <div className="g-act">
          {btn("up", `Move ${name} up`, <Icon name="up" />, "ib", i === 0)}
          {btn("down", `Move ${name} down`, <Icon name="down" />, "ib", i === n - 1)}
          {btn("remove", `Remove ${name} from favourite channels`, "Remove", "btn quiet")}
        </div>
      </div>
    );
  }
  const inf = info.get(name);
  return (
    <div {...common}>
      <span className="rank">{zone === "priority" ? i + 1 : ""}</span><span className="handle" aria-hidden="true"><Icon name="grip" /></span>
      {inf?.art ? <img className="box" src={inf.art} alt="" /> : <span className="box ph" style={{ width: 36 }} aria-hidden="true" />}
      <div style={{ minWidth: 0 }}><div className="g-t">{name}</div>
        <div className={`g-s${inf?.warn ? " warn" : ""}`}>{inf?.text ?? "No campaign right now"}</div></div>
      <div className="g-act">
        {zone === "priority" ? <>
          {btn("up", `Move ${name} up`, <Icon name="up" />, "ib", i === 0)}
          {btn("down", `Move ${name} down`, <Icon name="down" />, "ib", i === n - 1)}
          {btn("never", `Never mine ${name}`, "Never mine", "btn quiet")}
          {btn("remove", `Remove ${name} from Priority`, "Remove", "btn quiet")}
        </> : <>
          {btn("priority", `Move ${name} to Priority`, "Prioritise", "btn quiet")}
          {btn("remove", `Allow ${name} again`, "Allow again", "btn quiet")}
        </>}
      </div>
    </div>
  );
}

function AddForm({ to, list, placeholder, known, label, onAdd }: {
  to: Zone; list: string; placeholder: string; known: string[]; label: string; onAdd: (name: string) => Promise<void> | void;
}) {
  const [v, setV] = useState("");
  const [unknown, setUnknown] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const val = v.trim();
    if (!val) return;
    const match = known.find((n) => n.toLowerCase() === val.toLowerCase());
    if (!match) { setUnknown(val); return; }
    setV(""); setUnknown(null);
    await onAdd(match);
    input.current?.focus();
  }
  return (
    <form className="add" data-to={to} noValidate onSubmit={submit}>
      <div className="add-row">
        <input ref={input} id={`add-${to}`} type="text" list={list} placeholder={placeholder} aria-label={label} autoComplete="off"
          value={v} onChange={(e) => setV(e.target.value)} />
        <button className="btn" type="submit">Add</button>
      </div>
      {unknown && (
        <div className="confirm">
          <span>{to === "fav"
            ? <>The miner hasn't seen a channel called <b>{unknown}</b> yet. Check the spelling, or add it anyway.</>
            : <>No game called <b>{unknown}</b> has a campaign right now. Check the spelling, or add it so it's ready when one starts.</>}</span>
          <span className="acts">
            <button className="btn" type="button" onClick={async () => { const n = unknown; setV(""); setUnknown(null); await onAdd(n); input.current?.focus(); }}>Add anyway</button>
            <button className="btn quiet" type="button" onClick={() => { setUnknown(null); input.current?.focus(); }}>Cancel</button>
          </span>
        </div>
      )}
    </form>
  );
}
