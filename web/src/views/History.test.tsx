import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { state } from "../test/fixtures";
import { HistoryView, groupByDay } from "./History";

const r = (name: string) => ({ name, image_url: `u/${name}` });
const claim = (at: string, campaign_id: string, name: string) =>
  ({ at, campaign_id, campaign: `C-${campaign_id}`, game: "Palia", rewards: [r(name)] });

test("days are the viewer's local days: 02:30 UTC is still the previous evening in New York", () => {
  const groups = groupByDay([
    claim("2026-10-10T15:00:00Z", "c1", "late"),
    claim("2026-10-10T02:30:00Z", "c1", "evening"),
    claim("2026-10-09T23:00:00Z", "c1", "earlier"),
  ], "America/New_York");
  expect(groups.map((g) => g.label)).toEqual(["Sat 10 Oct", "Fri 9 Oct"]);
  expect(groups[1]!.rows[0]!.rewards.map((x) => x.name)).toEqual(["evening", "earlier"]);
});

test("one row per campaign per day, with its time span", () => {
  const groups = groupByDay([claim("2026-10-10T15:00:00Z", "c1", "a"), claim("2026-10-10T13:00:00Z", "c1", "b"),
    claim("2026-10-10T14:00:00Z", "c2", "c")], "UTC");
  expect(groups).toHaveLength(1);
  expect(groups[0]!.rows.map((x) => [x.campaign_id, x.rewards.length])).toEqual([["c1", 2], ["c2", 1]]);
});

test("the view summarises and switches period", async () => {
  const calls = mockApi({
    "GET /api/state": state(),
    "GET /api/history": { total_rewards: 2, claims: [claim("2026-10-10T15:00:00Z", "c1", "a"), claim("2026-10-10T14:00:00Z", "c2", "b")] },
  });
  render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}><HistoryView /></AppProvider>);
  expect(await screen.findByText(/claimed from 2 campaigns/)).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Time period" }), "90");
  expect(calls.some((c) => c.path === "/api/history?days=90")).toBe(true);
  vi.unstubAllGlobals();
});
