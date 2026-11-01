/* Pre-Docker QoL (asked for 2026-10-11): visible confirmations with Undo, the update notice, points in
 * History, finish time and tab title, signed-in browsers. */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { titleFor, UpdateNotice } from "./App";
import { AppProvider, Toasts, useApp } from "./store";
import { mockApi } from "./test/fetch";
import { campaign, state } from "./test/fixtures";
import { HistoryView } from "./views/History";
import { OverviewView } from "./views/Overview";
import { SettingsView } from "./views/Settings";

const ME = { authenticated: true, setup_required: false };
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

// The toast itself (title, detail, Undo, timing) is covered in toast.test.tsx.

test("Undo reverses only its own change, on the lists as they are now", async () => {
  // review fix: Undo re-saved a snapshot from before, wiping anything changed in between
  let server = { priority: ["Palia"], never: [] as string[], favourites: [] as string[] };
  const calls = mockApi({ "GET /api/state": state(), "GET /api/lists": () => server,
    "PUT /api/lists": (b: unknown) => { server = b as typeof server; return b; } });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  render(<AppProvider initialMe={ME}><OverviewView /><Toasts /></AppProvider>);
  const row = (await screen.findAllByRole("button", { name: /^More actions for / }))[0]!.closest(".row") as HTMLElement;
  await userEvent.click(within(row).getByRole("button", { name: /^More actions for / }));
  await userEvent.click(within(row).getByRole("menuitem", { name: "Never mine" }));
  await waitFor(() => expect(server.never).toHaveLength(1));
  const game = server.never[0]!;
  server = { ...server, favourites: ["newfav"] };  // changed elsewhere meanwhile
  const toast = await screen.findByRole("group", { name: "Moved to Never" });
  expect(toast).toHaveTextContent(`${game} won't be mined.`);
  await userEvent.click(within(toast).getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(server.never).not.toContain(game));
  expect(await screen.findByRole("group", { name: "Undone" })).toHaveTextContent(`${game} can be mined again.`);
  expect(server.favourites).toEqual(["newfav"]);
  expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2);
});

test("a new build behind the page offers a reload", async () => {
  let build = "0.1.0+main@aaaaaaa";
  mockApi({ "GET /api/state": () => state({ build }) });
  function Refresher() { const { refreshState } = useApp(); return <button type="button" onClick={() => void refreshState()}>refresh</button>; }
  render(<AppProvider initialMe={ME}><Refresher /><UpdateNotice /></AppProvider>);
  await userEvent.click(screen.getByRole("button", { name: "refresh" }));
  expect(screen.queryByText(/Dropwatch was updated/)).not.toBeInTheDocument();
  build = "0.1.0+main@bbbbbbb";
  await userEvent.click(screen.getByRole("button", { name: "refresh" }));
  expect(await screen.findByText(/Dropwatch was updated/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
});

test("History counts channel points for the period", async () => {
  mockApi({ "GET /api/state": state(), "GET /api/history": { total_rewards: 1, missed: [], points: { points: 1230, chests: 12 },
    claims: [{ at: "2026-10-10T15:00:00Z", campaign_id: "c1", campaign: "C", game: "Palia", rewards: [{ name: "x", image_url: "u" }] }] } });
  render(<AppProvider initialMe={ME}><HistoryView /></AppProvider>);
  const stats = await screen.findByRole("region", { name: "Last 30 days" });
  expect(within(stats).getByText("channel points").previousSibling).toHaveTextContent("1,230");
  expect(within(stats).getByText(/12 chests/)).toBeInTheDocument();
});

test("the tab title carries progress while mining, and the view otherwise", () => {
  // review fix: drops count the same watch time, so progress is the furthest drop, not the sum (fixture: 22 of 360)
  const s = state();
  expect(titleFor(s, "Overview")).toBe(`22/360 min · ${s.current!.campaign.name} · Dropwatch`);
  expect(titleFor(state({ current: null }), "History")).toBe("History · Dropwatch");
  expect(titleFor(state({ state: "paused" }), "History")).toBe("History · Dropwatch"); // not mining
});

test("the next reward says when, not just how long", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  mockApi({ "GET /api/state": state(), "GET /api/lists": { priority: [], never: [], favourites: [] } });
  render(<AppProvider initialMe={ME}><OverviewView /></AppProvider>);
  expect(await screen.findByText(/Next reward in .* \(~\d{1,2}:\d\d(\s?[AP]M)?\)/)).toBeInTheDocument();
});

test("Settings lists the signed-in browsers and signs the others out", async () => {
  const sessions = { sessions: [
    { id: "aaaa", device: "Chrome on Windows", created_at: "2026-10-10T20:00:00Z", last_seen_at: new Date().toISOString(), current: true },
    { id: "bbbb", device: "Safari on iPhone", created_at: "2026-10-09T20:00:00Z", last_seen_at: "2026-10-10T08:00:00Z", current: false },
  ] };
  const calls = mockApi({ "GET /api/state": state(), "GET /api/settings": {}, "GET /api/sessions": sessions,
    "POST /api/sessions/sign-out-others": undefined, "DELETE /api/sessions/bbbb": undefined });
  location.hash = "#settings/account";
  render(<AppProvider initialMe={ME}><SettingsView /></AppProvider>);
  const list = await screen.findByRole("list", { name: "Signed-in browsers" });
  expect(within(list).getByText("Chrome on Windows")).toBeInTheDocument();
  expect(within(list).getByText("This browser")).toBeInTheDocument();
  await act(async () => { await userEvent.click(within(list).getByRole("button", { name: "Sign out Safari on iPhone" })); });
  expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/sessions/bbbb")).toBe(true);
  await act(async () => { await userEvent.click(screen.getByRole("button", { name: "Sign out everywhere else" })); });
  expect(calls.some((c) => c.path === "/api/sessions/sign-out-others")).toBe(true);
});

test("a single campaign fixture is fine for the title helper", () => {
  expect(titleFor(state({ current: { ...state().current!, campaign: campaign({ id: "z", name: "Z" }) } }), "Overview")).toContain("Z");
});
