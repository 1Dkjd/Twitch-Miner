import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { campaign, state } from "../test/fixtures";
import { PrioritiesView } from "./Priorities";

const ME = { authenticated: true, setup_required: false };
const game = (name: string, over: Record<string, unknown> = {}, camp: Record<string, unknown> = {}) => ({
  game: name, box_art_url: "", priority: null, never: false, claimed_earlier: [],
  campaigns: [{ ...campaign({ id: name, game: name }), status: "active", will_mine: true, badge: false, ...camp }], ...over });

function setup(games: unknown[], lists = { priority: [] as string[], never: [] as string[], favourites: [] as string[] }) {
  const calls = mockApi({
    "GET /api/state": state(), "GET /api/lists": lists, "PUT /api/lists": (b: unknown) => b,
    "GET /api/suggestions": { games: [], channels: [], known_games: [] },
    "GET /api/inventory": { total_rewards: 0, claimed_rewards: 0, games },
  });
  render(<AppProvider initialMe={ME}><PrioritiesView /></AppProvider>);
  return calls;
}

test("bulk Never ticks badge/emote-only games and moves the ticked games at once", async () => {
  const calls = setup([game("Enshrouded", {}, { badge: true }), game("ELDEN RING", {}, { badge: true }), game("Rust")]);
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Add several games…" }));
  const box = screen.getByRole("group", { name: "Add several games to Never" });
  await u.click(within(box).getByRole("button", { name: "Tick badge/emote-only games (2)" }));
  expect(within(box).getByRole("checkbox", { name: /Rust/ })).not.toBeChecked();
  await u.click(within(box).getByRole("button", { name: "Never mine 2 games" }));
  const put = calls.filter((c) => c.method === "PUT").at(-1)!.body as { never: string[] };
  expect(put.never.sort()).toEqual(["ELDEN RING", "Enshrouded"]);
});

test("Linked accounts lists games needing a link first, with link buttons; linked ones fold away", async () => {
  setup([
    game("Linked game", {}, { linked: true, link_url: "https://a.example" }),
    game("Unlinked game", {}, { linked: false, link_url: "https://b.example" }),
    game("Badge game", {}, { badge: true, linked: false, link_url: "https://c.example" }),
  ]);
  const sec = (await screen.findByRole("heading", { name: "Linked accounts" })).closest(".bucket") as HTMLElement;
  const u = userEvent.setup();
  expect(await within(sec).findByText("Unlinked game")).toBeInTheDocument();
  expect(within(sec).getByRole("link", { name: /Link your Unlinked game account/ })).toHaveAttribute("href", "https://b.example");
  expect(within(sec).queryByText("Linked game")).toBeNull();
  expect(within(sec).queryByText("Badge game")).toBeNull(); // badge/emote drops need no account
  await u.click(within(sec).getByRole("button", { name: "Show linked games (1)" }));
  expect(within(sec).getByText("Linked game")).toBeInTheDocument();
});
