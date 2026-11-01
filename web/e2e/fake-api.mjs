// For the Playwright layout tests: serves web/dist with made-up API data, including a long name that has to wrap.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
const dist = process.argv[2] ?? "dist";
const inD = (d) => new Date(Date.now() + d * 864e5).toISOString();
const img = (n, c = "#3a2a5c") => `/img/${encodeURIComponent(n)}.svg?c=${encodeURIComponent(c)}`;
const r = (n) => ({ name: n, image_url: img(n, "#2a2a30") });
const drop = (id, req, cur, claimed, name) => ({ id, name, required_minutes: req, current_minutes: cur, claimed, required_subs: 0, requires: [], starts_at: inD(-2), ends_at: inD(3), rewards: [r(name)] });
const camp = (id, name, game, c, drops, o = {}) => ({ id, name, game, box_art_url: img(game, c), ends_at: inD(2), linked: true, maybe_unlinked: false, link_url: "https://link.example", allowed_channels: [], minutes_needed: 108, verdict: "plenty", pinned: false, ends_before_turn: false, new: false, starts_at: inD(-1), priority: false, drops, ...o });
const cur = camp("c1", "Open Series Cup #3", "Battlefield REDSEC", "#1d3a52", [drop("a", 120, 120, true, "Dog Tag: Iron Wolf"), drop("b", 360, 252, false, "Cold Blooded"), drop("c", 480, 252, false, "Weapon Charm: Ember")]);
const un = [camp("c2", "OWCS Stage 3 Playoffs", "Overwatch 2", "#7a3d12", [drop("d", 60, 15, false, "Esports Loot Box")], { minutes_needed: 45 }),
  camp("c3", "ALGS S2 Playoffs D4", "Apex Legends", "#6e1a1a", [drop("e", 30, 15, false, "APEX Pack")], { minutes_needed: 15, new: true }),
  camp("c4", "nopixel V", "Grand Theft Auto V", "#1f4d2b", [drop("f", 240, 0, false, "Pegassi Tempesta")], { minutes_needed: 240 })];
un.push(camp("c5", "An Extremely Long Campaign Name Championship Finals Presented By Somebody Season 12", "A Game With A Really Very Long Title Indeed", "#5a2d14", [drop("l", 90, 10, false, "A reward with a long name that has to wrap somewhere")], { ends_before_turn: true, new: true }));
const needs = [camp("n1", "ERCC S12 Semi Day 1", "Eternal Return", "#2c2f6b", [drop("g", 120, 0, false, "Nadine Skin")], { linked: false }), camp("n2", "Halloween 2026", "The Other Side", "#3b2a52", [drop("h", 60, 0, false, "Pumpkin Lantern")], { linked: false })];
const up = [camp("u1", "Season 4 Launch", "Marvel Rivals", "#5a1446", [drop("i", 60, 0, false, "Skin")], { starts_at: inD(3) }), camp("u2", "ERCC S12 Finals", "Eternal Return", "#2c2f6b", [drop("j", 60, 0, false, "Coins")], { starts_at: inD(4), linked: false })];
const state = { state: "mining", signed_in: true, login: "viewer", build: "preview", paused_until: null, last_refresh: inD(0), first_in_line: [], full_list_lost: false, priority_only: true, signin_kind: "android",
  current: { campaign: cur, channel: { login: "itzmaxiq", viewers: 4210, favourite: true }, reason: "priority 1", channel_reason: "favourite", also_credited: [], channels: [{ login: "zbra", viewers: 300, favourite: false }] },
  forecast: { missed: 2, finishes_at: inD(1.5), waiting: ["A Campaign With Nobody Live Right Now"], steps: [
    { campaign_id: "c1", name: cur.name, game: cur.game, box_art_url: cur.box_art_url, starts_at: inD(-0.001), finishes_at: inD(0.2), status: "ok", rewards_earned: 2, missed: [], alongside: false },
    { campaign_id: "c2", name: un[0].name, game: un[0].game, box_art_url: un[0].box_art_url, starts_at: inD(0.2), finishes_at: inD(0.3), status: "partial", rewards_earned: 1, missed: ["Esports Loot Box"], alongside: false },
    { campaign_id: "c5", name: un[3].name, game: un[3].game, box_art_url: un[3].box_art_url, starts_at: inD(0.3), finishes_at: inD(1.5), status: "miss", rewards_earned: 0, missed: ["A reward with a long name that has to wrap somewhere"], alongside: false },
  ] },
  needs_you: needs, needs_ignored: [], up_next: un, done: [], never: [], outside: [], too_late: [], upcoming: up };
const claim = (dd, name, campaign, game) => ({ at: inD(dd), campaign_id: campaign, campaign, game, rewards: [r(name)], box_art_url: img(game), minutes: 60, channel: "zbra", campaign_rewards: 3, campaign_ends: inD(2) });
const history = { total_rewards: 7, points: { points: 41200, chests: 14 }, claims: [claim(-.1, "APEX Pack", "ALGS S2 PO D3", "Apex Legends"), claim(-.2, "Esports Loot Box", "OWCS Stage 3", "Overwatch 2"), claim(-.3, "Grotti Turismo", "nopixel V", "GTA V"), claim(-1.2, "Hazmat Skin", "Rust 41", "Rust"), claim(-2.2, "Esports Loot Box", "OWCS Stage 3", "Overwatch 2"), claim(-4.2, "Cold Blooded", "Open Series #2", "Battlefield REDSEC"), claim(-5.2, "Loot", "OWCS Stage 3", "Overwatch 2")],
  missed: [{ campaign_id: "m1", name: "Halloween 2025", game: "The Other Side", reason: "not_linked", started: true, priority: true, pinned: false, minutes_watched: 20, rewards: [{ ...r("Lantern"), claimed: false }], rewards_claimed: 0, rewards_total: 1, ends_at: inD(-1.5), link_url: "https://link.example", box_art_url: img("The Other Side") }] };
const invC = (c, status, extra = {}) => ({ ...c, status, badge: false, will_mine: true, ...extra });
const inventory = { mine_badges: false, games: [
  { game: "Battlefield REDSEC", box_art_url: cur.box_art_url, priority: 1, never: false, claimed_earlier: [], campaigns: [invC(cur, "mining")] },
  { game: "Overwatch 2", box_art_url: un[0].box_art_url, priority: 2, never: false, claimed_earlier: [], campaigns: [invC(un[0], "active")] },
  { game: "Eternal Return", box_art_url: needs[0].box_art_url, priority: null, never: false, claimed_earlier: [], campaigns: [invC(needs[0], "needs_link")] },
  { game: "Apex Legends", box_art_url: un[1].box_art_url, priority: null, never: false, claimed_earlier: [], campaigns: [invC(un[1], "active")] }] };
const settings = { priority_only: true, mine_badges: false, skip_too_late: true, campaigns_every_minutes: 60, claim_points: true, points_watch_streak: true, arrange_up_next: false, notify_weekly: true };
const routes = { "/api/me": { authenticated: true, setup_required: false }, "/api/state": state, "/api/history": history, "/api/inventory": inventory, "/api/settings": settings, "/api/pins": { pins: [] },
  "/api/lists": { priority: ["Battlefield REDSEC", "Overwatch 2", "Apex Legends", "Eternal Return", "WARDOGS"], never: ["Fortnite", "World of Tanks"], favourites: ["itzmaxiq", "zbra"] },
  "/api/suggestions": { games: ["Rust"], channels: [{ login: "itzmaxiq", live: true, game: "Battlefield REDSEC", last_seen: null }], known_games: [] },
  "/api/activity": { kept_days: 7, events: [{ at: inD(-.01), kind: "claimed", data: { reward: "APEX Pack", campaign: "ALGS", game: "Apex Legends" } }, { at: inD(-.05), kind: "switched", data: { to: "itzmaxiq", from: "zbra", from_live: false, game: "Battlefield REDSEC" } }, { at: inD(-.1), kind: "points_earned", data: { points: 50, channel: "zbra" } }, { at: inD(-1.1), kind: "needs_you", data: { campaign: "Halloween 2026" } }, { at: inD(-1.2), kind: "checked", data: { campaigns: 65, seconds: 3 } }] },
  "/api/about": { version: "0.3.0", commit: "preview", started_at: inD(-1), campaigns_at: inD(0), server_tz: "UTC" }, "/api/notify/channels": { channels: [{ type: "discord", name: "Discord", configured: true, summary: "webhook set", fields: [], hint: "" }], available: [] }, "/api/sessions": { sessions: [{ id: "s", device: "Chrome on Windows", current: true, last_seen_at: inD(0) }] }, "/api/widget/key": { exists: false }, "/api/twitch/browser": { available: true, status: "idle", message: "" } };
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".webmanifest": "application/json" };
createServer((q, s) => {
  const u = new URL(q.url, "http://x");
  if (u.pathname.startsWith("/img/")) { s.setHeader("content-type", "image/svg+xml"); return s.end(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 4"><rect width="3" height="4" fill="${u.searchParams.get("c") || "#333"}"/></svg>`); }
  if (u.pathname === "/api/events") { s.setHeader("content-type", "text/event-stream"); s.flushHeaders(); return; }
  if (u.pathname.startsWith("/api/")) { const b = routes[u.pathname]; s.statusCode = b ? 200 : 404; s.setHeader("content-type", "application/json"); return s.end(JSON.stringify(b ?? { detail: "nf" })); }
  const f = join(dist, u.pathname === "/" ? "index.html" : u.pathname);
  if (!existsSync(f)) { s.statusCode = 404; return s.end(); }
  s.setHeader("content-type", types[extname(f)] ?? "application/octet-stream"); s.end(readFileSync(f));
}).listen(4177);
