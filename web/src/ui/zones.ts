/** Time zones for the weekly summary, named the way people say them: "Eastern Time (New York)". */
export interface Zone { id: string; label: string }

let cache: Zone[] | null = null;

function label(id: string): string {
  const city = id.split("/").pop()!.replace(/_/g, " ");
  try {
    const part = new Intl.DateTimeFormat("en-GB", { timeZone: id, timeZoneName: "longGeneric" })
      .formatToParts(new Date()).find((p) => p.type === "timeZoneName")?.value;
    return part && part !== city ? `${part} (${city})` : city;
  } catch {
    return city;
  }
}

/** Every zone the browser knows, by label; the device's own zone first. */
export function zones(): Zone[] {
  if (cache) return cache;
  const list = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];
  const ids = [...new Set([...list, "UTC"])];
  const all = ids.map((id) => ({ id, label: label(id) })).sort((a, b) => a.label.localeCompare(b.label));
  const here = deviceZone();
  const mine = all.find((z) => z.id === here);
  cache = mine ? [{ ...mine, label: `${mine.label}, this device` }, ...all.filter((z) => z !== mine)] : all;
  return cache;
}

export function deviceZone(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { return "UTC"; }
}
