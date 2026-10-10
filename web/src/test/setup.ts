import "@testing-library/jest-dom/vitest";

/* jsdom has no EventSource; components that open the live stream get this inert stand-in. */
class InertEventSource {
  readyState = 1;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly url: string) {}
  addEventListener() {}
  close() {}
}
if (!("EventSource" in globalThis)) {
  (globalThis as unknown as { EventSource: unknown }).EventSource = InertEventSource;
}
