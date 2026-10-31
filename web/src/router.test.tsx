import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import { parseSub, parseView, useView } from "./router";

function Views() {
  const v = useView();
  return (
    <>
      {["overview", "history"].map((n) => (
        <h1 key={n} id={`h-${n}`} tabIndex={-1} hidden={v !== n}>
          {n}
        </h1>
      ))}
    </>
  );
}

test("unknown hashes fall back to Overview", () => {
  expect(parseView("#nope")).toBe("overview");
  expect(parseView("#history")).toBe("history");
  expect(parseView("#connect")).toBe("connect");
});

test("a sub-route after the view keeps the view and is read separately", () => {
  expect(parseView("#settings/backup")).toBe("settings");
  expect(parseSub("#settings/backup")).toBe("backup");
  expect(parseSub("#settings")).toBe("");
  expect(parseView("#nope/backup")).toBe("overview");
});

test("navigation moves focus to the view heading and sets the title; first load does not", () => {
  location.hash = "#overview";
  render(<Views />);
  expect(document.activeElement).toBe(document.body);
  expect(document.title).toBe("Overview · Dropwatch");
  act(() => {
    location.hash = "#history";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  expect(document.activeElement?.id).toBe("h-history");
  expect(document.title).toBe("History · Dropwatch");
});

test("phones get four tabs and More; More opens the other two", async () => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("720"), addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("fetch", vi.fn(async (u: string) => new Response(JSON.stringify(String(u).includes("/me") ? { authenticated: true, setup_required: false } : {}), { status: String(u).includes("/me") ? 200 : 404 })));
  location.hash = "#overview";
  render(<App />);
  const nav = await screen.findByRole("navigation", { name: "Views" });
  expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(["Overview", "Priorities", "Inventory", "History"]);
  await userEvent.click(within(nav).getByRole("button", { name: "More" }));
  await userEvent.click(within(nav).getByRole("menuitem", { name: "Activity" }));
  expect(location.hash).toBe("#activity");
  vi.unstubAllGlobals();
});
