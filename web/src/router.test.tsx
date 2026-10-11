import { act, render } from "@testing-library/react";
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
