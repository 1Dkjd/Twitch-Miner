import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { ConnectScreen } from "./Connect";

const ME = { authenticated: true, setup_required: false };
const WAITING = { status: "waiting", message: "", code: "BKDQMDGP", verification_uri: "https://www.twitch.tv/activate",
  expires_at: new Date(Date.now() + 29 * 60_000).toISOString() };
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

test("getting a code shows it, then Connected once Twitch confirms", async () => {
  sessionStorage.setItem("dw-first-run", "1");
  let reads = 0;
  mockApi({
    "GET /api/twitch/signin": () => (reads++ < 1 ? { status: "idle", message: "" } : { status: "done", message: "Signed in as kp." }),
    "POST /api/twitch/signin": WAITING,
    // signed out until Twitch confirms the code, then signed in
    "GET /api/state": () => ({ state: reads > 1 ? "mining" : "signed_out", signed_in: reads > 1,
      login: reads > 1 ? "kernelpanicattack" : null, paused_until: null, last_refresh: null,
      current: null, needs_you: [], up_next: [], done: [] }),
  });
  render(<AppProvider initialMe={ME}><ConnectScreen pollMs={30} /></AppProvider>);
  expect(screen.getByRole("list", { name: "Setup steps" })).toBeInTheDocument();
  await userEvent.click(await screen.findByRole("button", { name: "Get a sign-in code" }));
  expect(await screen.findByLabelText("Code B K D Q M D G P")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Open twitch.tv\/activate/ })).toHaveAttribute("href", "https://www.twitch.tv/activate");
  expect(await screen.findByText("Connected")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("kernelpanicattack")).toBeInTheDocument());
});

test("an expired code offers a new one; a later visit has no setup steps", async () => {
  mockApi({ "GET /api/twitch/signin": { status: "expired", message: "That code expired. Get a new one." } });
  render(<AppProvider initialMe={ME}><ConnectScreen /></AppProvider>);
  expect(await screen.findByText("That code expired")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Get a new code" })).toBeInTheDocument();
  expect(screen.queryByRole("list", { name: "Setup steps" })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sign in to Twitch again");
});

test("cancel goes back to the start", async () => {
  const calls = mockApi({ "GET /api/twitch/signin": WAITING, "DELETE /api/twitch/signin": undefined });
  render(<AppProvider initialMe={ME}><ConnectScreen pollMs={10_000} /></AppProvider>);
  await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
  expect(await screen.findByRole("button", { name: "Get a sign-in code" })).toBeInTheDocument();
  expect(calls.some((c) => c.method === "DELETE")).toBe(true);
});
