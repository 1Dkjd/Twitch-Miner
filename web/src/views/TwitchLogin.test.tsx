import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider, Toasts } from "../store";
import { mockApi } from "../test/fetch";
import { state } from "../test/fixtures";
import { TwitchLogin, keysymFor } from "./TwitchLogin";

const sent: number[] = [];
const made: string[] = [];
vi.mock("@novnc/novnc", () => ({
  default: class extends EventTarget {
    scaleViewport = false; focusOnClick = false; background = "";
    constructor(_el: HTMLElement, url: string) { super(); made.push(url); }
    sendKey(k: number) { sent.push(k); }
    focus() {}
    disconnect() {}
  },
}));

const ME = { authenticated: true, setup_required: false };

test("keysyms: ASCII and Latin-1 as themselves, others in the Unicode range, newline as Return", () => {
  expect(keysymFor("a")).toBe(0x61);
  expect(keysymFor("é")).toBe(0xe9);
  expect(keysymFor("€")).toBe(0x01000000 + 0x20ac);
  expect(keysymFor("\n")).toBe(0xff0d);
});

test("hidden when this install has no browser", async () => {
  mockApi({ "GET /api/state": state(), "GET /api/twitch/browser": { status: "idle", message: "", available: false } });
  render(<AppProvider initialMe={ME}><TwitchLogin kind="tv" /></AppProvider>);
  await waitFor(() => expect(screen.queryByRole("button", { name: "Sign in on Twitch's page" })).toBeNull());
});

test("opens Twitch's page live, types a pasted password in, and closes when signed in", async () => {
  let st = { status: "idle", message: "", available: true };
  const calls = mockApi({
    "GET /api/state": state(),
    "GET /api/twitch/browser": () => st,
    "POST /api/twitch/browser": () => (st = { status: "open", message: "Sign in to Twitch below", available: true }),
    "DELETE /api/twitch/browser": undefined,
  });
  render(<AppProvider initialMe={ME}><TwitchLogin kind="tv" /><Toasts /></AppProvider>);
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Sign in on Twitch's page" }));
  expect(calls.some((c) => c.method === "POST" && c.path === "/api/twitch/browser")).toBe(true);
  expect(screen.getByRole("dialog", { name: "Sign in to Twitch" })).toBeInTheDocument();
  await waitFor(() => expect(made.at(-1)).toMatch(/\/api\/twitch\/browser\/vnc$/));
  await u.type(screen.getByLabelText("Password manager?"), "pw1");
  await u.click(screen.getByRole("button", { name: "Type it" }));
  expect(sent.slice(-3)).toEqual([0x70, 0x77, 0x31]);
  st = { status: "done", message: "Signed in as dk. Dropwatch now sees every campaign.", available: true };
  await act(async () => { await new Promise((r) => setTimeout(r, 1100)); });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

test("Cancel stops the sign-in browser", async () => {
  let st = { status: "idle", message: "", available: true };
  const calls = mockApi({
    "GET /api/state": state(),
    "GET /api/twitch/browser": () => st,
    "POST /api/twitch/browser": () => (st = { status: "starting", message: "", available: true }),
    "DELETE /api/twitch/browser": () => { st = { status: "idle", message: "", available: true }; return undefined; },
  });
  render(<AppProvider initialMe={ME}><TwitchLogin kind="tv" /></AppProvider>);
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: "Sign in on Twitch's page" }));
  await u.click(screen.getByRole("button", { name: "Cancel" }));
  expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/twitch/browser")).toBe(true);
  expect(screen.queryByRole("dialog")).toBeNull();
});
