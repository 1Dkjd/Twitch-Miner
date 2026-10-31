export interface Milestone {
  at: number;
  items: { name: string; image: string }[];
}

/** The campaign's watch time as one segment per reward mark (docs/design/twitch-native-mockup/, Overview). */
export function Track({ ms, watched, max, label }: { ms: Milestone[]; watched: number; max: number; label: string }) {
  return (
    <div className="track" role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={watched}
      aria-valuetext={label} data-testid="track">
      {ms.map((m, i) => {
        const from = i ? ms[i - 1]!.at : 0;
        const pct = Math.max(0, Math.min(100, ((watched - from) / (m.at - from)) * 100));
        return <span className="seg-bar" key={m.at}><span style={{ width: `${pct}%` }} /></span>;
      })}
    </div>
  );
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
