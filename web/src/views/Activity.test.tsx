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

test("the filter chips narrow it to one kind", async () => {
  setup();
  await screen.findByText("Kept for 7 days.");
  await userEvent.click(screen.getByRole("button", { name: "Rewards" }));
  expect(screen.getByRole("button", { name: "Rewards" })).toHaveAttribute("aria-pressed", "true");
  expect(sentences()).toEqual(["Opened a channel points chest on lvndmark", "Claimed Oxygen Respirator from Frozen Trail"]);
  await userEvent.click(screen.getByRole("button", { name: "Problems" }));
  expect(sentences()).toEqual(["Couldn't reach Twitch"]);
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
