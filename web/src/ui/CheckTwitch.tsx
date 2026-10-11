import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../store";
import { clock } from "./format";
import { Icon } from "./Icons";

/** Top bar "Check Twitch" (asked for 2026-10-10): re-read campaigns (link status included) and live
 * channels now, instead of waiting for Settings' "Check Twitch for campaign changes" interval. */
export function CheckTwitch() {
  const { refreshState, say, sayError } = useApp();
  const [phase, setPhase] = useState<"idle" | "busy" | "done" | "failed">("idle");
  const [at, setAt] = useState<Date | null>(null);
  const reset = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(reset.current), []);

  async function check() {
    if (phase === "busy") return;
    clearTimeout(reset.current);
    setPhase("busy");
    try {
      await api.post("/refresh");
      setAt(new Date());
      setPhase("done");
      say("Checked Twitch for campaigns and live channels.");
    } catch (e) {
      setPhase("failed");
      sayError(e, "Couldn't check Twitch");
    } finally {
      void refreshState();
      reset.current = setTimeout(() => setPhase("idle"), 4000);
    }
  }

  const text = { idle: "Check Twitch", busy: "Checking…", done: "Checked", failed: "Couldn't check" }[phase];
  return (
    <button type="button" className={`btn quiet check-tw${phase === "busy" ? " busy" : ""}`} aria-label="Check Twitch"
      aria-disabled={phase === "busy"} title={at ? `Last checked at ${clock(at)}` : "Re-read campaigns and live channels now"}
      onClick={() => void check()}>
      <Icon name="refresh" /><span className="check-tw-t">{text}</span>
    </button>
  );
}
