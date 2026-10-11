import { connectLive } from "./live";

class FakeES {
  static last: FakeES;
  readyState = 1;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, ((e: MessageEvent) => void)[]>();
  closed = false;
  constructor(readonly url: string) {
    FakeES.last = this;
  }
  addEventListener(kind: string, fn: (e: MessageEvent) => void) {
    this.listeners.set(kind, [...(this.listeners.get(kind) ?? []), fn]);
  }
  emit(kind: string, data: unknown) {
    for (const fn of this.listeners.get(kind) ?? []) fn({ data: JSON.stringify(data) } as MessageEvent);
  }
  close() {
    this.closed = true;
  }
}

const open = (url: string) => new FakeES(url) as unknown as EventSource;

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test("a burst of events triggers one debounced re-fetch", () => {
  const onRefetch = vi.fn();
  const stop = connectLive({ onRefetch, onConnection: vi.fn(), open });
  FakeES.last.emit("progress", { minutes: 1 });
  FakeES.last.emit("refreshed", {});
  FakeES.last.emit("claimed", {});
  vi.advanceTimersByTime(499);
  expect(onRefetch).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(onRefetch).toHaveBeenCalledOnce();
  stop();
});

test("events are passed on with their data", () => {
  const onEvent = vi.fn();
  connectLive({ onRefetch: vi.fn(), onConnection: vi.fn(), onEvent, open });
  FakeES.last.emit("signin", { status: "done" });
  expect(onEvent).toHaveBeenCalledWith("signin", { status: "done" });
});

test("lost only after 15 s of errors, and recovery re-fetches", () => {
  const onConnection = vi.fn();
  const onRefetch = vi.fn();
  connectLive({ onRefetch, onConnection, open });
  FakeES.last.onerror?.();
  vi.advanceTimersByTime(14_999);
  expect(onConnection).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(onConnection).toHaveBeenLastCalledWith(false);
  FakeES.last.onopen?.();
  expect(onConnection).toHaveBeenLastCalledWith(true);
  vi.advanceTimersByTime(500);
  expect(onRefetch).toHaveBeenCalledOnce();
});

test("a blip shorter than 15 s is never reported", () => {
  const onConnection = vi.fn();
  connectLive({ onRefetch: vi.fn(), onConnection, open });
  FakeES.last.onerror?.();
  vi.advanceTimersByTime(5_000);
  FakeES.last.onopen?.();
  vi.advanceTimersByTime(20_000);
  expect(onConnection).not.toHaveBeenCalled();
});

test("a closed stream is reopened after 5 s", () => {
  connectLive({ onRefetch: vi.fn(), onConnection: vi.fn(), open });
  const first = FakeES.last;
  first.readyState = 2;
  first.onerror?.();
  vi.advanceTimersByTime(5_000);
  expect(FakeES.last).not.toBe(first);
});

test("a closed stream asks whether the page is still signed in", () => {
  // the browser closes an EventSource on a 401 without saying why: an expired page session must
  // end at the sign-in screen, not 15 s later at "Can't reach the miner"
  const onClosed = vi.fn();
  connectLive({ onRefetch: vi.fn(), onConnection: vi.fn(), onClosed, open });
  FakeES.last.onerror?.();
  expect(onClosed).not.toHaveBeenCalled(); // a blip the browser retries itself
  FakeES.last.readyState = 2;
  FakeES.last.onerror?.();
  expect(onClosed).toHaveBeenCalledOnce();
});

test("stop closes the stream and cancels timers", () => {
  const onRefetch = vi.fn();
  const stop = connectLive({ onRefetch, onConnection: vi.fn(), open });
  FakeES.last.emit("state", {});
  stop();
  vi.advanceTimersByTime(1_000);
  expect(onRefetch).not.toHaveBeenCalled();
  expect(FakeES.last.closed).toBe(true);
});
