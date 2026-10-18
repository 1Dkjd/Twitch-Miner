import { useState } from "react";
import { ApiError, api } from "../api/client";
import { useApp } from "../store";

/** "I've linked it" (2026-10-18): after linking on the game's site, ask Twitch again right away instead of waiting
 * for the next scheduled check. Shown next to every Link account button. */
export function LinkedButton({ game, compact = false }: { game: string; compact?: boolean }) {
  const { say, refreshState } = useApp();
  const [busy, setBusy] = useState(false);
  async function check() {
    setBusy(true);
    try {
      const r = await api.post<{ status: string }>("/linked", { game });
      if (r.status === "linked") say({ title: `${game} is linked`, detail: "Twitch confirms it. It can be mined now." });
      else if (r.status === "not_linked") say({ title: `Twitch still says ${game} isn't linked`, detail: "Linking can take a few minutes to reach Twitch. Try again shortly.", tone: "bad" });
      else say({ title: `Checked ${game}`, detail: "Twitch doesn't say yet. Dropwatch will try mining it and see." });
    } catch (e) { say({ title: e instanceof ApiError ? e.message : "Couldn't check with Twitch", tone: "bad" }); }
    finally { setBusy(false); void refreshState(); }
  }
  return (
    <button className="btn quiet" type="button" disabled={busy} aria-label={`I've linked ${game}: check with Twitch`} onClick={() => void check()}>
      {busy ? "Checking…" : compact ? "Linked it" : "I've linked it"}
    </button>
  );
}
