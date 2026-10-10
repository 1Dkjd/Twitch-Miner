import { useLayoutEffect, useRef } from "react";
import { NB, mark } from "../ui/format";

export interface Milestone {
  at: number;
  items: { name: string; image: string }[];
}

/** The reward track, ported from the approved mockup's layoutTrack(): art is placed without
 * collisions with the next and final reward first; narrow tracks that can't fit every reward switch to
 * compact mode (earned milestones merge into one marker, art only for next and final, "+N more"). */
export function Track({ ms, watched, max, nextIdx, label }: { ms: Milestone[]; watched: number; max: number; nextIdx: number; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const run = () => layoutTrack(el, ms, watched, max, nextIdx);
    run();
    if (!("ResizeObserver" in window)) return;
    const ro = new ResizeObserver(run);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ms, watched, max, nextIdx]);
  return (
    <div className="track" ref={ref} role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={watched}
      aria-valuetext={label} data-testid="track" />
  );
}

export function layoutTrack(t: HTMLElement, ms: Milestone[], w: number, max: number, nextIdx: number, compact = false): void {
  const W = t.offsetWidth;
  if (!W || !ms.length || !max) return;
  const last = ms.length - 1;
  const x = (at: number) => (at / max) * W;
  const got = ms.map((_, i) => i).filter((i) => ms[i]!.at <= w);
  const pct = Math.min(100, (w / max) * 100);
  let html = `<div class="rail"><div class="fill" style="width:${pct}%"></div><div class="head" style="left:${pct}%"></div></div>`;
  ms.forEach((m, i) => {
    const isGot = m.at <= w;
    if (compact && isGot && i !== got[got.length - 1]) return;
    html += `<span class="ms-dot ${isGot ? "got" : i === nextIdx ? "next" : ""}" style="left:${x(m.at)}px"></span>`;
  });
  t.innerHTML = html;
  const order = (compact ? [nextIdx, last] : [nextIdx, last, ...ms.map((_, i) => i)])
    .filter((v, i, a) => v >= 0 && a.indexOf(v) === i);
  const taken: [number, number][] = [];
  const labTaken: [number, number][] = [];
  const free = (arr: [number, number][], a: number, b: number) => arr.every((r) => b + 6 <= r[0] || a >= r[1] + 6);
  let dropped = 0;
  const label = (text: string, cls: string, cx: number) => {
    const l = document.createElement("span");
    l.className = `ms-lab ${cls}`;
    l.textContent = text;
    t.appendChild(l);
    const lw = l.offsetWidth;
    const ll = Math.max(0, Math.min(W - lw, cx - lw / 2));
    if (free(labTaken, ll, ll + lw)) {
      l.style.left = `${ll}px`;
      labTaken.push([ll, ll + lw]);
    } else l.remove();
  };
  order.forEach((i) => {
    const m = ms[i]!;
    const cls = m.at <= w ? "got" : i === nextIdx ? "next" : "";
    const g = document.createElement("div");
    g.className = `ms-art ${cls}`;
    for (const it of m.items) {
      const img = document.createElement("img");
      img.src = it.image;
      img.alt = "";
      g.appendChild(img);
    }
    t.appendChild(g);
    const gw = g.offsetWidth;
    const cx = x(m.at);
    const left = Math.max(0, Math.min(W - gw, cx - gw / 2));
    if (free(taken, left, left + gw)) {
      g.style.left = `${left}px`;
      taken.push([left, left + gw]);
      const s = document.createElement("span");
      s.className = "ms-stem";
      s.style.left = `${cx}px`;
      t.appendChild(s);
    } else {
      g.remove();
      dropped++;
    }
    label(mark(m.at), i === nextIdx ? "next" : "", cx);
  });
  if (compact) {
    if (got.length) label(`${got.length}${NB}earned`, "got", x(ms[got[got.length - 1]!]!.at));
    const hidden = ms.filter((m, i) => m.at > w && i !== nextIdx && i !== last).length;
    if (hidden && taken.length === 2) {
      const tag = document.createElement("span");
      tag.className = "ms-more";
      tag.textContent = `+${hidden} more`;
      t.appendChild(tag);
      const [a, b] = taken.slice().sort((p, q) => p[0] - q[0]) as [[number, number], [number, number]];
      const mid = (a[1] + b[0]) / 2;
      const tw = tag.offsetWidth;
      if (b[0] - a[1] > tw + 12) tag.style.left = `${mid - tw / 2}px`;
      else tag.remove();
    }
    return;
  }
  // switch to compact when the full layout had to drop art or earned markers crowd together
  const gx = got.map((i) => x(ms[i]!.at));
  const crowded = gx.some((v, k) => k > 0 && v - gx[k - 1]! < 18);
  if (W < 560 && (dropped || crowded)) layoutTrack(t, ms, w, max, nextIdx, true);
}

/** Drops -> milestones: one per distinct required-minutes mark, with every reward earned there. */
export function milestones(drops: { required_minutes: number; current_minutes: number; claimed: boolean; rewards: { name: string; image_url: string }[] }[]) {
  const by = new Map<number, Milestone>();
  for (const d of drops) {
    if (d.required_minutes <= 0) continue;
    const m = by.get(d.required_minutes) ?? { at: d.required_minutes, items: [] };
    m.items.push(...d.rewards.map((r) => ({ name: r.name, image: r.image_url })));
    by.set(d.required_minutes, m);
  }
  const ms = [...by.values()].sort((a, b) => a.at - b.at);
  const watched = Math.max(0, ...drops.map((d) => (d.claimed ? d.required_minutes : d.current_minutes)));
  const max = ms.length ? ms[ms.length - 1]!.at : 0;
  const nextIdx = ms.findIndex((m) => m.at > watched);
  return { ms, watched, max, nextIdx };
}
