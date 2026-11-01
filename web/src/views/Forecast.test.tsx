import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { State } from "../api/client";
import { inDays, state } from "../test/fixtures";
import { Forecast } from "./Forecast";

type F = NonNullable<State["forecast"]>;
const step = (id: string, over: Partial<F["steps"][number]> = {}): F["steps"][number] => ({
  campaign_id: id, name: `Campaign ${id}`, game: `Game ${id}`, box_art_url: "https://static-cdn.jtvnw.net/ttv-boxart/1.jpg",
  starts_at: inDays(1), finishes_at: inDays(1.1), status: "ok", rewards_earned: 1, missed: [], alongside: false, ...over,
});
const show = (over: Partial<F>) => render(<Forecast state={state({ forecast: { steps: [], missed: 0, finishes_at: inDays(2), waiting: [], ...over } })} />);

test("says everything finishes, and when", () => {
  show({ steps: [step("a")] });
  expect(screen.getByRole("region", { name: "Forecast" })).toHaveTextContent(/Everything finishes by/);
  expect(screen.getByRole("listitem")).toHaveTextContent("1 reward by");
});

test("names what won't make it, in words", () => {
  show({ missed: 2, steps: [step("a"), step("b", { status: "partial", missed: ["Hat"] }), step("c", { status: "miss", rewards_earned: 0, missed: ["Skin"] })] });
  expect(screen.getByText("2 rewards won't make it")).toHaveClass("chip", "red");
  const rows = screen.getAllByRole("listitem");
  expect(within(rows[1]!).getByText("Won't make it: Hat")).toBeInTheDocument();
  expect(within(rows[2]!).getByText("Won't make it: Skin")).toBeInTheDocument();
  expect(within(rows[2]!).queryByText(/reward.* by/)).toBeNull();
});

test("long forecasts fold, but anything at risk stays in view", async () => {
  const steps = [...Array.from({ length: 7 }, (_, i) => step(`s${i}`)), step("late", { status: "miss", rewards_earned: 0, missed: ["Skin"] })];
  show({ missed: 1, steps });
  expect(screen.getAllByRole("listitem")).toHaveLength(6);
  expect(screen.getByText("Campaign late")).toBeInTheDocument();
  const more = screen.getByRole("button", { name: "Show all 8" });
  await userEvent.click(more);
  expect(screen.getAllByRole("listitem")).toHaveLength(8);
  expect(screen.getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");
});

test("marks the first step now, and what is earned alongside it", () => {
  show({ steps: [step("a", { starts_at: inDays(-0.001) }), step("b", { alongside: true })] });
  const rows = screen.getAllByRole("listitem");
  expect(rows[0]).toHaveTextContent("Game a·now");
  expect(rows[1]).toHaveTextContent("earned alongside");
});

test("lists what can't be scheduled", () => {
  show({ steps: [step("a")], waiting: ["Offline Cup"] });
  expect(screen.getByText(/waiting for a live channel: Offline Cup/)).toBeInTheDocument();
});

test("shows nothing when there is nothing to forecast", () => {
  const { container, rerender } = render(<Forecast state={state({ forecast: null })} />);
  expect(container).toBeEmptyDOMElement();
  rerender(<Forecast state={state({ forecast: { steps: [], missed: 0, finishes_at: null, waiting: ["Offline Cup"] } })} />);
  expect(container).toBeEmptyDOMElement();
});
