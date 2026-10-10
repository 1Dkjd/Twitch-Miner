# Dropwatch Phase 3 (Web UI) Plan

**Goal:** The approved Mining-look page, served by `dropwatch serve` at `/`, driving the real API. It covers first-run setup, Twitch code sign-in, Overview, Priorities, History and Settings.

**Visual spec:**
- `docs/design/approved-mockup-v7.html`, the Mining (`ore`) look only.
- `docs/design/signin-options.html`, option A (code sign-in, signed-out banner, catalogue banner).
- `docs/design/signin-mockup.html` (page password setup and sign-in).

**Spec:** `docs/superpowers/specs/2026-10-09-drops-miner-design.md` §8, §9, §11.

**Executor:** inline, worktree `../dropwatch-ui`, branch `phase3-ui` from `rename-dropwatch`.

**Format:** like phase 2b, this lists tasks, interfaces and failing tests, without full code. Each task is TDD, and there is a fresh review at the end.

## Decisions (declared)

1. **Stack:** React 19 + Vite + TypeScript (strict) + Tailwind 4, as the spec says.
   - The mockup's own stylesheet (tokens and the `ore` component classes) is ported **verbatim** into `web/src/styles/app.css` and stays the source of every approved visual.
   - Tailwind provides the reset and is used for new layout only. Re-expressing roughly 390 lines of tuned CSS as utilities would invite visual drift from the approved design.
2. **Fixed dark-first `ore` look.**
   - The Plain look and the mockup-controls bar are dropped (spec §11).
   - Theme is System, Light or Dark (Settings), stored in `localStorage`.
3. **Controls left out until their feature exists, rather than shown as broken promises:**
   - "Send test" (phase 4 adds `POST /api/notify/test`);
   - "Also claim channel points" (phase 4);
   - "Require a password" off-switch (no backend; the page password is always on);
   - History's missed-reward section (phase 4).
   - **The whole Notifications section** (added while building Task 8). The settings are stored, but nothing sends a notification until phase 4, so the switches would be a false promise.
4. **Added control:** Settings → Mining → **"Also mine badge and emote campaigns"** (`mine_badges`). The planner already uses it, but the mockup had no toggle for it.
5. **Reward and box art** load straight from Twitch's CDN. Box art gets the `-144x192` size inserted (both forms return 200). Spec §7's disk cache moves to phase 4.
6. **Live updates:**
   - One store, holding `GET /api/state`. The SSE events `state`, `refreshed`, `claimed`, `switched`, `needs_you`, `signin` and `progress` trigger a re-fetch; the re-fetch is debounced to 500 ms.
   - If the SSE stream fails for more than 15 s, the page shows **"Can't reach the miner"** with the last-known data, as in the mockup.
7. **Also declared after the review (2026-10-10):**
   - Tailwind is loaded **without its preflight reset**, because the mockup was tuned on browser defaults. Decision 1 said Tailwind provides the reset; it doesn't.
   - While a sign-in code is waiting, the Connect screen also polls `GET /api/twitch/signin` every 3 s as a fallback to SSE. Spec §11 says "no polling except the SSE reconnect"; this is a deliberate exception, and it is limited to that one screen.
   - Playwright is replaced by a live end-to-end check in the browser pane against the real server.
8. **Tests:**
   - Vitest and Testing Library cover components and logic.
   - One Playwright smoke run uses mocked `/api` routes (`page.route`) instead of the spec's "API fake mode", so it needs no second server.

## Backend gaps (Task 1)

- `CurrentOut.channels`: the other live channels that qualify for the current campaign. The "change" picker needs them, and the planner's qualifying rule is reused (`planner._qualifies`, made public as `qualifies`).
- `StateOut.last_switch: {from, to, at} | None`: drives the "went offline, switched to …" notice for 10 minutes after a switch.
- `StateOut.next_check_at`: drives the idle copy, "Checking again in N min".
- The FastAPI app serves `web/dist` at `/` (assets plus an SPA fallback to `index.html`) whenever that folder exists. `/api/*` is unaffected.
- **Tests first:**
  - `test_current_lists_alternative_channels`;
  - `test_last_switch_reported_then_expires`;
  - `test_next_check_at`;
  - `test_serves_index_and_assets`;
  - `test_spa_fallback_not_for_api`.

## Tasks

### Task 1: Backend gaps (above)

### Task 2: Scaffold `web/`
- Vite + React 19 + TS strict + Tailwind 4 (`@tailwindcss/vite`) + Vitest + Testing Library + jsdom.
- `npm run gen:api` runs `openapi-typescript ../docs/api/openapi.json -o src/api/types.ts`. `npm test` fails if `types.ts` is stale (it regenerates into a temp file and compares).
- The dev server proxies `/api` to `127.0.0.1:5810`.
- Fonts come from Google Fonts, as the mockup does (Archivo, Instrument Sans, Geist Mono).
- **Tests:** `types.freshness.test.ts`, plus `npm run build` producing `web/dist`.

### Task 3: Shell, styles, API client, store
- `app.css`: the verbatim port of the mockup CSS, `ore` only. The tokens keep the mockup's light/dark structure, plus the classes from the two sign-in mockups.
- `Icons.tsx`: the SVG sprite from the mockup.
- `api/client.ts`: typed `get`/`post`/`put`/`del`. On a 401, it clears the auth state and shows the login screen.
- `store.ts`: `useApp()` (React context + reducer), holding `me`, `state`, `lists`, `settings` and `connection: live|lost`.
- `useEvents()`: an EventSource with reconnect, the debounced re-fetch, and lost-connection detection.
- Hash router (`#overview`, `#priorities`, `#history`, `#settings`). Focus moves to the view's heading on navigation, and the title is `<View> · Dropwatch`.
- **Tests:**
  - `client.401.test`;
  - `events.refetch-debounce.test`;
  - `events.lost-after-15s.test` (fake timers);
  - `router.focus.test`.

### Task 4: First run and sign-in
- Setup (page password with live checks), page sign-in (wrong-password error), and the Twitch code flow: Ready → Code (copy, open link, QR with the `qrcode` package as an inline SVG, countdown) → Expired → Connected.
- The signed-out banner on Overview opens the code flow.
- **Tests:**
  - `setup.checks.test` (button disabled until 8+ characters and both match);
  - `login.error.test`;
  - `signin.code.test` (POST returns the code, it is shown, SSE `done` → Connected);
  - `signin.expired.test`.

### Task 5: Overview
- Banners: paused (Resume now), signed-out, can't-reach, catalogue (stale/unreachable, from `state.catalog`).
- **Mining now** card:
  - box art and blurred backdrop;
  - title, state chip, channel with ★ favourite;
  - a **change** button opening a picker of `current.channels` → `POST /api/channel`;
  - the switch notice (`last_switch`);
  - the **track** (port of `layoutTrack`, including compact mode and the ResizeObserver);
  - next-reward card and "Show all N rewards";
  - watched count and deadline bar (`verdict`);
  - the Pause menu (30 min / 1 h / 4 h / until I resume) with full keyboard behaviour.
- **Idle** card: first in line, next check time, and a **Check now** button that calls `POST /api/refresh`.
  - Added: a tiny endpoint calling `runner.refresh(force_campaigns=True)`.
  - This is the one extra backend item, tested in Task 1.
- **Needs you:**
  - link account (opens `link_url`) and Never mine (`PUT /api/lists`);
  - "may need linking" copy with a **Mine now** retry (`maybe_unlinked`);
  - first in the DOM on phones (at most 720 px).
- **Up next:** mini progress and Mine now.
- **Done:** collapsible, with claimed art.
- **Tests:**
  - `track.layout.test` (normal vs compact at a narrow width; next and final art always placed);
  - `deadline.test`;
  - `pausemenu.keyboard.test`;
  - `needs-first-on-phone.test`;
  - `nowcard.switch-notice.test`.

### Task 6: Priorities
- Three buckets (Priority, Favourite channels, Never). Up/down buttons, drag and drop, and add boxes with suggestions plus "Add anyway".
- Saving is `PUT /api/lists`, optimistic, rolled back with a message on a 422.
- Moves are announced in the live region, and focus stays on the moved row.
- **Tests:**
  - `priorities.move-focus.test`;
  - `priorities.add-unknown-confirm.test`;
  - `priorities.never-clash-rollback.test`.

### Task 7: History
- Period select (30 / 90 / 365 days). The summary line reads "N rewards claimed from M campaigns".
- Days are grouped in the **viewer's local time** (the API returns UTC). Rows group campaigns by day, with art and a "claimed HH:MM–HH:MM" range.
- **Tests:** `history.local-day-grouping.test`, which pins the time zone so 23:30 UTC lands on the local next or previous day correctly.

### Task 8: Settings
- Twitch account (signed in as … ; Sign out with inline confirm → `POST /api/twitch/signout`).
- Notifications (target + three toggles, saved on change/blur via `PUT /api/settings`).
- Mining (the badges toggle).
- This page (Theme; **Sign out of this page** → `POST /api/logout`).
- **Tests:** `settings.signout-confirm.test`, `settings.toggle-saves.test`.

### Task 9: Gate
1. Vitest, `tsc --noEmit`, `npm run build`, pytest, ruff. Then a Playwright smoke run with mocked API routes: first run → code → Overview → Priorities move → History → Settings.
2. A fresh whole-branch review, against the mockup and these declared decisions. Then impeccable `audit` on the built page.
3. **Live:**
   1. Rebuild, then restart `serve` from this branch on the real data.
   2. Nick opens `http://127.0.0.1:5810`. He sets his page password and checks every view against the mockup, with real campaigns.
   3. His visual verdict is the gate.
