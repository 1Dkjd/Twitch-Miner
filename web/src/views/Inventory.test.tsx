import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { campaign, inDays, state } from "../test/fixtures";
import { InventoryView } from "./Inventory";

const ME = { authenticated: true, setup_required: false };
const drop = (id: string, req: number, cur: number, claimed: boolean, name: string, start = -1) =>
  ({ id, name: id, required_minutes: req, current_minutes: cur, claimed, starts_at: inDays(start), ends_at: inDays(3),
     rewards: [{ name, image_url: "" }] });

function setup() {
  const palia = { ...campaign({ id: "c1", drops: [drop("a", 60, 60, true, "Glasses"), drop("b", 120, 30, false, "Hat")] }), status: "mining" };
  const wardogs = { ...campaign({ id: "w", game: "WARDOGS", name: "Season 02", starts_at: inDays(5), linked: null,
    link_url: "https://wardogs.example/link", drops: [drop("x", 240, 0, false, "Dog tag", 5)] }), status: "upcoming" };
  mockApi({
    "GET /api/state": state(),
    "GET /api/inventory": { total_rewards: 3, claimed_rewards: 1, games: [
      { game: "WARDOGS", box_art_url: "", priority: 1, never: false, campaigns: [wardogs],
        claimed_earlier: [{ at: inDays(-40), campaign_id: "s1", campaign: "Season 01", game: "WARDOGS",
          rewards: [{ name: "Old badge", image_url: "" }], minutes: null, channel: null, campaign_rewards: null, campaign_ends: null, box_art_url: null }] },
      { game: "Palia", box_art_url: "", priority: null, never: false, campaigns: [palia], claimed_earlier: [] },
    ] },
  });
  render(<AppProvider initialMe={ME}><InventoryView /></AppProvider>);
}

test("rewards show claimed, progress and locked states per game", async () => {
  setup();
  const palia = (await screen.findByRole("heading", { name: "Palia" })).closest("section")!;
  expect(within(palia).getByText("Glasses").closest("figure")).toHaveClass("claimed");
  expect(within(palia).getByRole("progressbar", { name: "Hat progress" })).toHaveAttribute("aria-valuenow", "25");
  expect(within(palia).getByText("Mining now")).toHaveClass("chip");
  const wd = screen.getByRole("heading", { name: "WARDOGS" }).closest("section")!;
  expect(within(wd).getByText("Priority 1")).toBeInTheDocument();
  expect(within(wd).getByText("Dog tag").closest("figure")).toHaveClass("locked");
  expect(within(wd).getByRole("link", { name: /Link your WARDOGS account/ })).toBeInTheDocument();
  expect(within(wd).getByText("Old badge").closest("figure")).toHaveClass("claimed");
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
