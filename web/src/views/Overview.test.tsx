import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { State } from "../api/client";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { state } from "../test/fixtures";
import { OverviewView } from "./Overview";

const ME = { authenticated: true, setup_required: false };
const LISTS = { priority: ["Phasmophobia"], never: [], favourites: ["example_streamer"] };

function setup(s: State, extra: Record<string, unknown> = {}) {
  const calls = mockApi({ "GET /api/state": s, "GET /api/lists": LISTS, ...extra });
  render(<AppProvider initialMe={ME}><OverviewView /></AppProvider>);
  return calls;
}
function setPhone(phone: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: phone && q.includes("720"), addEventListener() {}, removeEventListener() {} }));
}
afterEach(() => vi.unstubAllGlobals());

test("Mining now shows the campaign, channel, favourite mark, next reward and deadline", async () => {
  setPhone(false);
  setup(state());
  const card = await screen.findByRole("article");
  expect(within(card).getByRole("heading", { level: 2 })).toHaveTextContent("Frights & Delights");
  expect(card.querySelector(".now-facts")).toHaveTextContent("GamePaliaChannelexample_streamer");
  expect(within(card).getByText("Most urgent")).toHaveClass("chip");
  expect(within(card).getByText("favourite")).toBeInTheDocument();
  expect(card).toHaveTextContent("Next reward in 38 min"); // jest-dom folds the non-breaking space
  expect(card.textContent).toContain("38 min"); // spec §11: numbers and units never split
  expect(within(card).getByText("Plenty of time")).toBeInTheDocument();
  expect(card).toHaveTextContent("22 / 360 min watched");
});

test("Priority games say so in Up next", async () => {
  setPhone(false);
  setup(state());
  expect(await screen.findByText(/Priority 1/)).toBeInTheDocument();
});

test("Never mine on an Up next row moves its game from Priority to Never", async () => {
  setPhone(false);
  const calls = setup(state(), { "PUT /api/lists": (b: unknown) => b });
  const u = userEvent.setup();
  const row = (await screen.findByText("Crimson Eye 2026")).closest(".row") as HTMLElement;
  await u.click(within(row).getByRole("button", { name: "Never mine Phasmophobia" }));
  expect(calls.find((c) => c.path === "/api/lists" && c.method === "PUT")?.body)
    .toEqual({ priority: [], never: ["Phasmophobia"], favourites: ["example_streamer"] });
});

test("the pause menu works from the keyboard and pauses for the chosen time", async () => {
  setPhone(false);
  const calls = setup(state(), { "POST /api/pause": undefined });
  const u = userEvent.setup();
  const btn = await screen.findByRole("button", { name: "Pause" });
  await u.click(btn);
  const items = screen.getAllByRole("menuitem").filter((i) => i.closest("#pause-menu"));
  expect(items[0]).toHaveFocus();
  await u.keyboard("{ArrowDown}");
  expect(items[1]).toHaveFocus();
  await u.keyboard("{End}");
  expect(items[3]).toHaveFocus();
  await u.keyboard("{Escape}");
  expect(btn).toHaveFocus();
  expect(btn).toHaveAttribute("aria-expanded", "false");
  await u.click(btn);
  await u.keyboard("{ArrowDown}{Enter}");
  expect(calls.find((c) => c.path === "/api/pause")?.body).toEqual({ minutes: 60 });
});

test("the change link lists other live channels and switches", async () => {
  setPhone(false);
  const calls = setup(state(), { "POST /api/channel": undefined });
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Change channel" }));
  await u.click(screen.getByRole("menuitem", { name: /other_streamer/ }));
  expect(calls.find((c) => c.path === "/api/channel")?.body).toEqual({ login: "other_streamer" });
});

test("on phones Needs you comes before Mining now in the DOM", async () => {
  setPhone(true);
  setup(state());
  const needs = await screen.findByRole("heading", { name: "Needs you" });
  const now = screen.getByRole("article");
  expect(needs.compareDocumentPosition(now) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("on desktop Mining now comes first", async () => {
  setPhone(false);
  setup(state());
  const now = await screen.findByRole("article");
  const needs = screen.getByRole("heading", { name: "Needs you" });
  expect(now.compareDocumentPosition(needs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("a recent switch shows the notice until dismissed", async () => {
  setPhone(false);
  setup(state({ last_switch: { from: "example_streamer", to: "other_streamer", at: new Date().toISOString() } }));
  const notice = await screen.findByText(/Switched from/);
  expect(notice).toHaveTextContent("Switched from example_streamer to other_streamer");
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByText(/Switched from/)).not.toBeInTheDocument();
});

test("deadline verdicts map to the approved chips", async () => {
  setPhone(false);
  const s = state();
  s.current!.campaign.verdict = "wont_finish";
  setup(s);
  expect(await screen.findByText("Won't finish in time")).toHaveClass("chip", "red");
});

test("idle: first in line and Check now", async () => {
  setPhone(false);
  // while idle the miner's Up next is empty (nothing is live); first_in_line names what waits
  const calls = setup(state({ state: "idle", current: null, up_next: [], first_in_line: ["Crimson Eye 2026", "Palia Frights"],
    next_check_at: new Date(Date.now() + 4 * 60_000).toISOString() }),
    { "POST /api/refresh": undefined });
  expect(await screen.findByText("Nothing to mine right now")).toBeInTheDocument();
  expect(screen.getByText(/Crimson Eye 2026 is first in line, then Palia Frights/)).toBeInTheDocument();
  await act(async () => { await userEvent.click(screen.getByRole("button", { name: "Check now" })); });
  expect(calls.some((c) => c.path === "/api/refresh")).toBe(true);
});

test("may-need-linking rows offer a retry", async () => {
  setPhone(false);
  const s = state();
  s.needs_you[0]!.maybe_unlinked = true;
  s.needs_you[0]!.linked = null;
  setup(s);
  expect(await screen.findByText("007 First Light may need linking")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Try Extended Operations again" })).toBeInTheDocument();
});

test("signed out: the banner offers a sign-in code", async () => {
  setPhone(false);
  setup(state({ state: "signed_out" }));
  expect(await screen.findByRole("button", { name: "Get a sign-in code" })).toBeInTheDocument();
});

test("catalogue trouble shows the warning banner", async () => {
  setPhone(false);
  setup(state({ catalog: { status: "unreachable", since: new Date().toISOString() } }));
  expect(await screen.findByText(/Can't reach the campaign list since/)).toBeInTheDocument();
});

test("a Priority game says its place as a chip", async () => {
  setPhone(false);
  mockApi({ "GET /api/state": state(), "GET /api/lists": { priority: ["Palia", "AION 2", "Phasmophobia", "X"].reverse(), never: [], favourites: [] } });
  render(<AppProvider initialMe={ME}><OverviewView /></AppProvider>);
  expect(await screen.findByText("4th in Priority")).toHaveClass("chip");
});

test("ordinals", async () => {
  const { nth } = await import("./Overview");
  expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 103].map(nth)).toEqual(["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "103rd"]);
});

test("a watch-streak visit replaces the mining card and can be ended", async () => {
  setPhone(false);
  const until = new Date(Date.now() + 5 * 60_000);
  const calls = setup(state({ streak_visit: { channel: "favchan", until: until.toISOString() } }), { "POST /api/streak/end": undefined });
  expect(await screen.findByText(/for its watch streak/)).toBeInTheDocument();
  expect(screen.getByText("favchan")).toBeInTheDocument();
  expect(screen.queryByText("Change channel")).not.toBeInTheDocument();
  await act(async () => { await userEvent.click(screen.getByRole("button", { name: "Back to drops now" })); });
  expect(calls.some((c) => c.method === "POST" && c.path === "/api/streak/end")).toBe(true);
});

test("Coming up lists announced campaigns with a link button and Priority mark", async () => {
  setPhone(false);
  const { campaign, inDays } = await import("../test/fixtures");
  setup(state({ upcoming: [
    campaign({ id: "w", game: "WARDOGS", name: "Season 02", starts_at: inDays(5), ends_at: inDays(19), linked: null, priority: true }),
    campaign({ id: "a", game: "Apex Legends", name: "Split 2", starts_at: inDays(2), ends_at: inDays(16), linked: true }),
  ] }));
  const sec = (await screen.findByRole("heading", { name: "Coming up" })).closest("section")!;
  expect(sec).toHaveTextContent("WARDOGS");
  expect(within(sec).getByText("Priority")).toHaveClass("chip");
  expect(within(sec).getByRole("link", { name: /Link your WARDOGS account/ })).toBeInTheDocument();
  expect(within(sec).queryByRole("link", { name: /Link your Apex Legends account/ })).toBeNull();
  expect(within(sec).getByText("Account linked")).toBeInTheDocument();
  expect(within(sec).getByRole("button", { name: "Move Apex Legends to Priority" })).toBeInTheDocument();
  expect(within(sec).queryByRole("button", { name: "Move WARDOGS to Priority" })).toBeNull();
});

test("Coming up is hidden when nothing is announced", async () => {
  setPhone(false);
  setup(state());
  await screen.findByRole("article");
  expect(screen.queryByRole("heading", { name: "Coming up" })).toBeNull();
});

test("campaigns skipped for lack of time fold into one line under Up next, with Mine now", async () => {
  setPhone(false);
  const { campaign } = await import("../test/fixtures");
  const calls = setup(state({ too_late: [campaign({ id: "z", name: "Last Call", game: "Rust", minutes_needed: 300 })] }),
    { "POST /api/mine-now": null });
  const u = userEvent.setup();
  const fold = await screen.findByRole("button", { name: /Skipped: 1 campaign can't finish in time/ });
  expect(screen.queryByText("Last Call")).toBeNull();
  await u.click(fold);
  await u.click(screen.getByRole("button", { name: "Mine Last Call now" }));
  expect(calls.find((c) => c.path === "/api/mine-now")?.body).toEqual({ campaign_id: "z" });
});
