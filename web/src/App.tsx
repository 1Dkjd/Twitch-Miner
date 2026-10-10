import { useEffect, type ReactNode } from "react";
import { type View, useView } from "./router";
import { ConnectScreen } from "./screens/Connect";
import { LoginScreen, SetupScreen } from "./screens/PagePassword";
import { AppProvider, useApp } from "./store";
import { Icon, IconSprite, type IconName } from "./ui/Icons";
import { HistoryView } from "./views/History";
import { OverviewView } from "./views/Overview";
import { PrioritiesView } from "./views/Priorities";
import { SettingsView } from "./views/Settings";
import { clock } from "./ui/format";
import { applyTheme, savedTheme } from "./ui/theme";

export function App({ retryMs }: { retryMs?: number } = {}) {
  useEffect(() => applyTheme(savedTheme()), []);
  return (
    <AppProvider retryMs={retryMs}>
      <IconSprite />
      <Shell />
    </AppProvider>
  );
}

const TABS: [Exclude<View, "connect">, string, IconName][] = [
  ["overview", "Overview", "home"], ["priorities", "Priorities", "list"], ["history", "History", "clock"], ["settings", "Settings", "gear"],
];

/** The status pill: what the miner is doing, never contradicting the banner below it. */
export function pillFor(state: string | undefined, lost: boolean): [string, string] {
  if (lost) return ["alert", "Miner unreachable"];
  switch (state) {
    case "mining": case "switched": return ["ok", "Mining"];
    case "paused": return ["paused", "Paused"];
    case "signed_out": return ["alert", "Signed out"];
    case "twitch_unreachable": return ["alert", "Can't reach Twitch"];
    case "idle": return ["muted", "Idle"];
    default: return ["muted", "Starting"];
  }
}

function TopBar({ view, tabs }: { view: View; tabs: boolean }) {
  const { state, connection } = useApp();
  const [tone, label] = pillFor(state?.state, connection === "lost");
  return (
    <header className="bar">
      <div className="bar-in">
        <div className="brand"><svg aria-hidden="true"><use href="#i-pick" /></svg>Dropwatch</div>
        {tabs && (
          <nav className="tabs" aria-label="Views">
            {TABS.map(([v, name, icon]) => (
              <a key={v} href={`#${v}`} aria-current={view === v ? "page" : undefined}><Icon name={icon} />{name}</a>
            ))}
          </nav>
        )}
        {tabs && <span className="pill" role="status" data-tone={tone}><span className="dot" aria-hidden="true" />{label}</span>}
      </div>
    </header>
  );
}

/** Shown when the page can't reach the miner at all (it retries every few seconds by itself). */
function MinerDown() {
  const { lostSince, refreshMe } = useApp();
  return (
    <div className="view">
      <div className="banner" data-tone="alert" role="alert"><Icon name="cloud" />
        <div><div className="banner-t">Can't reach the miner</div>
          <div className="banner-b">No answer{lostSince ? ` since ${clock(lostSince)}` : ""}. This page keeps trying by itself. If it stays like this, check that Dropwatch is running.</div></div>
        <div className="banner-acts"><button className="btn" type="button" onClick={() => void refreshMe().catch(() => undefined)}>Retry now</button></div>
      </div>
    </div>
  );
}

function Shell() {
  const { me, announcement, connection } = useApp();
  const view = useView();
  useEffect(() => {
    if (me?.setup_required) document.title = "Set up · Dropwatch";
    else if (me && !me.authenticated) document.title = "Sign in · Dropwatch";
  }, [me]);
  let body: ReactNode;
  let tabs = false;
  if (!me) body = connection === "lost" ? <MinerDown /> : null;
  else if (me.setup_required) body = <SetupScreen />;
  else if (!me.authenticated) body = <LoginScreen />;
  else if (view === "connect") body = <ConnectScreen />;
  else {
    tabs = true;
    body = view === "priorities" ? <PrioritiesView /> : view === "history" ? <HistoryView />
      : view === "settings" ? <SettingsView /> : <OverviewView />;
  }
  return (
    <>
      <TopBar view={view} tabs={tabs} />
      <main className="wrap">
        <div id="live" className="sr" aria-live="polite">{announcement}</div>
        {body}
      </main>
    </>
  );
}
