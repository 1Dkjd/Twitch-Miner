import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { state } from "../test/fixtures";
import { SettingsView } from "./Settings";

const SETTINGS = { mine_badges: false, claim_points: true, notify_target: "", notify_claimed: true, notify_needs_you: true, notify_signin: true };
afterEach(() => vi.unstubAllGlobals());

function setup(extra: Record<string, unknown> = {}) {
  const calls = mockApi({ "GET /api/state": state(), "GET /api/settings": SETTINGS, ...extra });
  render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}><SettingsView /></AppProvider>);
  return calls;
}

test("Twitch sign-out asks first; Stay signed in returns focus and does nothing", async () => {
  const calls = setup({ "POST /api/twitch/signout": undefined });
  const u = userEvent.setup();
  const btn = await screen.findByRole("button", { name: "Sign out" , description: "" });
  await u.click(screen.getAllByRole("button", { name: "Sign out" })[0]!);
  const stay = screen.getByRole("button", { name: "Stay signed in" });
  expect(stay).toHaveFocus();
  await u.click(stay);
  expect(document.querySelector(".confirm")).toBeNull(); // the sign-in alert shares this wording, so look at the box
  expect(calls.some((c) => c.path === "/api/twitch/signout")).toBe(false);
  expect(btn).toBeInTheDocument();
  await u.click(screen.getAllByRole("button", { name: "Sign out" })[0]!);
  const confirmBox = document.querySelector(".confirm")!;
  await u.click(confirmBox.querySelector("button.btn:not(.quiet)")!);
  await waitFor(() => expect(calls.some((c) => c.path === "/api/twitch/signout")).toBe(true));
});

test("the badges switch saves straight away", async () => {
  const calls = setup({ "PUT /api/settings": { ...SETTINGS, mine_badges: true } });
  const sw = await screen.findByRole("checkbox", { name: "Also mine badge and emote campaigns" });
  await waitFor(() => expect(sw).toBeEnabled());
  await userEvent.click(sw);
  await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ mine_badges: true }));
  expect(sw).toBeChecked();
});

test("the old single-URL notification design is gone (replaced 2026-10-10)", async () => {
  setup();
  await screen.findByRole("heading", { name: "Notifications" });
  expect(screen.queryByText(/A reward is claimed/)).not.toBeInTheDocument();
  expect(screen.queryByText(/An ntfy topic or a Discord webhook URL/)).not.toBeInTheDocument();
});
