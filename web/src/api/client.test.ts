import { ApiError, api, setUnauthorizedHandler } from "./client";

function reply(status: number, body?: unknown) {
  return vi.fn(async () =>
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: body === undefined ? {} : { "content-type": "application/json" },
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a 401 tells the app to show sign-in and throws", async () => {
  const seen = vi.fn();
  setUnauthorizedHandler(seen);
  vi.stubGlobal("fetch", reply(401, { detail: "Sign in to this page first." }));
  await expect(api.get("/state")).rejects.toMatchObject({ status: 401, message: "Sign in to this page first." });
  expect(seen).toHaveBeenCalledOnce();
});

test("a wrong password at /login is an error, not a sign-out", async () => {
  const seen = vi.fn();
  setUnauthorizedHandler(seen);
  vi.stubGlobal("fetch", reply(401, { detail: "Wrong password." }));
  await expect(api.post("/login", { password: "x" })).rejects.toBeInstanceOf(ApiError);
  expect(seen).not.toHaveBeenCalled();
});

test("422 validation message is surfaced", async () => {
  vi.stubGlobal("fetch", reply(422, { detail: [{ msg: "Input should be greater than or equal to 1" }] }));
  await expect(api.post("/pause", { minutes: 0 })).rejects.toThrow("greater than or equal to 1");
});

test("204 resolves to undefined and JSON bodies parse", async () => {
  vi.stubGlobal("fetch", reply(204));
  await expect(api.post("/resume")).resolves.toBeUndefined();
  vi.stubGlobal("fetch", reply(200, { ok: true }));
  await expect(api.get("/health")).resolves.toEqual({ ok: true });
});
