import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { LoginScreen, SetupScreen } from "./PagePassword";

const ME = { authenticated: false, setup_required: true };
afterEach(() => vi.unstubAllGlobals());

test("setup: the button stays disabled until 8+ characters and both entries match", async () => {
  const calls = mockApi({ "POST /api/setup": undefined, "GET /api/me": { authenticated: true, setup_required: false } });
  render(<AppProvider initialMe={ME}><SetupScreen /></AppProvider>);
  const go = screen.getByRole("button", { name: "Set password and continue" });
  const u = userEvent.setup();
  await u.type(screen.getByLabelText("Page password"), "short");
  expect(go).toHaveAttribute("aria-disabled", "true");
  await u.clear(screen.getByLabelText("Page password"));
  await u.type(screen.getByLabelText("Page password"), "correct horse");
  await u.type(screen.getByLabelText("Type it again"), "correct hors");
  expect(go).toHaveAttribute("aria-disabled", "true");
  await u.click(go);
  expect(calls.filter((c) => c.path === "/api/setup")).toHaveLength(0);
  await u.type(screen.getByLabelText("Type it again"), "e");
  expect(go).toHaveAttribute("aria-disabled", "false");
  await u.click(go);
  expect(calls.find((c) => c.path === "/api/setup")?.body).toEqual({ password: "correct horse" });
  expect(location.hash).toBe("#connect");
});

test("login: a wrong password says so and marks the field", async () => {
  mockApi({ "POST /api/login": { status: 401, body: { detail: "Wrong password." } } });
  render(<AppProvider initialMe={{ authenticated: false, setup_required: false }}><LoginScreen /></AppProvider>);
  const u = userEvent.setup();
  await u.type(screen.getByLabelText("Page password"), "nope nope");
  await u.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("That isn't the page password");
  expect(screen.getByLabelText("Page password")).toHaveAttribute("aria-invalid", "true");
});
