import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { campaign, inDays, state } from "../test/fixtures";
import { InventoryView } from "./Inventory";

const ME = { authenticated: true, setup_required: false };
const drop = (id: string, req: number, cur: number, claimed: boolean, name: string, start = -1, subs = 0) =>
  ({ id, name: id, required_minutes: req, current_minutes: cur, claimed, required_subs: subs, requires: [] as string[], starts_at: inDays(start), ends_at: inDays(3),
     rewards: [{ name, image_url: "" }] });

function setup(extra: Record<string, unknown> = {}) {
  const palia = { ...campaign({ id: "c1", drops: [drop("a", 60, 60, true, "Glasses"), drop("b", 120, 30, false, "Hat")] }), status: "mining", will_mine: true };
  const wardogs = { ...campaign({ id: "w", game: "WARDOGS", name: "Season 02", starts_at: inDays(5), linked: null,
    link_url: "https://wardogs.example/link", drops: [drop("x", 240, 0, false, "Dog tag", 5)] }), status: "upcoming", will_mine: true };
  const calls = mockApi({
    ...extra,
    "GET /api/state": state(),
    "GET /api/inventory": { total_rewards: 3, claimed_rewards: 1, games: [
      { game: "WARDOGS", box_art_url: "", priority: 1, never: false, campaigns: [wardogs],
        claimed_earlier: [{ at: inDays(-40), campaign_id: "s1", campaign: "Season 01", game: "WARDOGS",
          rewards: [{ name: "Old badge", image_url: "" }], minutes: null, channel: null, campaign_rewards: null, campaign_ends: null, box_art_url: null }] },
      { game: "Palia", box_art_url: "", priority: null, never: false, campaigns: [palia], claimed_earlier: [] },
    ] },
  });
  render(<AppProvider initialMe={ME}><InventoryView /></AppProvider>);
  return calls;
}

test("rewards show claimed, progress and locked states per game", async () => {
  setup();
  const palia = (await screen.findByRole("heading", { name: "Palia" })).closest("section")!;
  expect(within(palia).getByText("Glasses").closest(".inv-item")).toHaveClass("claimed");
  expect(within(palia).getByRole("progressbar", { name: "Hat progress" })).toHaveAttribute("aria-valuenow", "25");
  expect(within(palia).getByText("Mining now")).toHaveClass("chip");
  const wd = screen.getByRole("heading", { name: "WARDOGS" }).closest("section")!;
  expect(within(wd).getByText("Priority 1")).toBeInTheDocument();
  expect(within(wd).getByText("Dog tag").closest(".inv-item")).toHaveClass("locked");
  expect(within(wd).getByRole("link", { name: /Link your WARDOGS account/ })).toBeInTheDocument();
  expect(within(wd).queryByText("Old badge")).toBeNull(); // "Claimed earlier" starts folded
  await userEvent.setup().click(within(wd).getByRole("button", { name: /Claimed earlier/ }));
  expect(within(wd).getByText("Old badge").closest(".inv-item")).toHaveClass("claimed");
  expect(screen.getByText(/of 3 rewards claimed/)).toBeInTheDocument();
});

test("Still to earn hides claimed history; the filter box narrows by game", async () => {
  setup();
  const u = userEvent.setup();
  await screen.findByRole("heading", { name: "Palia" });
  await u.click(screen.getByRole("button", { name: "Still to earn" }));
  expect(screen.queryByText("Old badge")).toBeNull();
  await u.type(screen.getByRole("searchbox", { name: "Filter Inventory" }), "pal");
  expect(screen.queryByRole("heading", { name: "WARDOGS" })).toBeNull();
  expect(screen.getByRole("heading", { name: "Palia" })).toBeInTheDocument();
});

test("Never games are hidden until asked for; zero-minute rewards say so", async () => {
  const never = { game: "Airport Baggage Simulator", box_art_url: "", priority: null, never: true, claimed_earlier: [],
    campaigns: [{ ...campaign({ id: "n", game: "Airport Baggage Simulator", drops: [drop("z", 0, 0, false, "Statue")] }), status: "never" }] };
  const free = { game: "Ace", box_art_url: "", priority: null, never: false, claimed_earlier: [],
    campaigns: [{ ...campaign({ id: "f", game: "Ace", drops: [drop("q", 0, 0, false, "Nugget")] }), status: "active" }] };
  mockApi({ "GET /api/state": state(), "GET /api/inventory": { total_rewards: 2, claimed_rewards: 0, games: [never, free] } });
  render(<AppProvider initialMe={ME}><InventoryView /></AppProvider>);
  const u = userEvent.setup();
  expect(await screen.findByRole("heading", { name: "Ace" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Airport Baggage Simulator" })).toBeNull();
  expect(screen.getByText("Nugget").closest(".inv-item")).toHaveTextContent("No watch time");
  await u.click(screen.getByRole("button", { name: "Show Never games (1)" }));
  expect(screen.getByRole("heading", { name: "Airport Baggage Simulator" })).toBeInTheDocument();
});

test("Still to earn leaves out campaigns the miner won't mine", async () => {
  const mk = (id: string, game: string, will: boolean) => ({ game, box_art_url: "", priority: null, never: false, claimed_earlier: [],
    campaigns: [{ ...campaign({ id, game, drops: [drop(id, 60, 0, false, `${game} reward`)] }), status: "active", will_mine: will }] });
  mockApi({ "GET /api/state": state(), "GET /api/inventory": { total_rewards: 2, claimed_rewards: 0, games: [mk("a", "Wanted", true), mk("b", "Badge only", false)] } });
  render(<AppProvider initialMe={ME}><InventoryView /></AppProvider>);
  const u = userEvent.setup();
  expect(await screen.findByRole("heading", { name: "Badge only" })).toBeInTheDocument();
  await u.click(screen.getByRole("button", { name: "Still to earn" }));
  expect(screen.queryByRole("heading", { name: "Badge only" })).toBeNull();
  expect(screen.getByRole("heading", { name: "Wanted" })).toBeInTheDocument();
});

test("badge and emote campaigns are hidden unless badge mining is on; sub drops say so", async () => {
  const g = (id: string, game: string, badge: boolean, d = drop(id, 60, 0, false, `${game} reward`)) => ({ game, box_art_url: "", priority: null, never: false, claimed_earlier: [],
    campaigns: [{ ...campaign({ id, game, drops: [d] }), status: "active", will_mine: !badge, badge }] });
  mockApi({ "GET /api/state": state(), "GET /api/inventory": { total_rewards: 3, claimed_rewards: 0, mine_badges: false, games: [
    g("a", "Enshrouded", true), g("b", "Item game", false), g("c", "Sub game", false, drop("c", 0, 0, false, "FrekiFriend", -1, 1))] } });
  render(<AppProvider initialMe={ME}><InventoryView /></AppProvider>);
  const u = userEvent.setup();
  expect(await screen.findByRole("heading", { name: "Item game" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Enshrouded" })).toBeNull();
  expect(screen.getByText("FrekiFriend").closest(".inv-item")).toHaveTextContent("Needs a sub");
  await u.click(screen.getByRole("button", { name: "Show badge and emote campaigns (1)" }));
  expect(screen.getByRole("heading", { name: "Enshrouded" })).toBeInTheDocument();
});

test("the size slider resizes reward tiles and is remembered", async () => {
  localStorage.removeItem("dropwatch.inventory.tile");
  setup();
  const slider = await screen.findByRole("slider", { name: "Reward size" });
  fireEvent.change(slider, { target: { value: "160" } });
  expect(document.getElementById("v-inventory")!.style.getPropertyValue("--inv-tile")).toBe("160px");
  expect(localStorage.getItem("dropwatch.inventory.tile")).toBe("160");
});

function one(c: ReturnType<typeof campaign>, extra: Record<string, unknown> = {}, over: Record<string, unknown> = {}) {
  return { game: c.game, box_art_url: "", priority: null, never: false, claimed_earlier: [], campaigns: [{ ...c, status: "active", will_mine: true, ...extra }], ...over };
}

test("game actions: Prioritise and Never save the lists; Mine now starts a campaign", async () => {
  const c = campaign({ id: "p", game: "Palia", drops: [drop("a", 120, 10, false, "Hat")] });
  const calls = mockApi({
    "GET /api/state": state(), "GET /api/lists": { priority: [], never: [], favourites: [] },
    "GET /api/inventory": { total_rewards: 1, claimed_rewards: 0, games: [one(c)] },
    "PUT /api/lists": (b: unknown) => b, "POST /api/mine-now": null,
  });
  render(<AppProvider initialMe={ME}><InventoryView /></AppProvider>);
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Move Palia to Priority" }));
  expect(calls.find((x) => x.method === "PUT")?.body).toEqual({ priority: ["Palia"], never: [], favourites: [] });
  await u.click(screen.getByRole("button", { name: "Mine Frights & Delights now" }));
  expect(calls.find((x) => x.method === "POST" && x.path.endsWith("/mine-now"))?.body).toEqual({ campaign_id: "p" });
});

test("fully claimed campaigns fold to one line until opened", async () => {
  const c = campaign({ id: "d", game: "Halo", name: "Season Done", drops: [drop("a", 60, 60, true, "Helmet"), drop("b", 60, 60, true, "Visor")] });
  mockApi({ "GET /api/state": state(), "GET /api/lists": { priority: [], never: [], favourites: [] },
    "GET /api/inventory": { total_rewards: 2, claimed_rewards: 2, games: [one(c, { status: "done" })] } });
  render(<AppProvider initialMe={ME}><InventoryView /></AppProvider>);
  const fold = await screen.findByRole("button", { name: "Show Season Done, all 2 claimed" });
  expect(screen.queryByText("Helmet")).toBeNull();
  await userEvent.setup().click(fold);
  expect(screen.getByText("Helmet")).toBeInTheDocument();
});

test("a reward that can't be finished in time says so; clicking a reward shows its details", async () => {
  const late = { ...drop("x", 600, 30, false, "Late hat"), ends_at: new Date(Date.now() + 60 * 60_000).toISOString() };
  const after = { ...drop("y", 900, 0, false, "Second hat"), requires: ["Late hat"] };
  const c = campaign({ id: "l", game: "Rust", name: "Rust S9", allowed_channels: ["streamer_one"], drops: [late, after], linked: false });
  mockApi({ "GET /api/state": state(), "GET /api/lists": { priority: [], never: [], favourites: [] },
    "GET /api/inventory": { total_rewards: 2, claimed_rewards: 0, games: [one(c, { verdict: "wont_finish" })] } });
  render(<AppProvider initialMe={ME}><InventoryView /></AppProvider>);
  const u = userEvent.setup();
  const tile = (await screen.findByText("Late hat")).closest(".inv-item")!;
  expect(tile).toHaveClass("late");
  expect(tile).toHaveTextContent("Won't finish in time");
  expect(screen.getAllByText("Won't finish in time")[0]).toHaveClass("chip");
  await u.click(screen.getByRole("button", { name: "Second hat: details" }));
  const dlg = screen.getByRole("dialog");
  expect(dlg).toHaveTextContent("Earn first");
  expect(dlg).toHaveTextContent("Late hat");
  expect(dlg).toHaveTextContent("streamer_one");
  expect(dlg).toHaveTextContent("Not linked");
  await u.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("Ending soonest lists campaigns by end time across games", async () => {
  const a = campaign({ id: "a", game: "Later game", name: "Later", ends_at: inDays(9) });
  const b = campaign({ id: "b", game: "Sooner game", name: "Sooner", ends_at: inDays(1) });
  mockApi({ "GET /api/state": state(), "GET /api/lists": { priority: [], never: [], favourites: [] },
    "GET /api/inventory": { total_rewards: 6, claimed_rewards: 0, games: [one(a), one(b)] } });
  render(<AppProvider initialMe={ME}><InventoryView /></AppProvider>);
  await screen.findByRole("heading", { name: "Later game" });
  await userEvent.setup().click(screen.getByRole("button", { name: "Ending soonest" }));
  const names = [...document.querySelectorAll(".inv-camp .row-t")].map((n) => n.textContent);
  expect(names[0]).toContain("Sooner");
  expect(names[1]).toContain("Later");
});

test("a reward can be starred from its details, and the tile shows it", async () => {
  const calls = setup({ "GET /api/wishlist": { drops: [] }, "PUT /api/wishlist": (b: unknown) => b });
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Hat: details" }));
  await u.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Star this reward" }));
  await waitFor(() => expect(calls.find((c) => c.method === "PUT" && c.path === "/api/wishlist")?.body).toEqual({ drops: ["b"] }));
  expect(await screen.findByRole("button", { name: "Hat, starred: details" })).toBeInTheDocument();
  expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Starred" })).toHaveAttribute("aria-pressed", "true");
});
