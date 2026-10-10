/* Regression tests for the phase-3 final review (page side). */
import { render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import { connectLive } from "./api/live";
import { ConnectScreen } from "./screens/Connect";
import { AppProvider } from "./store";
import { mockApi } from "./test/fetch";
import { state } from "./test/fixtures";
import { OverviewView } from "./views/Overview";

const ME = { authenticated: true, setup_required: false };
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const desktop = () => vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));

// C1: a stale "done" from an earlier sign-in must not hide the code button once signed out
test("a leftover done status while signed out offers a new code", async () => {
  mockApi({ "GET /api/twitch/signin": { status: "done", message: "Signed in as kp." },
    "GET /api/state": state({ state: "signed_out", signed_in: false, login: null, current: null }) });
  render(<AppProvider initialMe={ME}><ConnectScreen /></AppProvider>);
  expect(await screen.findByRole("button", { name: "Get a sign-in code" })).toBeInTheDocument();
  expect(screen.queryByText("Connected")).not.toBeInTheDocument();
});

// I2: signed out is its own card, not the idle copy about live channels
test("signed out shows 'nothing is being mined' and no Check now", async () => {
  desktop();
  mockApi({ "GET /api/state": state({ state: "signed_out", signed_in: false, current: null }), "GET /api/lists": { priority: [], never: [], favourites: [] } });
  render(<AppProvider initialMe={ME}><OverviewView /></AppProvider>);
  expect(await screen.findByText("Nothing is being mined while you're signed out of Twitch.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Check now" })).not.toBeInTheDocument();
  expect(screen.queryByText(/live channel with drops/)).not.toBeInTheDocument();
});

// I3: the miner being down when the page loads is reported, not a blank page, and it recovers
test("an unreachable miner at load shows the banner, then the page once it answers", async () => {
  let up = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (!up) throw new TypeError("Failed to fetch");
    if (String(url).endsWith("/api/me")) return new Response(JSON.stringify({ authenticated: false, setup_required: false }), { status: 200 });
    return new Response("{}", { status: 200 });
  }));
  render(<App retryMs={20} />);
  expect(await screen.findByText("Can't reach the miner")).toBeInTheDocument();
  up = true;
  expect(await screen.findByRole("heading", { name: "Enter the page password" })).toBeInTheDocument();
});

// minor re-graded: a short reconnect (phone wake, restart) still catches up
test("a short reconnect re-fetches", () => {
  vi.useFakeTimers();
  const onRefetch = vi.fn();
  let es: { onopen: (() => void) | null; onerror: (() => void) | null; readyState: number } | null = null;
  connectLive({ onRefetch, onConnection: vi.fn(), open: () => {
    es = { onopen: null, onerror: null, readyState: 1, addEventListener() {}, close() {} } as never;
    return es as unknown as EventSource;
  } });
  es!.onerror!();
  vi.advanceTimersByTime(3000);
  es!.onopen!();
  vi.advanceTimersByTime(500);
  expect(onRefetch).toHaveBeenCalledOnce();
});

// minor re-graded: the chip never contradicts the banner
test("while Twitch is unreachable the card is not 'Mining'", async () => {
  desktop();
  mockApi({ "GET /api/state": state({ state: "twitch_unreachable" }), "GET /api/lists": { priority: [], never: [], favourites: [] } });
  render(<AppProvider initialMe={ME}><OverviewView /></AppProvider>);
  const card = await screen.findByRole("article");
  expect(card).not.toHaveTextContent(/^.*Mining$/);
  await waitFor(() => expect(card.querySelector(".chip.gold")).toBeNull());
  expect(card).toHaveTextContent("Retrying Twitch");
});

// found at the live gate: first run on a miner that already has a Twitch login (CLI sign-in)
test("the Twitch step says 'already connected' when the miner is signed in", async () => {
  sessionStorage.setItem("dw-first-run", "1");
  mockApi({ "GET /api/twitch/signin": { status: "idle", message: "" }, "GET /api/state": state() });
  render(<AppProvider initialMe={ME}><ConnectScreen /></AppProvider>);
  expect(await screen.findByText("Already connected")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Get a sign-in code" })).not.toBeInTheDocument();
  sessionStorage.clear();
});
