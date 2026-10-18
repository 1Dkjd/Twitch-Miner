import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../store";

const FIELDS: [string, string][] = [["status", "Status"], ["game", "Game"], ["progress", "Progress"],
  ["next_in_minutes", "Next reward in"], ["needs_you", "Needs you"], ["claimed_today", "Claimed today"]];

export function homepageYaml(origin: string, key: string): string {
  return [
    "- Dropwatch:",
    "    icon: https://raw.githubusercontent.com/KernelPanic-Studios/dropwatch/main/brand/png/icon-256.png",
    `    href: ${origin}`,
    "    widget:",
    "      type: customapi",
    `      url: ${origin}/api/widget?key=${key}`,
    "      refreshInterval: 60000",
    "      mappings:",
    ...FIELDS.flatMap(([field, label]) => [
      `        - field: ${field}`,
      `          label: ${label}`,
      ...(field === "progress" ? ["          format: number", "          suffix: \"%\""]
        : field === "next_in_minutes" ? ["          format: number", "          suffix: \" min\""] : []),
    ]),
  ].join("\n");
}

/** Settings › Homepage widget (2026-10-18): a key for the read-only /api/widget summary, and the ready-made
 * Homepage entry. The key is shown once; Dropwatch keeps only a hash of it. */
export function WidgetSettings() {
  const { say, sayError } = useApp();
  const [exists, setExists] = useState<boolean | null>(null);
  const [key, setKey] = useState<string | null>(null);
  useEffect(() => { api.get<{ exists: boolean }>("/widget/key").then((r) => setExists(r.exists)).catch(() => setExists(false)); }, []);
  async function make() {
    try { const r = await api.post<{ key: string }>("/widget/key"); setKey(r.key); setExists(true); }
    catch (e) { sayError(e, "Couldn't make a key"); }
  }
  async function revoke() {
    try { await api.del("/widget/key"); setKey(null); setExists(false); say("Widget key revoked. Dashboards using it stop updating."); }
    catch (e) { sayError(e, "Couldn't revoke it"); }
  }
  const yaml = key ? homepageYaml(location.origin, key) : "";
  return (
    <>
      <div className="opt">
        <div><div>Widget key</div>
          <div className="d">Lets a dashboard such as Homepage read a small summary (what's being mined, progress, next reward, what needs you) without the page password. It can't change anything.</div></div>
        {exists
          ? <span className="acts"><button className="btn" type="button" onClick={() => void make()}>New key</button>
              <button className="btn quiet" type="button" onClick={() => void revoke()}>Revoke</button></span>
          : <button className="btn strong" type="button" disabled={exists === null} onClick={() => void make()}>Make a key</button>}
      </div>
      {key && (
        <div className="opt widget-yaml">
          <div><div>Add this to Homepage's <b>services.yaml</b></div>
            <div className="d">Shown once: Dropwatch only keeps a fingerprint of the key. Making a new key stops the old one.</div>
            <pre className="mono" aria-label="Homepage entry">{yaml}</pre></div>
          <button className="btn" type="button" onClick={() => { void navigator.clipboard?.writeText(yaml).then(() => say("Copied")); }}>Copy</button>
        </div>
      )}
    </>
  );
}
