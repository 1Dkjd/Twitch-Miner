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
import { applyTheme, savedTheme } from "./ui/theme";

export function App() {
  useEffect(() => applyTheme(savedTheme()), []);
  return (
    <AppProvider>
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

function Shell() {
  const { me, announcement } = useApp();
  const view = useView();
  let body: ReactNode;
  let tabs = false;
  if (!me) body = null;
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
