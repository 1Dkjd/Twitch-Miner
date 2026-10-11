import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ActivityEvent } from "../api/client";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { state } from "../test/fixtures";
import { ActivityView, describe } from "./Activity";

const ev = (at: string, kind: string, data: ActivityEvent["data"] = {}): ActivityEvent => ({ at, kind, data });
// newest first, as the API sends them
const EVENTS = [
  ev("2026-10-10T19:00:00Z", "state", { state: "mining" }),
  ev("2026-10-10T18:59:59Z", "switched", { from: "hekimae", to: "theburntpeanut", game: "Escape from Tarkov",
    campaign: "EXFIL Brothers Day 2", reason: "you pinned it", from_live: true }),
  ev("2026-10-10T18:45:00Z", "points_claimed", { channel: "lvndmark" }),
  ev("2026-10-10T18:21:00Z", "claimed", { campaign: "Frozen Trail", reward: "Oxygen Respirator", game: "ARC Raiders" }),
  ev("2026-10-10T17:52:00Z", "state", { state: "twitch_unreachable", error: "ClientConnectorError" }),
  ev("2026-10-10T17:40:00Z", "notified", { title: "Dropwatch: Twitch sign-in stopped working", sent: ["ntfy"], failed: [] }),
  ev("2026-10-10T17:34:00Z", "switched", { from: "bayzex", to: "theburntpeanut", from_live: false }),
  ev("2026-10-10T17:30:00Z", "debug_dump", {}),
];

function setup() {
  mockApi({ "GET /api/state": state(), "GET /api/activity": { events: EVENTS, kept_days: 7 } });
  render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}><ActivityView /></AppProvider>);
}
const sentences = () => [...document.querySelectorAll(".act .s")].map((e) => e.textContent);

test("events read as sentences with their reasons, newest first", async () => {
  setup();
  expect(await screen.findByText("Kept for 7 days.")).toBeInTheDocument();
  expect(sentences()).toEqual([
    "Switched to theburntpeanut from hekimae",
    "Opened a channel points chest on lvndmark",
    "Claimed Oxygen Respirator from Frozen Trail",
    "Couldn't reach Twitch",
    "Sent “Twitch sign-in stopped working” to ntfy",
    "Switched to theburntpeanut from bayzex",
  ]);
  const first = screen.getByText(/from hekimae/).closest(".act") as HTMLElement;
  expect(within(first).getByText("Pinned in Up next · Escape from Tarkov · EXFIL Brothers Day 2")).toBeInTheDocument();
  expect(screen.getByText("bayzex went offline")).toBeInTheDocument();
  expect(screen.getByText("ClientConnectorError")).toBeInTheDocument();
  vi.unstubAllGlobals();
});

const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed");
const CHECK = ev("2026-10-10T18:50:00Z", "checked", { manual: true, campaigns: 143, new: 0, linked: [], seconds: 4.8 });

test("every kind starts on; turning kinds off hides only those, and All brings everything back", async () => {
  try { localStorage.clear(); } catch { /* none */ }
  mockApi({ "GET /api/state": state(), "GET /api/activity": { events: [CHECK, ...EVENTS], kept_days: 7 } });
  render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}><ActivityView /></AppProvider>);
  await screen.findByText("Kept for 7 days.");
  for (const k of ["All", "Mining", "Twitch", "Rewards", "Problems", "Notifications"]) expect(pressed(k)).toBe("true");
  expect(sentences()).toContain("You checked Twitch");
  await userEvent.click(screen.getByRole("button", { name: "Mining" }));
  await userEvent.click(screen.getByRole("button", { name: "Twitch" }));
  expect(pressed("Mining")).toBe("false");
  expect(pressed("All")).toBe("false");
  expect(sentences()).toEqual([
    "Opened a channel points chest on lvndmark",
    "Claimed Oxygen Respirator from Frozen Trail",
    "Couldn't reach Twitch",
    "Sent “Twitch sign-in stopped working” to ntfy",
  ]);
  await userEvent.click(screen.getByRole("button", { name: "Twitch" }));  // back on
  expect(sentences()[0]).toBe("You checked Twitch");
  await userEvent.click(screen.getByRole("button", { name: "All" }));
  expect(pressed("Mining")).toBe("true");
  expect(sentences()).toHaveLength(7);
  vi.unstubAllGlobals();
});

test("the choice is remembered in this browser, and turning everything off says so", async () => {
  try { localStorage.clear(); } catch { /* none */ }
  const show = () => {
    mockApi({ "GET /api/state": state(), "GET /api/activity": { events: [CHECK, ...EVENTS], kept_days: 7 } });
    return render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}><ActivityView /></AppProvider>);
  };
  const first = show();
  await screen.findByText("Kept for 7 days.");
  await userEvent.click(screen.getByRole("button", { name: "Twitch" }));
  first.unmount();
  show();
  await screen.findByText("Kept for 7 days.");
  expect(pressed("Twitch")).toBe("false");
  expect(sentences()).not.toContain("You checked Twitch");
  for (const k of ["Mining", "Rewards", "Problems", "Notifications"]) await userEvent.click(screen.getByRole("button", { name: k }));
  expect(screen.getByText("Turn on at least one kind to see activity.")).toBeInTheDocument();
  vi.unstubAllGlobals();
});

test("mining after a switch says nothing new; mining after a problem says 'again'", () => {
  const mining = ev("2026-10-10T19:00:00Z", "state", { state: "mining" });
  expect(describe(mining, ev("2026-10-10T18:59:00Z", "switched", { from: "a", to: "b" }))).toBeNull();
  expect(describe(mining, ev("2026-10-10T18:00:00Z", "state", { state: "twitch_unreachable" }))?.text).toBe("Mining again");
  const idle = ev("2026-10-10T19:00:00Z", "state", { state: "idle" });
  expect(describe(idle, ev("2026-10-10T18:00:00Z", "state", { state: "idle" }))).toBeNull(); // no repeats
});

test("a notification no channel took is a problem line", () => {
  const line = describe(ev("2026-10-10T19:00:00Z", "notified", { title: "Dropwatch: Your week", sent: [], failed: ["Discord"] }), undefined);
  expect(line?.tone).toBe("bad");
  expect(line?.d).toBe("Tried Discord");
});

test("check-ins read as clicked or automatic, with what they found", () => {
  const clicked = describe(ev("2026-10-10T23:02:51Z", "checked", { manual: true, campaigns: 143, new: 2, linked: ["Riders Republic"], seconds: 1.3 }), undefined);
  expect(clicked?.text).toBe("You checked Twitch");
  expect(clicked?.d).toBe("143 campaigns · 2 new · Riders Republic now linked · took 1.3 s");
  expect(clicked?.group).toBe("twitch");
  const auto = describe(ev("2026-10-10T22:01:00Z", "checked", { manual: false, campaigns: 143, new: 0, linked: [], seconds: 0.9 }), undefined);
  expect(auto?.text).toBe("Checked Twitch for campaign changes");
  expect(auto?.d).toBe("143 campaigns · took 0.9 s");
});

test("watch-streak visits and streak points have their own lines", () => {
  const visit = describe(ev("2026-10-11T06:00:00Z", "switched", { from: "a", to: "favchan", reason: "watch streak", game: "Just Chatting", from_live: true }), undefined);
  expect(visit?.d).toBe("Watch-streak visit to a favourite · Just Chatting");
  const earned = describe(ev("2026-10-11T06:04:00Z", "points_earned", { channel: "favchan", reason: "WATCH_STREAK", points: 350 }), undefined);
  expect(earned?.text).toBe("Earned 350 watch-streak points on favchan");
  expect(earned?.group).toBe("rewards");
});
