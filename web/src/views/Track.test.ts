import { milestones } from "./Track";

test("milestones come from drops, grouped by minutes", () => {
  const r = (n: string) => ({ name: n, image_url: `u/${n}` });
  const got = milestones([
    { required_minutes: 60, current_minutes: 60, claimed: true, rewards: [r("a"), r("b")] },
    { required_minutes: 180, current_minutes: 70, claimed: false, rewards: [r("c")] },
    { required_minutes: 180, current_minutes: 70, claimed: false, rewards: [r("d")] },
  ]);
  expect(got.ms.map((m) => [m.at, m.items.length])).toEqual([[60, 2], [180, 2]]);
  expect(got).toMatchObject({ watched: 70, max: 180, nextIdx: 1 });
});
