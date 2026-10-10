import { layoutTrack, milestones, type Milestone } from "./Track";

/* jsdom has no layout: give the track a width and each piece a size from its class and content. */
function sized(width: number) {
  const t = document.createElement("div");
  document.body.appendChild(t);
  Object.defineProperty(t, "offsetWidth", { value: width, configurable: true });
  return t;
}
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get(this: HTMLElement) {
      if (this.classList.contains("ms-art")) return 8 + this.querySelectorAll("img").length * 36;
      if (this.classList.contains("ms-lab") || this.classList.contains("ms-more")) return (this.textContent ?? "").length * 7;
      return 0;
    },
  });
});

const item = (n: string) => ({ name: n, image: `https://img/${n}` });
const ten: Milestone[] = [15, 30, 45, 60, 90, 120, 150, 180, 240, 300].map((at, i) => ({ at, items: [item(`r${i}`)] }));

test("a track wide enough for every reward places them all (15-min marks need 50 px each)", () => {
  const t = sized(1100);
  layoutTrack(t, ten, 70, 300, 4);
  expect(t.querySelectorAll(".ms-art")).toHaveLength(10);
  expect(t.querySelector(".ms-more")).toBeNull();
});

test("narrow track goes compact: next and final art only, earned merged, +N more", () => {
  const t = sized(340);
  layoutTrack(t, ten, 70, 300, 4);
  const arts = [...t.querySelectorAll(".ms-art")];
  expect(arts).toHaveLength(2);
  expect(arts.some((a) => a.classList.contains("next"))).toBe(true);
  expect(t.querySelectorAll(".ms-dot.got")).toHaveLength(1);
  // the "4 earned" label is placed after next/final, so it yields to them when they collide (by design)
  expect(t.querySelector(".ms-more")?.textContent).toBe("+4 more");
});

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
