/* The toast (picked 2026-10-11 from docs/design/toast-mockup.html): variant B (title + detail, deck) with a line
 * along the bottom that drains until it closes, no numbers; bottom right, centred on phones. */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "./api/client";
import { AppProvider, Toasts, useApp, type ToastSpec } from "./store";
import { mockApi } from "./test/fetch";
import { state } from "./test/fixtures";

afterEach(() => vi.unstubAllGlobals());

function Sayer({ spec, error }: { spec?: ToastSpec | string; error?: unknown }) {
  const { say, sayError } = useApp();
  return <button type="button" onClick={() => (error ? sayError(error, "Couldn't save") : say(spec!))}>go</button>;
}

function setup(node: React.ReactNode) {
  mockApi({ "GET /api/state": state() });
  render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}>{node}<Toasts /></AppProvider>);
}
const toasts = () => screen.queryAllByRole("group", { name: /./ }).filter((g) => g.classList.contains("toast"));

test("a title, a quieter detail line and an action; the action runs and closes it", async () => {
  const run = vi.fn();
  setup(<Sayer spec={{ title: "Moved to Never", detail: "Vaultbreakers won't be mined.", action: { label: "Undo", run } }} />);
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  const t = screen.getByRole("group", { name: "Moved to Never" });
  expect(t).toHaveTextContent("Vaultbreakers won't be mined.");
  await userEvent.click(within(t).getByRole("button", { name: "Undo" }));
  expect(run).toHaveBeenCalledOnce();
  expect(screen.queryByRole("group", { name: "Moved to Never" })).not.toBeInTheDocument();
});

test("a plain message is just a title, and success is the default tone", async () => {
  setup(<Sayer spec="Setting saved" />);
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  const t = screen.getByRole("group", { name: "Setting saved" });
  expect(t).toHaveClass("toast", "ok");
  expect(t.querySelector(".toast-d")).toBeNull();
});

test("an error is its own tone, titled, with the server's reason as the detail", async () => {
  setup(<Sayer error={new ApiError(503, "The miner didn't answer.")} />);
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  const t = screen.getByRole("group", { name: "Couldn't save" });
  expect(t).toHaveClass("bad");
  expect(t).toHaveTextContent("The miner didn't answer.");
});

test("the line along the bottom times it: 4 s plain, 8 s with an action, and it closes when the line runs out", async () => {
  setup(<><Sayer spec="Setting saved" /><Sayer spec={{ title: "Moved to Never", action: { label: "Undo", run: () => undefined } }} /></>);
  const [plain, withAction] = screen.getAllByRole("button", { name: "go" });
  await userEvent.click(plain!);
  await userEvent.click(withAction!);
  const bar = (name: string) => screen.getByRole("group", { name }).querySelector(".toast-bar") as HTMLElement;
  expect(bar("Setting saved").style.animationDuration).toBe("4000ms");
  expect(bar("Moved to Never").style.animationDuration).toBe("8000ms");
  act(() => { fireEvent.animationEnd(bar("Setting saved")); });
  expect(screen.queryByRole("group", { name: "Setting saved" })).not.toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Moved to Never" })).toBeInTheDocument();
});

test("pointing at or tabbing into the deck pauses every line", async () => {
  setup(<Sayer spec="Setting saved" />);
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  const deck = screen.getByRole("region", { name: "Notices" });
  expect(deck).not.toHaveAttribute("data-paused");
  fireEvent.mouseEnter(deck);
  expect(deck).toHaveAttribute("data-paused");
  fireEvent.mouseLeave(deck);
  expect(deck).not.toHaveAttribute("data-paused");
  fireEvent.focus(screen.getByRole("button", { name: "Dismiss: Setting saved" }));
  expect(deck).toHaveAttribute("data-paused");
});

test("closing the last notice while pointing at it doesn't leave the next one paused", async () => {
  // found on the bench: the deck unmounts under the pointer, so mouseleave/blur never arrive
  setup(<Sayer spec="Setting saved" />);
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  fireEvent.mouseEnter(screen.getByRole("region", { name: "Notices" }));
  fireEvent.click(screen.getByRole("button", { name: "Dismiss: Setting saved" }));
  expect(screen.queryByRole("region", { name: "Notices" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  expect(screen.getByRole("region", { name: "Notices" })).not.toHaveAttribute("data-paused");
});

test("dismissing from the keyboard lets the other notices carry on closing", async () => {
  // review fix: the focused button is removed, so no blur arrives and the deck stayed paused for good
  setup(<><Sayer spec="One" /><Sayer spec="Two" /></>);
  for (const b of screen.getAllByRole("button", { name: "go" })) await userEvent.click(b);
  const deck = screen.getByRole("region", { name: "Notices" });
  const dismiss = within(screen.getByRole("group", { name: "Two" })).getByRole("button", { name: "Dismiss: Two" });
  act(() => dismiss.focus());
  expect(deck).toHaveAttribute("data-paused");
  await userEvent.keyboard("{Enter}");
  expect(screen.queryByRole("group", { name: "Two" })).not.toBeInTheDocument();
  expect(deck).not.toHaveAttribute("data-paused");
});

test("they stack newest first, three at most", async () => {
  setup(<><Sayer spec="One" /><Sayer spec="Two" /><Sayer spec="Three" /><Sayer spec="Four" /></>);
  for (const b of screen.getAllByRole("button", { name: "go" })) await userEvent.click(b);
  expect(toasts().map((t) => t.getAttribute("aria-label"))).toEqual(["Four", "Three", "Two"]);
});

/* Polish (2026-10-12): errors stay as long as an Undo; a full deck drops a plain notice before an Undo; each
 * Dismiss says what it dismisses; Alt+N reaches the newest notice from the keyboard. */
test("an error stays up as long as a notice with Undo", async () => {
  setup(<Sayer error={new ApiError(503, "The miner didn't answer.")} />);
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  const bar = screen.getByRole("group", { name: "Couldn't save" }).querySelector(".toast-bar") as HTMLElement;
  expect(bar.style.animationDuration).toBe("8000ms");
});

test("when the deck is full, the oldest plain notice goes before an Undo", async () => {
  const undo = { label: "Undo", run: () => undefined };
  setup(<><Sayer spec={{ title: "Moved to Never", action: undo }} /><Sayer spec="Two" /><Sayer spec="Three" /><Sayer spec="Four" /></>);
  for (const b of screen.getAllByRole("button", { name: "go" })) await userEvent.click(b);
  expect(toasts().map((t) => t.getAttribute("aria-label"))).toEqual(["Four", "Three", "Moved to Never"]);
});

test("each Dismiss button names the notice it closes", async () => {
  setup(<><Sayer spec="One" /><Sayer spec="Two" /></>);
  for (const b of screen.getAllByRole("button", { name: "go" })) await userEvent.click(b);
  expect(screen.getByRole("button", { name: "Dismiss: Two" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Dismiss: One" })).toBeInTheDocument();
});

test("Alt+N reaches the newest notice's Undo, and focus goes back afterwards", async () => {
  const run = vi.fn();
  setup(<><input aria-label="somewhere" /><Sayer spec={{ title: "Moved to Never", detail: "Palia won't be mined.", action: { label: "Undo", run } }} /></>);
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  const field = screen.getByRole("textbox", { name: "somewhere" });
  act(() => field.focus());
  await userEvent.keyboard("{Alt>}n{/Alt}");
  const undo = within(screen.getByRole("group", { name: "Moved to Never" })).getByRole("button", { name: "Undo" });
  expect(undo).toHaveFocus();
  expect(screen.getByRole("region", { name: "Notices" })).toHaveAttribute("data-paused");
  await userEvent.keyboard("{Enter}");
  expect(run).toHaveBeenCalledOnce();
  expect(field).toHaveFocus();
});

test("the announcement for a notice with Undo says how to reach it", async () => {
  function Said() { return <div data-testid="said">{useApp().announcement}</div>; }
  setup(<><Said /><Sayer spec={{ title: "Moved to Never", detail: "Palia won't be mined.", action: { label: "Undo", run: () => undefined } }} /></>);
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  await waitFor(() => expect(screen.getByTestId("said")).toHaveTextContent("Moved to Never. Palia won't be mined. Alt+N to reach Undo."));
});
