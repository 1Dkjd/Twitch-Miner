// noVNC ships no types; only what the Twitch sign-in window uses (views/TwitchLogin.tsx)
declare module "@novnc/novnc" {
  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: { wsProtocols?: string[] });
    scaleViewport: boolean;
    focusOnClick: boolean;
    background: string;
    sendKey(keysym: number, code: string | null, down?: boolean): void;
    focus(): void;
    disconnect(): void;
  }
}
