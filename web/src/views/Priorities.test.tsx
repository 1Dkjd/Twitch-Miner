import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider, useApp } from "../store";
import { mockApi } from "../test/fetch";
import { state } from "../test/fixtures";
import { PrioritiesView } from "./Priorities";

const ME = { authenticated: true, setup_required: false };
function Said() {
  return <div data-testid="said">{useApp().announcement}</div>;
}
afterEach(() => vi.unstubAllGlobals());

function setup(lists: { priority: string[]; never: string[]; favourites: string[] }, put?: (b: unknown) => unknown) {
  const calls = mockApi({
    "GET /api/state": state(), "GET /api/lists": lists,
    "GET /api/suggestions": { games: ["Palia", "Phasmophobia", "007 First Light", "AION 2"], channels: [
      { login: "example_streamer", live: true, game: "Palia", last_seen: "2026-10-10T10:00:00Z" },
      { login: "dnd", live: false, game: "Dungeons & Dragons", last_seen: "2026-10-08T20:00:00Z" },
      { login: "never_seen", live: false, game: null, last_seen: null }] },
    "PUT /api/lists": put ?? ((b: unknown) => b),
  });
  render(<AppProvider initialMe={ME}><PrioritiesView /><Said /></AppProvider>);
  return calls;
}

test("moving a game keeps focus on it and announces the new position", async () => {
  const calls = setup({ priority: ["Palia", "Phasmophobia"], never: [], favourites: [] });
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Move Phasmophobia up" }));
  await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ priority: ["Phasmophobia", "Palia"] }));
  await waitFor(() => expect(screen.getByTestId("said")).toHaveTextContent("Phasmophobia moved to position 1 of 2"));
  // up is now disabled at the top, so focus lands on the next enabled control of the same row
  await waitFor(() => expect(document.activeElement?.closest(".g")?.getAttribute("data-name")).toBe("Phasmophobia"));
});

test("adding an unknown game asks first; Add anyway adds it", async () => {
  const calls = setup({ priority: [], never: [], favourites: [] });
  const u = userEvent.setup();
  await u.type(await screen.findByRole("combobox", { name: "Add a game to Priority" }), "Hollow Knight");
  await u.click(screen.getAllByRole("button", { name: "Add" })[0]!);
  expect(screen.getByText(/No game called/)).toHaveTextContent("No game called Hollow Knight has a campaign right now");
  expect(calls.some((c) => c.method === "PUT")).toBe(false);
  await u.click(screen.getByRole("button", { name: "Add anyway" }));
  await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ priority: ["Hollow Knight"] }));
});

test("a known game is matched case-insensitively and added straight away", async () => {
  const calls = setup({ priority: [], never: [], favourites: [] });
  const u = userEvent.setup();
  await u.type(await screen.findByRole("combobox", { name: "Add a game to Never" }), "aion 2");
  await u.click(screen.getAllByRole("button", { name: "Add" })[2]!);
  await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ never: ["AION 2"] }));
});

test("a rejected save rolls back and says why", async () => {
  setup({ priority: ["Palia"], never: [], favourites: [] }, () => ({ status: 422, body: { detail: "In both Priority and Never: Palia" } }));
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Never mine Palia" }));
  await waitFor(() => expect(screen.getByTestId("said")).toHaveTextContent("In both Priority and Never: Palia"));
  expect(document.getElementById("z-priority")).toHaveTextContent("Palia");
  expect(document.getElementById("z-never")).not.toHaveTextContent("Palia");
});

test("rows say what each game is doing", async () => {
  setup({ priority: ["Palia", "007 First Light"], never: [], favourites: ["example_streamer"] });
  expect(await screen.findByText(/Mining now · 5 h 38 min to go/)).toBeInTheDocument();
  expect(screen.getByText(/Needs account link/)).toHaveClass("g-s", "warn");
  expect(screen.getByText(/Live now · Palia/)).toBeInTheDocument();
});

test("favourites say live now, when they were last seen, or not seen yet", async () => {
  setup({ priority: [], never: [], favourites: ["example_streamer", "dnd", "never_seen"] });
  expect(await screen.findByText("Live now · Palia")).toHaveClass("on");
  expect(screen.getByText(/Offline · last seen .* on Dungeons & Dragons/)).toBeInTheDocument();
  expect(screen.getByText("Not seen live yet")).toBeInTheDocument();
});

test("the channel add box suggests offline channels too, with a note", async () => {
  setup({ priority: [], never: [], favourites: [] });
  await screen.findByRole("combobox", { name: "Add a favourite channel" });
  const opts = [...document.querySelectorAll("#known-channels option")].map((o) => [o.getAttribute("value"), o.getAttribute("label")]);
  expect(opts[0]).toEqual(["example_streamer", "Live now · Palia"]);
  expect(opts[1]![0]).toBe("dnd");
  expect(opts[1]![1]).toMatch(/^Offline · last seen/);
});
