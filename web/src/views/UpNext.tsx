import { DndContext, KeyboardSensor, MouseSensor, TouchSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS as DndCSS } from "@dnd-kit/utilities";
import { useEffect, useState } from "react";
import { api, type Campaign, type Settings, type State } from "../api/client";
import { useApp } from "../store";
import { NB, boxArt, clock, day, dur } from "../ui/format";
import { Icon } from "../ui/Icons";
import { milestones } from "./Track";

const SHOWN = 5;

/** Up next (approved mockup docs/design/next-features-mockup.html, 2026-10-10): a filter over every queued
 * campaign, a red warning on a campaign that would end before its turn, and "Arrange myself" pins that go
 * first after Priority in Nick's order (drag, or the arrows). The rest stays in the automatic order. */
export function UpNext({ state, priorityOf, onNever, onPriority }: {
  state: State; priorityOf: (g: string, ordinal?: boolean) => string | null; onNever: (game: string) => void;
  onPriority: (game: string) => void;
}) {
  const { refreshState, say, sayError } = useApp();
  const [all, setAll] = useState(false);
  const [filter, setFilter] = useState("");
  const [arrange, setArrange] = useState<boolean | null>(null);
  const [pins, setPins] = useState<string[]>([]);
  const [showOutside, setShowOutside] = useState(false);
  const [showLate, setShowLate] = useState(false);
  // Settings > Mining (2026-10-18): campaigns skipped because nothing left can finish in time
  const late = state.too_late ?? [];
  // Priority only (approved 2026-10-12): just Priority games are mined; the rest fold into one line
  const po = !!state.priority_only;
  const outside = state.outside ?? [];
  useEffect(() => { if (!po) setShowOutside(false); }, [po]);  // fold closed again next time it's switched on
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  useEffect(() => {
    api.get<Settings>("/settings").then((s) => setArrange(!!s.arrange_up_next)).catch(() => setArrange(false));
  }, []);
  // re-read after every refresh: the server drops pins of campaigns that ended
  useEffect(() => {
    api.get<{ pins: string[] }>("/pins").then((p) => setPins(p.pins)).catch(() => undefined);
  }, [state.last_refresh]);
  if (!state.up_next.length && !(po && outside.length) && !late.length) return null;

  async function savePins(next: string[], said: string) {
    try { setPins((await api.put<{ pins: string[] }>("/pins", { pins: next })).pins); say(said); }
    catch (e) { sayError(e, "Couldn't save the order"); }
    void refreshState();
  }
  async function toggle(on: boolean) {
    setArrange(on);
    try { await api.put("/settings", { arrange_up_next: on }); say(on ? "Arrange myself is on" : "Back to the automatic order"); }
    catch (e) { setArrange(!on); sayError(e, "Couldn't save"); }
    void refreshState();
  }
  // the pinned campaigns shown in Up next, in order: the one being mined (or one with no live channel)
  // can be pinned too but isn't shown, so moves work on what is visible and keep the others in place
  const visiblePins = state.up_next.filter((c) => c.pinned && pins.includes(c.id)).map((c) => c.id);
  function reorder(from: number, to: number) {
    const next = arrayMove(visiblePins, from, to);
    let k = 0;
    void savePins(pins.map((p) => (visiblePins.includes(p) ? next[k++]! : p)), `Moved to pin ${to + 1} of ${visiblePins.length}`);
  }
  const move = (id: string, by: number) => {
    const i = visiblePins.indexOf(id), j = i + by;
    if (i >= 0 && j >= 0 && j < visiblePins.length) reorder(i, j);
  };
  function onDragEnd(e: DragEndEvent) {
    const a = String(e.active.id), b = e.over ? String(e.over.id) : null;
    if (b && a !== b && visiblePins.includes(a) && visiblePins.includes(b)) reorder(visiblePins.indexOf(a), visiblePins.indexOf(b));
  }

  const needle = filter.trim().toLowerCase();
  const hits = needle ? state.up_next.filter((c) => `${c.name} ${c.game}`.toLowerCase().includes(needle)) : state.up_next;
  const shown = needle || all ? hits : hits.slice(0, SHOWN);
  const more = state.up_next.length - SHOWN;
  // pins don't count while Priority only is on, so neither does Arrange myself (its switch is hidden then)
  const arr = !po && !!arrange;
  const manual = arr && !needle;
  const pinnedShown = shown.filter((c) => c.pinned).map((c) => c.id);
  const curGame = state.current?.campaign.game;

  const row = (c: Campaign) => (
    <UpNextRow key={c.id} c={c} pr={priorityOf(c.game)} arrange={arr} pinned={arr && c.pinned}
      pinIndex={visiblePins.indexOf(c.id)} pinCount={visiblePins.length}
      onMineNow={async () => {
        try { await api.post("/mine-now", { campaign_id: c.id }); say(`Mining ${c.name} now`); }
        catch (e) { sayError(e, "Couldn't switch to it"); }
        void refreshState();
      }}
      onNever={() => onNever(c.game)}
      onPriority={() => onPriority(c.game)}
      onPin={() => savePins([...pins, c.id], `${c.name} pinned`)}
      onUnpin={() => savePins(pins.filter((p) => p !== c.id), `${c.name} unpinned`)}
      onMove={(by) => move(c.id, by)} />
  );
  const header = (
    <>
      {curGame && !arr && state.up_next.length > 0 && <span className="aside">Starts when {curGame} is done or its streams go offline</span>}
      {po && !state.up_next.length && <span className="aside">Priority only is on</span>}
      {!po && <label className="arr"><input type="checkbox" role="switch" className="sw" aria-label="Arrange myself" disabled={arrange === null}
        checked={!!arrange} onChange={(e) => void toggle(e.target.checked)} /><span aria-hidden="true">Arrange myself</span></label>}
      {state.up_next.length > 0 && <label className="filter"><input type="search" aria-label="Filter Up next" placeholder="Filter by game or campaign"
        value={filter} onChange={(e) => setFilter(e.target.value)} />{needle && <span className="n">{hits.length} of {state.up_next.length}</span>}</label>}
    </>
  );
  const pinnedRows = shown.filter((c) => manual && c.pinned);
  const restRows = shown.filter((c) => !(manual && c.pinned));
  const body = (
    <>
      <div className="list" id="up-next-list">
        {needle && !hits.length && <div className="row"><span /><div className="row-s">Nothing in Up next matches "{filter.trim()}".</div></div>}
        {manual && pinnedRows.length > 0 && <div className="pins-h">Pinned · mined first, in your order</div>}
        {manual && (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={pinnedShown} strategy={verticalListSortingStrategy}>{pinnedRows.map(row)}</SortableContext>
          </DndContext>
        )}
        {manual && (
          <div className="auto-h">{pins.length ? "Then automatic · most urgent first" : "Automatic · most urgent first · pin any to put it first"}</div>
        )}
        {restRows.map(row)}
        {po && outside.length > 0 && (
          <button className="ign-foot" type="button" aria-expanded={showOutside} aria-controls="outside-list"
            aria-label={`Not mined: ${outside.length} ${outside.length === 1 ? "campaign" : "campaigns"} outside Priority · ${showOutside ? "Hide" : "Show"}`}
            onClick={() => setShowOutside(!showOutside)}>
            Not mined: {outside.length} {outside.length === 1 ? "campaign" : "campaigns"} outside Priority
            <span className="sep">·</span><u>{showOutside ? "Hide" : "Show"}</u>
          </button>
        )}
        {late.length > 0 && (
          <button className="ign-foot" type="button" aria-expanded={showLate} aria-controls="late-list"
            aria-label={`Skipped: ${late.length} ${late.length === 1 ? "campaign" : "campaigns"} can't finish in time · ${showLate ? "Hide" : "Show"}`}
            onClick={() => setShowLate(!showLate)}>
            Skipped: {late.length} {late.length === 1 ? "campaign" : "campaigns"} can't finish in time
            <span className="sep">·</span><u>{showLate ? "Hide" : "Show"}</u>
          </button>
        )}
        {showLate && (
          <div id="late-list">
            {late.map((c) => (
              <UpNextRow key={c.id} c={c} pr={null} arrange={false} pinned={false} pinIndex={-1} pinCount={0}
                onMineNow={async () => {
                  try { await api.post("/mine-now", { campaign_id: c.id }); say(`Trying ${c.name} anyway`); }
                  catch (e) { sayError(e, "Couldn't start it"); }
                  void refreshState();
                }}
                onNever={() => onNever(c.game)} onPriority={() => onPriority(c.game)}
                onPin={() => undefined} onUnpin={() => undefined} onMove={() => undefined} />
            ))}
          </div>
        )}
        {po && showOutside && (
          <div id="outside-list">
            {outside.map((c) => (
              <UpNextRow key={c.id} c={c} pr={null} arrange={false} pinned={false} pinIndex={-1} pinCount={0} outside
                onMineNow={() => undefined} onNever={() => onNever(c.game)} onPriority={() => onPriority(c.game)}
                onPin={() => undefined} onUnpin={() => undefined} onMove={() => undefined} />
            ))}
          </div>
        )}
      </div>
      {!needle && more > 0 && (
        <button className="btn quiet more" type="button" aria-expanded={all} aria-controls="up-next-list" onClick={() => setAll(!all)}>
          {all ? "Show only the next " + SHOWN : `Show all ${state.up_next.length}`}<Icon name="down" className="chev" /></button>
      )}
    </>
  );
  return (
    <section id="sec-next" aria-labelledby="h-next">
      <div className="sec-h"><h2 id="h-next">Up next</h2><span className="count">{state.up_next.length}</span>{header}<a className="sec-link" href="#priorities">Edit priorities</a></div>
      {body}
    </section>
  );
}

function UpNextRow({ c, pr, arrange, pinned, pinIndex, pinCount, outside, onMineNow, onNever, onPriority, onPin, onUnpin, onMove }: {
  c: Campaign; pr: string | null; arrange: boolean; pinned: boolean; pinIndex: number; pinCount: number;
  outside?: boolean;  // Priority only: not mined, so no Mine now
  onMineNow: () => void; onNever: () => void; onPriority: () => void; onPin: () => void; onUnpin: () => void;
  onMove: (by: number) => void;
}) {
  // offered only for games not on Priority yet (pr is their "Priority N" label)
  const addToPriority = !pr && (
    <button className="btn quiet" type="button" aria-label={`Add ${c.game} to Priority`} onClick={onPriority}>Add to Priority</button>
  );
  const sortable = useSortable({ id: c.id, disabled: !pinned });
  const { watched, max } = milestones(c.drops);
  const firstOpen = [...c.drops].filter((x) => !x.claimed && x.rewards.length).sort((a, b) => a.required_minutes - b.required_minutes)[0];
  const style = pinned ? { transform: DndCSS.Translate.toString(sortable.transform), transition: sortable.transition } : undefined;
  return (
    <div className={`row${pinned ? " pinned" : ""}${sortable.isDragging ? " placeholder" : ""}`} ref={pinned ? sortable.setNodeRef : undefined} style={style}>
      <img className="box" src={boxArt(c.box_art_url)} alt="" />
      <div>
        <div className="row-t">{c.name}{c.new && <> <span className="chip note" title="Dropwatch first saw this campaign in the last 24 hours">New</span></>}</div>
        <div className="row-s">{c.game}{pr && <><span className="sep">·</span>{pr}</>}<span className="sep">·</span>ends {day(c.ends_at)}</div>
        {firstOpen && <div className="row-art">{firstOpen.rewards.map((x, i) => <img key={i} src={x.image_url} alt={x.name} />)}</div>}
        {c.ends_before_turn && (
          <div className="turn"><span className="chip red">Ends {day(c.ends_at)} {clock(c.ends_at)}, before its turn</span></div>
        )}
      </div>
      <div className="row-acts">
        {max > 0 && !arrange && (
          <div className="mini" aria-label={`${watched} of ${max} minutes watched`}>
            <div className="rail"><div className="fill" style={{ width: `${(watched / max) * 100}%` }} /></div>
            <span className="label">{watched} / {max}{NB}min · {dur(c.minutes_needed)} to go</span>
          </div>
        )}
        {!arrange && <>
          {!outside && <button className="btn" type="button" aria-label={`Mine ${c.name} now`} onClick={onMineNow}>Mine now</button>}
          {addToPriority}
          <button className="btn quiet" type="button" aria-label={`Never mine ${c.game}`} onClick={onNever}>Never mine</button>
        </>}
        {arrange && pinned && <>
          <span className="grip" {...sortable.attributes} {...sortable.listeners} aria-label={`Drag ${c.name} to reorder`}><Icon name="grip" /></span>
          <button className="btn quiet" type="button" aria-label={`Move ${c.name} up`} disabled={pinIndex <= 0} onClick={() => onMove(-1)}><Icon name="up" /></button>
          <button className="btn quiet" type="button" aria-label={`Move ${c.name} down`} disabled={pinIndex >= pinCount - 1} onClick={() => onMove(1)}><Icon name="down" /></button>
          <button className="btn" type="button" aria-label={`Unpin ${c.name}`} onClick={onUnpin}>Unpin</button>
        </>}
        {arrange && !pinned && <>
          <button className="btn" type="button" aria-label={`Pin ${c.name} to the top`} onClick={onPin}>Pin to top</button>
          {addToPriority}
          <button className="btn quiet" type="button" aria-label={`Never mine ${c.game}`} onClick={onNever}>Never mine</button>
        </>}
      </div>
    </div>
  );
}
