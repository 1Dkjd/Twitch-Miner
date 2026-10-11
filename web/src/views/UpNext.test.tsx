import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { State } from "../api/client";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { campaign, state } from "../test/fixtures";
import { OverviewView } from "./Overview";

const ME = { authenticated: true, setup_required: false };
const LISTS = { priority: [], never: [], favourites: [] };
const q = (id: string, name: string, game: string, over = {}) => campaign({ id, name, game, minutes_needed: 60, ...over });
const QUEUE = [
  q("a", "CONTROL Resonant launch", "CONTROL Resonant"), q("b", "Dragon's Dogma 2 - DA", "Dragon's Dogma II"),
  q("c", "Rematch x Blue Lock", "REMATCH"), q("d", "Dragonfire 6 - #6/7", "Albion Online", { ends_before_turn: true, ends_at: "2026-10-11T09:29:00Z" }),
  q("e", "Vaultbreakers", "Vaultbreakers"), q("f", "S7 Launch Drops", "Arena Breakout: Infinite"),
];

function setup(s: Partial<State> = {}, settings = { arrange_up_next: false }, pins: string[] = []) {
  let current = { ...settings };
  let pinned = [...pins];
  const calls = mockApi({
    "GET /api/state": state({ up_next: QUEUE, ...s }), "GET /api/lists": LISTS,
    "GET /api/settings": () => current,
    "PUT /api/settings": (b: object) => (current = { ...current, ...b }),
    "GET /api/pins": () => ({ pins: pinned }),
    "PUT /api/pins": (b: { pins: string[] }) => ({ pins: (pinned = b.pins) }),
  });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  render(<AppProvider initialMe={ME}><OverviewView /></AppProvider>);
  return calls;
}
afterEach(() => vi.unstubAllGlobals());
const upNext = async () => (await screen.findByRole("heading", { name: "Up next" })).closest("section") as HTMLElement;
const titles = (sec: HTMLElement) => [...sec.querySelectorAll(".row-t")].map((e) => e.textContent);

test("the filter searches every queued campaign, by game or name", async () => {
  setup();
  const u = userEvent.setup();
  const sec = await upNext();
  expect(titles(sec)).toHaveLength(5); // the next five, as before
  await u.type(within(sec).getByRole("searchbox", { name: "Filter Up next" }), "dragon");
  expect(titles(sec)).toEqual(["Dragon's Dogma 2 - DA", "Dragonfire 6 - #6/7"]);
  expect(within(sec).getByText("2 of 6")).toBeInTheDocument();
  await u.clear(within(sec).getByRole("searchbox", { name: "Filter Up next" }));
  await u.type(within(sec).getByRole("searchbox", { name: "Filter Up next" }), "arena");
  expect(titles(sec)).toEqual(["S7 Launch Drops"]); // found beyond the first five
  await u.type(within(sec).getByRole("searchbox", { name: "Filter Up next" }), "zzz");
  expect(within(sec).getByText(/Nothing in Up next matches/)).toBeInTheDocument();
});

test("a campaign that would end before its turn says so; the others say nothing", async () => {
  setup();
  const sec = await upNext();
  const late = within(sec).getByText("Dragonfire 6 - #6/7").closest(".row") as HTMLElement;
  expect(within(late).getByText(/before its turn/)).toHaveClass("chip", "red");
  expect(sec.querySelectorAll(".chip.red")).toHaveLength(1);
});

test("campaigns Dropwatch first saw in the last day are marked New", async () => {
  setup({ up_next: [q("n1", "CONTROL Resonant launch", "CONTROL Resonant", { new: true }), q("o1", "Old one", "Palia")] });
  const sec = await upNext();
  const fresh = within(sec).getByText("CONTROL Resonant launch").closest(".row") as HTMLElement;
  expect(within(fresh).getByText("New")).toHaveClass("chip", "note");
  expect(sec.querySelectorAll(".chip.note")).toHaveLength(1);
});

test("Arrange myself: switch it on, pin, move and unpin", async () => {
  const calls = setup();
  const u = userEvent.setup();
  const sec = await upNext();
  expect(within(sec).queryByRole("button", { name: /Pin .* to the top/ })).toBeNull();
  await u.click(within(sec).getByRole("switch", { name: "Arrange myself" }));
  await waitFor(() => expect(calls.find((c) => c.path === "/api/settings" && c.method === "PUT")?.body).toEqual({ arrange_up_next: true }));
  await u.click(await within(sec).findByRole("button", { name: "Pin Vaultbreakers to the top" }));
  await waitFor(() => expect(calls.filter((c) => c.path === "/api/pins" && c.method === "PUT").at(-1)?.body).toEqual({ pins: ["e"] }));
  await u.click(within(sec).getByRole("button", { name: "Pin Rematch x Blue Lock to the top" }));
  await waitFor(() => expect(calls.filter((c) => c.path === "/api/pins" && c.method === "PUT").at(-1)?.body).toEqual({ pins: ["e", "c"] }));
});

test("pinned rows come first with move and unpin controls", async () => {
  const pinnedQueue = [{ ...QUEUE[4]!, pinned: true }, { ...QUEUE[2]!, pinned: true }, ...QUEUE.filter((c) => !["e", "c"].includes(c.id))];
  const calls = setup({ up_next: pinnedQueue }, { arrange_up_next: true }, ["e", "c"]);
  const u = userEvent.setup();
  const sec = await upNext();
  expect(await within(sec).findByText(/Pinned · mined first, in your order/)).toBeInTheDocument();
  expect(within(sec).getByText(/Then automatic · most urgent first/)).toBeInTheDocument();
  await u.click(within(sec).getByRole("button", { name: "Move Rematch x Blue Lock up" }));
  await waitFor(() => expect(calls.filter((c) => c.path === "/api/pins" && c.method === "PUT").at(-1)?.body).toEqual({ pins: ["c", "e"] }));
  await u.click(within(sec).getByRole("button", { name: "Unpin Vaultbreakers" }));
  await waitFor(() => expect(calls.filter((c) => c.path === "/api/pins" && c.method === "PUT").at(-1)?.body).toEqual({ pins: ["c"] }));
});

test("moving a pin works on the pins you can see, keeping one you can't (the one being mined) in place", async () => {
  // "now" is pinned and being mined, so it isn't in Up next; Vaultbreakers (e) and Rematch (c) are shown
  const pinnedQueue = [{ ...QUEUE[4]!, pinned: true }, { ...QUEUE[2]!, pinned: true }, ...QUEUE.filter((c) => !["e", "c"].includes(c.id))];
  const calls = setup({ up_next: pinnedQueue }, { arrange_up_next: true }, ["now", "e", "c"]);
  const u = userEvent.setup();
  const sec = await upNext();
  await waitFor(() => expect(within(sec).getByRole("button", { name: "Move Vaultbreakers up" })).toBeDisabled());
  await u.click(within(sec).getByRole("button", { name: "Move Rematch x Blue Lock up" }));
  await waitFor(() => expect(calls.filter((c) => c.path === "/api/pins" && c.method === "PUT").at(-1)?.body)
    .toEqual({ pins: ["now", "c", "e"] }));
});

test("Add to Priority puts the game at the end of Priority, and isn't offered for games already there", async () => {
  const calls = mockApi({
    "GET /api/state": state({ up_next: QUEUE }), "GET /api/settings": { arrange_up_next: false }, "GET /api/pins": { pins: [] },
    "GET /api/lists": { priority: ["Palia", "REMATCH"], never: ["Albion Online"], favourites: [] },
    "PUT /api/lists": (b: unknown) => b,
  });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  render(<AppProvider initialMe={ME}><OverviewView /></AppProvider>);
  const u = userEvent.setup();
  const sec = await upNext();
  await waitFor(() => expect(within(sec).queryByRole("button", { name: "Add REMATCH to Priority" })).toBeNull());
  await u.click(within(sec).getByRole("button", { name: "Add CONTROL Resonant to Priority" }));
  await waitFor(() => expect(calls.find((c) => c.path === "/api/lists" && c.method === "PUT")?.body)
    .toEqual({ priority: ["Palia", "REMATCH", "CONTROL Resonant"], never: ["Albion Online"], favourites: [] }));
});
