/* Needs you > Ignore (approved 2026-10-11, docs/design/ignore-mockup.html): hides one campaign until it ends;
 * Undo on the toast, and an "N ignored · Show" line that opens them with Unignore. */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider, Toasts } from "../store";
import { mockApi } from "../test/fetch";
import { campaign, state } from "../test/fixtures";
import { OverviewView } from "./Overview";

const ME = { authenticated: true, setup_required: false };
const DBD = campaign({ id: "dbd", name: "DbD: October of Horror", game: "Dead by Daylight", linked: false });
const BOND = campaign({ id: "bond", name: "Extended Operations", game: "007 First Light", linked: false });
afterEach(() => vi.unstubAllGlobals());

/** A server that keeps the ignored ids, as the real one does. */
function setup(ignored: string[] = []) {
  const ids = new Set(ignored);
  const all = [DBD, BOND];
  const st = () => state({ needs_you: all.filter((c) => !ids.has(c.id)), needs_ignored: all.filter((c) => ids.has(c.id)) });
  const calls = mockApi({
    "GET /api/state": () => st(), "GET /api/lists": { priority: [], never: [], favourites: [] },
    "POST /api/needs/ignored/dbd": () => { ids.add("dbd"); return { ids: [...ids] }; },
    "DELETE /api/needs/ignored/dbd": () => { ids.delete("dbd"); return { ids: [...ids] }; },
    "POST /api/needs/ignored/bond": () => { ids.add("bond"); return { ids: [...ids] }; },
  });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  render(<AppProvider initialMe={ME}><OverviewView /><Toasts /></AppProvider>);
  return calls;
}
const card = () => screen.getByRole("region", { name: /Needs you/ });

test("Ignore hides that campaign, says until when, and Undo brings it back", async () => {
  const calls = setup();
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Ignore DbD: October of Horror" }));
  expect(calls.some((c) => c.method === "POST" && c.path === "/api/needs/ignored/dbd")).toBe(true);
  const toast = await screen.findByRole("group", { name: "Ignored" });
  expect(toast).toHaveTextContent("DbD: October of Horror won't show here or in alerts. It ends");
  await waitFor(() => expect(within(card()).queryByText("Link your Dead by Daylight account")).not.toBeInTheDocument());
  expect(within(card()).getByRole("button", { name: "1 ignored · Show" })).toBeInTheDocument();
  await u.click(within(toast).getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/needs/ignored/dbd")).toBe(true));
  expect(await within(card()).findByText("Link your Dead by Daylight account")).toBeInTheDocument();
  expect(within(card()).queryByRole("button", { name: /ignored/ })).not.toBeInTheDocument();
});

test("Show lists the ignored ones with Unignore; Hide folds them away", async () => {
  const calls = setup(["dbd"]);
  const u = userEvent.setup();
  const show = await screen.findByRole("button", { name: "1 ignored · Show" });
  expect(show).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("button", { name: "Unignore DbD: October of Horror" })).not.toBeInTheDocument();
  await u.click(show);
  expect(screen.getByRole("button", { name: "1 ignored · Hide" })).toHaveAttribute("aria-expanded", "true");
  await u.click(screen.getByRole("button", { name: "Unignore DbD: October of Horror" }));
  await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/needs/ignored/dbd")).toBe(true));
  expect(await screen.findByRole("group", { name: "Back in Needs you" })).toBeInTheDocument();
  expect(await within(card()).findByText("Link your Dead by Daylight account")).toBeInTheDocument();
});

test("with everything ignored the card is one quiet line that still opens them", async () => {
  setup(["dbd", "bond"]);
  const line = await screen.findByRole("button", { name: "Needs you · 2 ignored · Show" });
  expect(screen.queryByText("Link your 007 First Light account")).not.toBeInTheDocument();
  await userEvent.click(line);
  expect(screen.getByRole("button", { name: "Unignore Extended Operations" })).toBeInTheDocument();
});

test("nothing needs you and nothing ignored: no card at all", async () => {
  mockApi({ "GET /api/state": state({ needs_you: [], needs_ignored: [] }), "GET /api/lists": { priority: [], never: [], favourites: [] } });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  render(<AppProvider initialMe={ME}><OverviewView /></AppProvider>);
  await screen.findByRole("article");
  expect(screen.queryByRole("region", { name: /Needs you/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /ignored/ })).not.toBeInTheDocument();
});
