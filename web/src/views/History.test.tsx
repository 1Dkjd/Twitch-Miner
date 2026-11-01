import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProvider } from "../store";
import { mockApi } from "../test/fetch";
import { state } from "../test/fixtures";
import { HistoryView, RewardsPerDay, groupByDay, rewardBars } from "./History";

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
  const stats = await screen.findByRole("region", { name: "Last 30 days" });
  expect(within(stats).getByText("rewards claimed").previousSibling).toHaveTextContent("2");
  expect(within(stats).getByText("campaigns").previousSibling).toHaveTextContent("2");
  await userEvent.click(within(screen.getByRole("group", { name: "Time period" })).getByRole("button", { name: "90 days" }));
  expect(screen.getByRole("button", { name: "90 days" })).toHaveAttribute("aria-pressed", "true");
  expect(calls.some((c) => c.path === "/api/history?days=90")).toBe(true);
  vi.unstubAllGlobals();
});

const detailed = (at: string, name: string, minutes: number | null, channel: string | null) => ({
  at, campaign_id: "c9", campaign: "EXFIL Brothers Day 2", game: "Escape from Tarkov", rewards: [r(name)],
  minutes, channel, campaign_rewards: minutes === null && channel === null ? null : 10,
  // relative to now: an absolute date here went stale on 2026-10-11 and flipped "ends" to "ended"
  campaign_ends: minutes === null && channel === null ? null : new Date(Date.now() + 3 * 86_400_000).toISOString(),
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
  expect(body).toHaveTextContent(/campaign ends \w{3} \d{1,2} \w{3}, /);
  const lines = [...body.querySelectorAll("li")].map((li) => li.textContent);
  expect(lines[0]).toMatch(/^Common 1after 1\sh watched·on honeyxxo\d{1,2}:\d\d(\s?[AP]M)?$/); // oldest first
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
  expect(li.textContent).toMatch(/^Common 3\d{1,2}:\d\d(\s?[AP]M)?$/);
  expect(screen.getByText("Claimed before Dropwatch saved watch time and channel.")).toBeVisible();
  expect(document.querySelector(".hx-sum")).toBeNull(); // nothing known about the campaign either
});

test("a row uses the art saved with its claim, even when the miner knows no campaign for that game", async () => {
  renderHistory([{ ...detailed("2026-10-10T13:00:00Z", "Rare 1", 120, "honeyxxo"), game: "Escape from Tarkov",
    box_art_url: "https://static-cdn.jtvnw.net/ttv-boxart/491931_IGDB-{width}x{height}.jpg" }]);
  const btn = await screen.findByRole("button", { name: /EXFIL Brothers Day 2/ });
  expect(btn.querySelector("img.box")?.getAttribute("src")).toBe("https://static-cdn.jtvnw.net/ttv-boxart/491931_IGDB-144x192.jpg");
});

const miss = (id: string, name: string, game: string, reason: string, over = {}) => ({
  campaign_id: id, name, game, box_art_url: "", link_url: `https://link/${id}`, ends_at: "2026-10-10T14:59:00Z", reason,
  rewards: [{ name: `${name} reward`, image_url: `u/${id}`, claimed: false }], rewards_total: 3, rewards_claimed: 0,
  minutes_watched: 0, started: false, priority: false, pinned: false, ...over,
});

function renderMissed(missed: unknown[], claims: unknown[] = []) {
  mockApi({ "GET /api/state": state(), "GET /api/history": { total_rewards: claims.length, claims, missed } });
  render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}><HistoryView /></AppProvider>);
}

test("Missed lists campaigns that mattered with their reason, and folds the rest away", async () => {
  renderMissed([
    miss("er", "ER ESPORTS DROPS", "Eternal Return", "not_linked", { minutes_watched: 60, started: true }),
    miss("q", "October Drops", "The Quinfall", "ran_out_of_time", { started: true, rewards_total: 2 }),
    miss("albion", "Dragonfire 6 - #6/7", "Albion Online", "outranked", { priority: true }),
    miss("rise", "Mobile Drop 183", "Rise Online", "never_list"),
    miss("x", "Some campaign", "Some game", "outranked"),
    miss("y", "Another one", "Other game", "no_live_channels"),
  ]);
  const sec = (await screen.findByRole("heading", { name: "Missed" })).closest("section") as HTMLElement;
  expect([...sec.querySelectorAll(".list > .row .row-t")].map((e) => e.textContent)).toEqual(
    ["ER ESPORTS DROPS", "October Drops", "Dragonfire 6 - #6/7"]);
  const er = within(sec).getByText("ER ESPORTS DROPS").closest(".row") as HTMLElement;
  expect(within(er).getByText("Account not linked")).toHaveClass("chip", "red");
  expect(er).toHaveTextContent(/Twitch counted 1\sh but won't give rewards until Eternal Return is linked/);
  expect(within(er).getByRole("link", { name: "Link account" })).toHaveAttribute("href", "https://link/er");
  expect(within(sec).getByRole("button", { name: /Skipped on purpose · 1/ })).toBeInTheDocument();
  expect(within(sec).getByRole("button", { name: /Never started · 2/ })).toBeInTheDocument();
  expect(screen.getByText(/3 campaigns/)).toBeInTheDocument(); // the lead counts the full rows
});

test("the History filter narrows claimed and missed alike", async () => {
  renderMissed([miss("er", "ER ESPORTS DROPS", "Eternal Return", "not_linked", { started: true }),
    miss("q", "October Drops", "The Quinfall", "ran_out_of_time", { started: true })],
  [claim("2026-10-10T15:00:00Z", "c1", "Palcat Glasses")]);
  const u = userEvent.setup();
  await screen.findByRole("heading", { name: "Missed" });
  await u.type(screen.getByRole("searchbox", { name: "Filter History" }), "quinfall");
  expect(screen.queryByText("ER ESPORTS DROPS")).toBeNull();
  expect(screen.getByText("October Drops")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Claimed" })).toBeNull(); // C-c1 / Palia doesn't match
});

test("stats: watch time per campaign is its longest claimed drop, rewards by game, missed by reason", async () => {
  const c = (at: string, cid: string, game: string, minutes: number | null) =>
    ({ at, campaign_id: cid, campaign: `C-${cid}`, game, rewards: [r(`${cid}-${at}`)], minutes });
  const missed = (id: string, reason: string) => ({ campaign_id: id, name: id, game: "Palia", box_art_url: "", link_url: "",
    ends_at: "2026-10-09T12:00:00Z", reason, rewards: [], rewards_total: 3, rewards_claimed: 0, minutes_watched: 30,
    started: true, priority: false, pinned: false });
  mockApi({ "GET /api/state": state(), "GET /api/history": { total_rewards: 4, claims: [
    c("2026-10-10T15:00:00Z", "a", "Escape from Tarkov", 600), c("2026-10-10T14:00:00Z", "a", "Escape from Tarkov", 240),
    c("2026-10-10T13:00:00Z", "b", "Escape from Tarkov", 60), c("2026-10-09T13:00:00Z", "d", "ARC Raiders", 120),
  ], missed: [missed("m1", "not_linked"), missed("m2", "outranked"), missed("m3", "not_linked")] } });
  render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}><HistoryView /></AppProvider>);
  const stats = await screen.findByRole("region", { name: "Last 30 days" });
  expect(within(stats).getByText("rewards claimed").previousSibling).toHaveTextContent("4");
  expect(within(stats).getByText("campaigns").previousSibling).toHaveTextContent("3");
  // 600 (not 600 + 240: drop times count from the campaign's start) + 60 + 120 = 13 h
  expect(within(stats).getByText(/of watching/).previousSibling).toHaveTextContent("13 h");
  const games = within(stats).getByRole("list", { name: "Rewards by game" });
  expect(within(games).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Escape from Tarkov3", "ARC Raiders1"]);
  const reasons = within(stats).getByRole("list", { name: "Missed, by reason" });
  expect(within(reasons).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Account not linked2", "Other campaigns came first1"]);
  vi.unstubAllGlobals();
});

test("stats: watch time says so when older claims didn't record it", async () => {
  mockApi({ "GET /api/state": state(), "GET /api/history": { total_rewards: 2, claims: [
    { ...claim("2026-10-10T15:00:00Z", "a", "x"), minutes: 120 }, { ...claim("2026-10-01T15:00:00Z", "b", "y"), minutes: null },
  ] } });
  render(<AppProvider initialMe={{ authenticated: true, setup_required: false }}><HistoryView /></AppProvider>);
  const stats = await screen.findByRole("region", { name: "Last 30 days" });
  expect(within(stats).getByText(/of watching/).previousSibling).toHaveTextContent("2 h+");
  vi.unstubAllGlobals();
});

test("rewards per day counts the viewer's days, with empty days included", () => {
  const today = new Date().toISOString();
  render(<RewardsPerDay days={3} claims={[{ at: today, campaign_id: "a", campaign: "A", game: "G", rewards: [r("x"), r("y")] }]} />);
  const chart = screen.getByRole("img", { name: /^Rewards per day/ });
  expect(chart.getAttribute("aria-label")!.endsWith(" 2")).toBe(true);
  expect(chart.querySelectorAll("b")).toHaveLength(3);
  expect([...chart.querySelectorAll("b")].map((b) => b.textContent)).toEqual(["0", "0", "2"]);
});

test("long periods group the chart into weeks and months", () => {
  const now = new Date(2026, 9, 31, 12);
  const at = (d: Date) => ({ at: d.toISOString(), campaign_id: "a", campaign: "A", game: "G", rewards: [r("x")] });
  const claims = [at(new Date(2026, 9, 30)), at(new Date(2026, 9, 1)), at(new Date(2026, 0, 15))];
  expect(rewardBars(claims, 30, now).unit).toBe("day");
  expect(rewardBars(claims, 30, now).bars).toHaveLength(14);
  const weeks = rewardBars(claims, 90, now);
  expect(weeks.unit).toBe("week");
  expect(weeks.bars).toHaveLength(13);
  expect(weeks.bars.at(-1)!.n).toBe(1);
  const months = rewardBars(claims, 365, now);
  expect(months.unit).toBe("month");
  expect(months.bars.map((b) => b.n)).toEqual([0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2]); // Nov 2025 to Oct 2026
});
