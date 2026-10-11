/* Pre-Docker QoL (asked for 2026-10-11): visible confirmations with Undo, the update notice, points in
 * History, finish time and tab title, signed-in browsers. */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { titleFor, UpdateNotice } from "./App";
import { AppProvider, Toast, useApp } from "./store";
import { mockApi } from "./test/fetch";
import { campaign, state } from "./test/fixtures";
import { HistoryView } from "./views/History";
import { OverviewView } from "./views/Overview";
import { SettingsView } from "./views/Settings";

const ME = { authenticated: true, setup_required: false };
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

function Sayer({ undo }: { undo?: () => void }) {
  const { say } = useApp();
  return <button type="button" onClick={() => say("Vaultbreakers moved to Never", undo)}>go</button>;
}

test("confirmations show on screen, with Undo when there's something to undo", async () => {
  mockApi({ "GET /api/state": state() });
  const undo = vi.fn();
  render(<AppProvider initialMe={ME}><Sayer undo={undo} /><Toast /></AppProvider>);
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  const toast = await screen.findByRole("status", { name: "Notice" });
  expect(toast).toHaveTextContent("Vaultbreakers moved to Never");
  await userEvent.click(within(toast).getByRole("button", { name: "Undo" }));
  expect(undo).toHaveBeenCalledOnce();
  await waitFor(() => expect(screen.queryByRole("status", { name: "Notice" })).not.toBeInTheDocument());
});

test("Never mine can be undone from its confirmation", async () => {
  const lists = { priority: ["Palia"], never: [], favourites: [] };
  const calls = mockApi({ "GET /api/state": state(), "GET /api/lists": lists, "PUT /api/lists": (b: unknown) => b });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  render(<AppProvider initialMe={ME}><OverviewView /><Toast /></AppProvider>);
  const btn = await screen.findAllByRole("button", { name: /^Never mine / });
  await userEvent.click(btn[0]!);
  const toast = await screen.findByRole("status", { name: "Notice" });
  await userEvent.click(within(toast).getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual(lists));
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
  const s = state();
  const cur = s.current!.campaign;
  const done = cur.drops.reduce((n, d) => n + d.current_minutes, 0);
  expect(titleFor(s, "Overview")).toMatch(new RegExp(`^${done}/\\d+ min · ${cur.name} · Dropwatch$`));
  expect(titleFor(state({ current: null }), "History")).toBe("History · Dropwatch");
});

test("the next reward says when, not just how long", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  mockApi({ "GET /api/state": state(), "GET /api/lists": { priority: [], never: [], favourites: [] } });
  render(<AppProvider initialMe={ME}><OverviewView /></AppProvider>);
  expect(await screen.findByText(/Next reward in .* \(~\d\d:\d\d\)/)).toBeInTheDocument();
});

test("Settings lists the signed-in browsers and signs the others out", async () => {
  const sessions = { sessions: [
    { id: "aaaa", device: "Chrome on Windows", created_at: "2026-10-10T20:00:00Z", last_seen_at: new Date().toISOString(), current: true },
    { id: "bbbb", device: "Safari on iPhone", created_at: "2026-10-09T20:00:00Z", last_seen_at: "2026-10-10T08:00:00Z", current: false },
  ] };
  const calls = mockApi({ "GET /api/state": state(), "GET /api/settings": {}, "GET /api/sessions": sessions,
    "POST /api/sessions/sign-out-others": undefined, "DELETE /api/sessions/bbbb": undefined });
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
