/* Priority-only mining on the page (approved 2026-10-12, docs/design/priority-only-mockup.html). */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { State } from "../api/client";
import { AppProvider, Toasts } from "../store";
import { mockApi } from "../test/fetch";
import { campaign, state } from "../test/fixtures";
import { OverviewView } from "./Overview";
import { PrioritiesView } from "./Priorities";
import { SettingsView } from "./Settings";

const ME = { authenticated: true, setup_required: false };
const PRIO = ["Palia", "Phasmophobia", "AION 2", "ARC Raiders", "Riders Republic"];
const ALBION = campaign({ id: "a1", name: "AOCP Flamescale 5", game: "Albion Online" });
const KIRKA = campaign({ id: "k1", name: "Kirka Drops", game: "Kirka.io" });
afterEach(() => vi.unstubAllGlobals());

function overview(s: State, extra: Record<string, unknown> = {}) {
  const calls = mockApi({ "GET /api/state": s, "GET /api/lists": { priority: PRIO, never: [], favourites: [] },
    "GET /api/settings": { arrange_up_next: false }, "GET /api/pins": { pins: [] }, ...extra });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  render(<AppProvider initialMe={ME}><OverviewView /><Toasts /></AppProvider>);
  return calls;
}
const idleNone = () => state({ current: null, up_next: [], needs_you: [], priority_only: true, outside: [ALBION, KIRKA],
  first_in_line: [] });

test("with nothing to mine in the Priority games, it says so and names them", async () => {
  overview(idleNone());
  expect(await screen.findByRole("heading", { name: "Nothing to mine in your Priority games" })).toBeInTheDocument();
  expect(await screen.findByText(/Palia, Phasmophobia, AION 2, ARC Raiders and Riders Republic have nothing Dropwatch can mine/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Edit Priority" })).toBeInTheDocument();
});

test("with a Priority campaign but nobody live, it waits for one", async () => {
  overview(state({ current: null, up_next: [], priority_only: true, outside: [ALBION], first_in_line: ["Frights & Delights"] }));
  expect(await screen.findByRole("heading", { name: "Waiting for a Priority game to go live" })).toBeInTheDocument();
  expect(screen.getByText(/Frights & Delights is first in line/)).toBeInTheDocument();
});

test("Turn off Priority only saves it, with Undo", async () => {
  const calls = overview(idleNone(), { "PUT /api/settings": (b: object) => b });
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Turn off Priority only" }));
  await waitFor(() => expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({ priority_only: false }));
  const toast = await screen.findByRole("group", { name: "Priority only is off" });
  await u.click(within(toast).getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({ priority_only: true }));
});

test("games outside Priority are folded away; Show lists them without Mine now", async () => {
  overview(idleNone());
  const u = userEvent.setup();
  const sec = (await screen.findByRole("heading", { name: "Up next" })).closest("section") as HTMLElement;
  expect(within(sec).queryByRole("switch", { name: "Arrange myself" })).not.toBeInTheDocument();
  expect(within(sec).queryByText("AOCP Flamescale 5")).not.toBeInTheDocument();
  const show = within(sec).getByRole("button", { name: "Not mined: 2 campaigns outside Priority · Show" });
  expect(show).toHaveAttribute("aria-expanded", "false");
  await u.click(show);
  expect(within(sec).getByText("AOCP Flamescale 5")).toBeInTheDocument();
  expect(within(sec).getByRole("button", { name: "Add Albion Online to Priority" })).toBeInTheDocument();
  expect(within(sec).getByRole("button", { name: "Never mine Albion Online" })).toBeInTheDocument();
  expect(within(sec).queryByRole("button", { name: /^Mine .* now$/ })).not.toBeInTheDocument();
});

test("with the switch off nothing is folded", async () => {
  overview(state({ priority_only: false, outside: [] }));
  await screen.findByRole("heading", { name: "Up next" });
  expect(screen.queryByRole("button", { name: /outside Priority/ })).not.toBeInTheDocument();
});

test("Settings › Mining has the switch first, and the summary leads with Priority only", async () => {
  location.hash = "#settings/mining";
  const settings = { mine_badges: true, campaigns_every_minutes: 30, priority_only: false };
  let saved = { ...settings };
  const calls = mockApi({ "GET /api/state": state(), "GET /api/settings": () => saved,
    "PUT /api/settings": (b: object) => (saved = { ...saved, ...b }) });
  render(<AppProvider initialMe={ME}><SettingsView /></AppProvider>);
  const u = userEvent.setup();
  const sw = await screen.findByRole("checkbox", { name: "Only mine games in Priority" });
  await waitFor(() => expect(sw).toBeEnabled());
  const pane = sw.closest(".set") as HTMLElement;
  expect(pane.querySelector(".opt input")).toBe(sw);  // first in the section
  await u.click(sw);
  await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ priority_only: true }));
  await waitFor(() => expect(screen.getByRole("link", { name: /^Mining/ })).toHaveTextContent("Priority only · badges on · every 30 min"));
});

/* Review fixes (2026-10-12). */
test("with Arrange myself already on, Priority only still shows the normal list (pins don't count then)", async () => {
  const palia = campaign({ id: "p1", name: "Frights & Delights", game: "Palia", pinned: true });
  overview(state({ priority_only: true, up_next: [palia], outside: [] }),
    { "GET /api/settings": { arrange_up_next: true }, "GET /api/pins": { pins: ["p1"] } });
  const sec = (await screen.findByRole("heading", { name: "Up next" })).closest("section") as HTMLElement;
  expect(await within(sec).findByRole("button", { name: "Mine Frights & Delights now" })).toBeInTheDocument();
  expect(within(sec).queryByRole("button", { name: /^Unpin/ })).not.toBeInTheDocument();
  expect(within(sec).queryByText(/Pinned · mined first/)).not.toBeInTheDocument();
});

test("before the Priority list has loaded, the card doesn't claim it's empty", async () => {
  // no /api/lists route: the request fails, so the lists never load (useLists keeps them null)
  mockApi({ "GET /api/state": idleNone(),
    "GET /api/settings": { arrange_up_next: false }, "GET /api/pins": { pins: [] } });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  render(<AppProvider initialMe={ME}><OverviewView /></AppProvider>);
  await screen.findByRole("heading", { name: /Priority/, level: 2 });
  expect(screen.queryByText(/Your Priority list is empty/)).not.toBeInTheDocument();
});

test("with nothing in Up next, the header doesn't say what it starts after", async () => {
  overview(state({ priority_only: true, up_next: [], outside: [ALBION] }));
  const sec = (await screen.findByRole("heading", { name: "Up next" })).closest("section") as HTMLElement;
  expect(within(sec).queryByText(/Starts when/)).not.toBeInTheDocument();
  expect(within(sec).getByText("Priority only is on")).toBeInTheDocument();
});

test("Priorities has the Priority only switch and it saves the setting", async () => {
  const calls = mockApi({ "GET /api/state": state({ priority_only: false }), "GET /api/lists": { priority: [], never: [], favourites: [] }, "PUT /api/settings": {} });
  render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}><PrioritiesView /></AppProvider>);
  const sw = await screen.findByRole("switch", { name: "Priority only" });
  await waitFor(() => expect(sw).toBeEnabled());
  await userEvent.click(sw);
  await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === "/api/settings" && (c.body as { priority_only: boolean }).priority_only)).toBe(true));
});
