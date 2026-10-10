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

const detailed = (at: string, name: string, minutes: number | null, channel: string | null) => ({
  at, campaign_id: "c9", campaign: "EXFIL Brothers Day 2", game: "Escape from Tarkov", rewards: [r(name)],
  minutes, channel, campaign_rewards: minutes === null && channel === null ? null : 10,
  campaign_ends: minutes === null && channel === null ? null : "2026-10-11T12:00:00Z",
});

function renderHistory(claims: unknown[]) {
  mockApi({ "GET /api/state": state(), "GET /api/history": { total_rewards: claims.length, claims } });
  render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}><HistoryView /></AppProvider>);
}

test("tapping a campaign opens each reward with its watch time and channel", async () => {
  renderHistory([detailed("2026-10-10T13:00:00Z", "Rare 1", 120, "honeyxxo"),
    detailed("2026-10-10T12:00:00Z", "Common 1", 60, "honeyxxo")]);
  const u = userEvent.setup();
  const btn = await screen.findByRole("button", { name: /EXFIL Brothers Day 2/ });
  expect(btn).toHaveAttribute("aria-expanded", "false");
  const body = document.getElementById(btn.getAttribute("aria-controls")!)!;
  expect(body).not.toBeVisible();
  await u.click(btn);
  expect(btn).toHaveAttribute("aria-expanded", "true");
  expect(body).toBeVisible();
  expect(body).toHaveTextContent("2 of 10 rewards in this campaign");
  expect(body).toHaveTextContent(/campaign ends Sun 11 Oct/);
  const lines = [...body.querySelectorAll("li")].map((li) => li.textContent);
  expect(lines[0]).toMatch(/^Common 1after 1\sh watched·on honeyxxo\d\d:\d\d$/); // oldest first
  expect(lines[1]).toMatch(/^Rare 1after 2\sh watched·on honeyxxo/);
  expect(body).not.toHaveTextContent("before Dropwatch saved");
  await u.click(btn);
  expect(body).not.toBeVisible();
});

test("a claim from before the details were saved shows its time and says why there's nothing more", async () => {
  renderHistory([detailed("2026-10-09T23:00:00Z", "Common 3", null, null)]);
  const u = userEvent.setup();
  await u.click(await screen.findByRole("button", { name: /EXFIL Brothers Day 2/ }));
  const li = document.querySelector(".hx-body li")!;
  expect(li.textContent).toMatch(/^Common 3\d\d:\d\d$/);
  expect(screen.getByText("Claimed before Dropwatch saved watch time and channel.")).toBeVisible();
  expect(document.querySelector(".hx-sum")).toBeNull(); // nothing known about the campaign either
});

test("a row uses the art saved with its claim, even when the miner knows no campaign for that game", async () => {
  renderHistory([{ ...detailed("2026-10-10T13:00:00Z", "Rare 1", 120, "honeyxxo"), game: "Escape from Tarkov",
    box_art_url: "https://static-cdn.jtvnw.net/ttv-boxart/491931_IGDB-{width}x{height}.jpg" }]);
  const btn = await screen.findByRole("button", { name: /EXFIL Brothers Day 2/ });
  expect(btn.querySelector("img.box")?.getAttribute("src")).toBe("https://static-cdn.jtvnw.net/ttv-boxart/491931_IGDB-144x192.jpg");
});
