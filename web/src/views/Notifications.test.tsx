import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider, useApp } from "../store";
import { mockApi } from "../test/fetch";
import { state } from "../test/fixtures";
import { SettingsView } from "./Settings";

const ME = { authenticated: true, setup_required: false };
const SETTINGS = {
  mine_badges: false, claim_points: true, notify_signin: true, notify_unreachable: true, notify_not_earning: true,
  notify_claim_failed: true, notify_stopped: true, notify_needs_you: false,
  notify_unreachable_minutes: 15, notify_not_earning_minutes: 30, arrange_up_next: false,
  notify_claimed: false, notify_weekly: false, notify_weekly_day: 6, notify_weekly_hour: 18,
};
const ALL = [["ntfy", "ntfy"], ["telegram", "Telegram"], ["discord", "Discord"], ["slack", "Slack"],
  ["pushover", "Pushover"], ["gotify", "Gotify"], ["webhook", "Webhook"]].map(([type, name]) => ({ type, name }));
const discord = (set: boolean) => ({
  type: "discord", name: "Discord", configured: set, summary: set ? "webhook set" : "not set", hint: "In Discord: Channel Settings…",
  fields: [{ key: "webhook_url", label: "Discord webhook URL", secret: true, value: "", set }],
});

function Said() {
  return <div data-testid="said">{useApp().announcement}</div>;
}
function setup(routes: Record<string, unknown> = {}) {
  const calls = mockApi({
    "GET /api/state": state(), "GET /api/settings": SETTINGS, "PUT /api/settings": (b: object) => ({ ...SETTINGS, ...b }),
    "GET /api/notify/channels": { channels: [], available: ALL }, ...routes,
  });
  render(<AppProvider initialMe={ME}><SettingsView /><Said /></AppProvider>);
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

test("the failure alerts are on, 'a campaign needs you' is off, and a switch saves", async () => {
  const calls = setup();
  const u = userEvent.setup();
  const sec = (await screen.findByRole("heading", { name: "Notifications" })).closest(".set") as HTMLElement;
  for (const name of ["Twitch sign-in stops working", "Twitch can't be reached", "Mining isn't earning",
    "A reward couldn't be claimed", "Mining stopped on an error"]) {
    expect(await within(sec).findByRole("checkbox", { name })).toBeChecked();
  }
  const needs = within(sec).getByRole("checkbox", { name: "A campaign needs you" });
  expect(needs).not.toBeChecked();
  await u.click(needs);
  await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ notify_needs_you: true }));
});

test("the wait times are editable and only valid numbers are saved", async () => {
  const calls = setup();
  const u = userEvent.setup();
  const mins = await screen.findByRole("spinbutton", { name: "Minutes before the Twitch can't be reached alert" });
  await waitFor(() => expect(mins).toHaveValue(15));
  await u.clear(mins);
  await u.type(mins, "2");
  await u.tab();
  expect(calls.some((c) => c.method === "PUT")).toBe(false); // under the 5-minute floor
  await waitFor(() => expect(screen.getByTestId("said")).toHaveTextContent("Pick 5 to 240 minutes."));
  await u.clear(mins);
  await u.type(mins, "45");
  await u.tab();
  await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ notify_unreachable_minutes: 45 }));
});

test("adding a channel opens its editor; a secret is sent once and never shown back", async () => {
  let channels: unknown[] = [];
  const calls = setup({
    "GET /api/notify/channels": () => ({ channels, available: ALL }),
    "PUT /api/notify/channels/discord": (b: { values: Record<string, string> }) => {
      channels = [discord(Boolean(b.values.webhook_url))];
      return { channels, available: ALL.filter((a) => a.type !== "discord") };
    },
  });
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: /Add a channel/ }));
  await u.click(screen.getByRole("menuitem", { name: "Discord" }));
  await waitFor(() => expect(calls.find((c) => c.path === "/api/notify/channels/discord")?.body).toEqual({ values: {} }));
  const field = await screen.findByLabelText("Discord webhook URL");
  expect(field).toHaveFocus();
  expect(field).toHaveAttribute("type", "password");
  await u.type(field, "https://discord.com/api/webhooks/1/SECRET");
  await u.tab();
  await waitFor(() => expect(calls.filter((c) => c.path === "/api/notify/channels/discord").at(-1)?.body)
    .toEqual({ values: { webhook_url: "https://discord.com/api/webhooks/1/SECRET" } }));
  expect(await screen.findByText("webhook set")).toBeInTheDocument();
  expect(screen.getByLabelText("Discord webhook URL")).toHaveValue(""); // the page never holds it again
  expect(screen.getByLabelText("Discord webhook URL")).toHaveAttribute("placeholder", "Saved. Type a new one to replace it.");
});

test("removing a channel and sending a test", async () => {
  const calls = setup({
    "GET /api/notify/channels": { channels: [discord(true)], available: ALL.filter((a) => a.type !== "discord") },
    "DELETE /api/notify/channels/discord": { channels: [], available: ALL },
    "POST /api/notify/test": { ok: false, message: "Failed: Discord: HTTP 404.", results: [] },
  });
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Send test notification" }));
  expect(await screen.findByText("Failed: Discord: HTTP 404.")).toBeInTheDocument();
  await u.click(screen.getByRole("button", { name: "Remove Discord" }));
  await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  await waitFor(() => expect(screen.queryByText("webhook set")).toBeNull());
});

test("the weekly summary and reward-claimed pushes are off, and the day and time save", async () => {
  const calls = setup();
  const u = userEvent.setup();
  const weekly = await screen.findByRole("checkbox", { name: "Weekly summary" });
  expect(weekly).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: "A reward is claimed" })).not.toBeChecked();
  expect(screen.getByRole("combobox", { name: "Day" })).toHaveValue("6");
  expect(screen.getByRole("combobox", { name: "Time" })).toHaveValue("18");
  await u.click(weekly);
  await waitFor(() => expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({ notify_weekly: true }));
  await u.selectOptions(screen.getByRole("combobox", { name: "Day" }), "Friday");
  await waitFor(() => expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({ notify_weekly_day: 4 }));
  await u.selectOptions(screen.getByRole("combobox", { name: "Time" }), "09:00");
  await waitFor(() => expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({ notify_weekly_hour: 9 }));
});
