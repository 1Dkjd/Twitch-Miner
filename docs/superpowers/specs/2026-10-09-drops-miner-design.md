# Drops Miner: design

Date: 2026-10-09 · Status: draft for review

## 1. Purpose

Drops Miner replaces the `dungfu/twitch-drops-miner` container on Nick's Unraid server. It earns timed
Twitch drops (in-game rewards) for one Twitch account without anyone watching streams. It tells Twitch
that the account watched a stream for a minute, once a minute, on one channel at a time. It claims each
reward when it is earned, and switches channel when a stream ends or a more important campaign comes up.

The existing container works but its UI is disliked. Its code is a 1,600-line core that is coupled to
its GUI. This project keeps the Twitch knowledge and replaces the rest.

**Users.** One person, the owner, who checks the page now and then from a desktop browser or a phone.

**Success.**
- It mines and claims drops on Nick's account for days with no babysitting.
- It discovers new campaigns by itself.
- The page behaves like the approved mockup.
- When something needs Nick (an unlinked game account, an expired sign-in), the page says so and a
  notification reaches him.

## 2. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Relationship to the original | Port the Twitch logic into a new, cleanly separated Python app | The hard part is Twitch knowledge (query IDs, login, the watch heartbeat), and it is Python. Wrapping upstream would keep its GUI-coupled core. |
| Language | Python 3.12, asyncio | The port is near line-for-line. The workload is waiting on the network. Nick already maintains Python apps. |
| Audience | Private GitHub repo `drops-miner`, Nick's Unraid only | It can go public later. |
| Frontend | React + Vite + Tailwind, TypeScript | The same stack as homelab-dashboard. TypeScript types are generated from the API's OpenAPI schema. |
| Twitch sign-in | Browser sign-in that obtains an Android-app token (the fork's method) | See section 4. The only verified way to get a token that can also list campaigns. |
| Scheduling | Priority games first in list order, then everything else least-spare-time first; Never list excluded; favourite channels break ties | Agreed during the mockup rounds. Priority is not a whitelist. |
| UI | Approved mockup v7, Mining look | `docs/design/approved-mockup-v7.html`, also https://claude.ai/artifact/1C2ggUHkgriumwXYtQo8Qc |

**Licensing.** DevilXD/TwitchDropsMiner and fireph/TwitchDropsMiner are both MIT. Ported code keeps
their copyright notices in `NOTICE`. No code is copied from anything that isn't MIT-licensed.

## 3. How Twitch drops mining works (facts the design relies on)

These come from the reference code: fireph/TwitchDropsMiner `webui` branch, a fork of
DevilXD/TwitchDropsMiner. They were checked on 2026-10-08 and 2026-10-09.

- **One channel at a time.** Twitch tracks one current drop session per account. The original keeps a
  single `watching_channel`. Its README warns that watching anything else on the same account confuses
  progress. One stream can still advance several campaigns for the same game when the channel qualifies
  for all of them.
- **The heartbeat.** Every 59 s (`WATCH_INTERVAL`) it POSTs a `minute-watched` event to the channel's
  "spade" analytics URL, which it scrapes from the channel page (`channel.py`: `send_watch`,
  `spade_payload`). Success is HTTP 204. No video is downloaded.
- **Progress stalls.** When progress stops arriving for about a minute, the original asks GQL
  `DropCurrentSessionContext` (`CurrentDrop`) for the true minutes.
- **Live updates.** Twitch PubSub websockets: up to 8 connections × 50 topics. They carry user drop
  events (progress, claim available), notifications, and channel stream up/down plus title or game
  changes.
- **Discovery and inventory.** GQL persisted queries:
  - `ViewerDropsDashboard`: all campaigns.
  - `Inventory`: the account's campaigns in progress and their claimed state.
  - `CampaignDetails`.
- **Claiming.** GQL `DropsPage_ClaimDropRewards`.
- **Channel choice in the original.** Within the same game priority, a channel on the campaign's own
  allowed list beats a general one (`should_switch`, `acl_based`).

The exact query hashes and headers are ported from the reference `constants.py`, with attribution.

## 4. Twitch sign-in (the decisive constraint)

Spike results, run on Nick's account on 2026-10-09 (read-only, throwaway code):

| Method | Result |
|---|---|
| Device-code login, Android app client (`kd1unb4b…`) | Fails: HTTP 400 `invalid client`. Twitch removed it around 2026-09-18 (upstream issue DevilXD#1165). |
| Device-code login, Android TV client (`ue6666qo…`) | Works. The token validates, and `Inventory` returns the 3 campaigns in progress. |
| `ViewerDropsDashboard` with the TV token | Returns `dropCampaigns: null`, so there is no discovery. This matches DevilXD's comment on #1165. |
| Heartbeat and claim with the TV token | Not tested. The spike was read-only. |

**Chosen method: browser sign-in with Android delegation**, as fireph's `webui/browser_login.py` does it.
It is proven by Nick's running container, which lists campaigns he never started.

1. When the owner presses **Sign in to Twitch**, the server starts Chromium in a virtual display (Xvfb)
   on `twitch.tv/login`. It streams the browser to the page through noVNC, proxied over the app's own
   port.
2. The owner signs in on the real Twitch page, including 2FA.
3. The automation (CDP) intercepts the POST to `passport.twitch.tv/protected_login` (and `/shim`). It
   sets `client_id` to the WEB client and `delegate_client_id` to the Android app client, so Twitch
   issues an **Android-app token**.
4. The server checks the token with `id.twitch.tv/oauth2/validate`. It accepts it only if the client ID
   is the Android app's. Then it stores the token and closes the browser.
5. Chromium and the virtual display run only during sign-in. They stay up until sign-in finishes or the
   owner presses Cancel. They also close if no page has been watching the sign-in for 10 minutes. There
   is no timer on the owner's typing.

The Android token is used for everything else: GQL, PubSub, heartbeat and claims. The original and the
fork both run that way today.

**Swappable.** `twitch/auth` exposes one interface: `SessionProvider.sign_in()`, which returns a
`TwitchSession` (token, client info, device id, user id). If browser sign-in breaks, a TV-code provider
can replace it. That would also need a campaign source other than `ViewerDropsDashboard`, which is out of
scope for v1.

**UI consequence.** The approved mockup's "sign-in expired" banner shows a device code. That flow no
longer applies. The banner needs a **Sign in to Twitch** button that opens the embedded browser view.
The first-run screens (set the page password, then sign in to Twitch) also don't exist in the mockup yet.
**Both get a mockup round before they are built.**

## 5. Architecture

```
            ┌──────────────┐  events   ┌───────────┐  SSE   ┌──────────┐
 Twitch ◀──▶│ twitch/*     │◀─────────▶│  runner   │───────▶│  api     │◀──▶ browser UI
            │ auth gql     │           │ (loop)    │        │ FastAPI  │
            │ pubsub watch │           └─────┬─────┘        └────┬─────┘
            └──────────────┘                 │ plan()            │
                                       ┌─────▼─────┐        ┌────▼─────┐
                                       │  planner  │        │  store   │ SQLite /data/drops.db
                                       │  (pure)   │        └────┬─────┘
                                       └───────────┘        ┌────▼─────┐
                                                            │  notify  │ ntfy / Discord
                                                            └──────────┘
```

Each unit has one job and a small interface. Nothing below `api` knows the UI exists.

| Unit | Job | Interface (sketch) | Depends on |
|---|---|---|---|
| `twitch/auth` | Get and keep a `TwitchSession` | `SessionProvider.sign_in() -> TwitchSession`; `validate(session) -> bool` | Chromium (only during sign-in) |
| `twitch/gql` | Persisted queries, rate limit, backoff, single retry on `service error` / `PersistedQueryNotFound` | `await gql.inventory()`, `.campaigns()`, `.campaign_details(ids)`, `.current_drop(channel_id)`, `.claim(drop_instance_id)`, `.claim_points(...)`, `.stream_info(logins)` | `TwitchSession` |
| `twitch/pubsub` | Websocket pool, topic subscribe/unsubscribe, reconnects | async iterator of typed events: `DropProgress`, `DropClaimable`, `StreamUp/Down`, `StreamChanged`, `PointsClaimable` | `TwitchSession` |
| `twitch/watch` | The minute heartbeat to one channel | `await watch.send(channel) -> bool` | `TwitchSession` |
| `models` | Plain dataclasses: Game, Campaign, Drop, Reward, Channel, Plan | none | none |
| `planner` | Decide what to mine and on which channel. **Pure:** no I/O, no clock reads | `plan(campaigns, live_channels, prefs, now) -> Plan` | `models` |
| `runner` | The loop: refresh, plan, watch, claim, switch, pause | emits `Event`s; commands: `pause(until)`, `resume()`, `mine_now(campaign_id)`, `switch_channel(login)`, `reload()` | everything above, `store` |
| `store` | SQLite persistence | functions per table (section 7) | `sqlite3` via `asyncio.to_thread` |
| `notify` | Send ntfy or Discord webhook messages | `await notify.send(kind, text)` | `store` (settings) |
| `api` | REST, SSE, page auth, sign-in proxy, serves the built UI | section 8 | `runner`, `store` |

Libraries: `aiohttp` (Twitch HTTP and websockets, as in the reference), `fastapi` + `uvicorn` (API and
SSE), `pydantic` (API models and OpenAPI), `argon2-cffi` (page password), `zendriver` (Chromium CDP, as in
the fork), Xvfb + x11vnc + noVNC/websockify (sign-in view). Tests: `pytest`, `pytest-asyncio`. Lint:
`ruff`.

## 6. The planner (the rules, exactly)

Inputs:
- campaigns, with drops, required and current minutes, start and end, the account-linked flag, and the
  allowed-channel list;
- live channels, with game, drops-enabled flag and viewers;
- preferences: Priority (an ordered list of games), Never (a set of games), Favourite channels (an
  ordered list);
- `now`.

1. **Eligible campaigns.** A campaign is eligible when:
   - it has started and not ended;
   - its account is linked;
   - its game is not on Never;
   - it still has an unclaimed drop that can be earned before it ends;
   - at least one live, drops-enabled channel qualifies for it (the allowed list if the campaign has
     one, otherwise any channel streaming that game).

   Campaigns that fail only on the linked flag become **Needs you** items.
2. **Order of eligible campaigns.**
   1. Games on Priority, in list order.
   2. Then all others, by **spare-time ratio** ascending:
      `ratio = minutes_until_end / minutes_still_needed`. The upstream code calls this "low availability
      first".
   3. Ties break on end time, then campaign id, so the order is deterministic.

   One stream can serve several campaigns of the same game, so the chosen campaign's game also credits
   its sibling campaigns. The planner records them in the Plan for display.
3. **Channel for the chosen campaign.**
   1. Favourite channels in list order.
   2. Then channels on the campaign's allowed list.
   3. Then any qualifying channel.

   Within each tier, the most viewers win. The reference sorts candidate channels by viewers,
   descending, before applying game priority (`twitch.py`, `_viewers_key`).
4. **Stickiness.** The runner does not switch channels when the new plan only differs in channel tier
   within the same campaign. It switches when:
   - the current channel goes offline or stops qualifying;
   - a higher-ranked campaign becomes eligible;
   - a favourite comes online for the current campaign.

   This mirrors the reference's `should_switch`.
5. **Output.** `Plan` contains:
   - `current` (campaign, channel, reason: priority n / most urgent / favourite / allowed-channel);
   - `queue` (the ordered eligible campaigns after it);
   - `needs_you` (unlinked, with the link URL when Twitch gives one);
   - `done` (open campaigns with everything claimed);
   - a deadline verdict per campaign: `ratio > 1` → "won't finish", `ratio > 0.5` → "tight",
     otherwise "plenty of time".

"Mine now" and "change channel" are **overrides** the runner holds until the overridden campaign or
channel stops being eligible. They are not planner inputs that persist forever.

## 7. Data (SQLite, `/data/drops.db`)

| Table | Holds |
|---|---|
| `settings` | key/value: notify target, notify toggles, claim channel points, page password hash, schema version |
| `priority` | `position, game_name` |
| `never` | `game_name` |
| `favourites` | `position, channel_login` |
| `session` | the Twitch session: token, client id, device id, user id, login. The file is `0600`; the token is never logged. |
| `claims` | `claimed_at, campaign_id, campaign_name, game, reward_name, image_url` |
| `campaign_snapshots` | latest known state per campaign: end time, linked flag, drops with minutes, `blocked_reasons` seen while live (e.g. "no qualifying channel online") |
| `ended_campaigns` | written once when a campaign ends: rewards got, missed, and a **missed reason** |
| `events` | a rolling log of runner events (last 7 days) for diagnosis |

**Missed-reward reasons**, decided at campaign end from the snapshot. Only for games not on Never:

1. **Claim failed:** a drop reached its minutes but every claim attempt failed (recorded errors).
2. **Account not linked:** the campaign was unlinked for its final snapshot.
3. **Channels offline:** the campaign has an allowed-channel list and none of those channels was live
   with drops on during the times it would have been mined.
4. **Ran out of time:** anything else, meaning it was minable but other campaigns ranked higher, or there
   wasn't enough time.

Reward images are referenced by Twitch's URL and cached on disk under `/data/cache` the first time the UI
asks for them.

## 8. API

All endpoints require the page session cookie, except login and first-run setup.

| Method and path | Purpose |
|---|---|
| `GET /api/state` | Snapshot for Overview: runner state, current plan, needs-you, up next, done, deadline verdicts |
| `GET /api/events` | SSE stream: `state`, `progress`, `claimed`, `switched`, `needs_you`, `signin` |
| `POST /api/pause` `{minutes \| null}` · `POST /api/resume` | Pause for a duration or until resumed |
| `POST /api/mine-now` `{campaign_id}` · `POST /api/channel` `{login}` | Overrides |
| `GET/PUT /api/lists` | Priority, Never, Favourites. PUT replaces all three atomically |
| `GET /api/suggestions` | Games with campaigns and channels seen, for the add boxes |
| `GET /api/history?days=30` | Claims grouped by day and campaign; ended campaigns with missed reasons |
| `GET/PUT /api/settings` · `POST /api/notify/test` | Settings and the "Send test" button |
| `POST /api/twitch/signin` · `DELETE /api/twitch/signin` · `GET /api/twitch/signin/vnc` (WebSocket) | Start, cancel, and view the sign-in browser |
| `POST /api/twitch/signout` | Forget the Twitch session |
| `POST /api/login` · `POST /api/logout` · `POST /api/setup` | Page password: first-run setup, sign-in, sign-out |

The OpenAPI schema generates `web/src/api/types.ts` (`openapi-typescript`). CI fails if the generated file
is stale.

## 9. Runner states

The runner reports exactly one state, and the UI renders it. The UI never infers state.

| State | Meaning | UI (mockup state) |
|---|---|---|
| `mining` | heartbeat succeeding | Mining now, normal |
| `switched` | the channel changed in the last few minutes (carries from/to) | "Streamer went offline" notice |
| `paused` | owner paused; carries `until` | Paused banner + dimmed card |
| `idle` | nothing eligible; carries the next check time and what's first in line | Nothing to mine |
| `signed_out` | no valid Twitch session | Sign-in banner (re-mocked, section 4) |
| `twitch_unreachable` | Twitch calls failing; carries the last success time | Can't reach Twitch |

"Can't reach the miner" (UI ↔ API) is detected by the **page** when the SSE stream drops. It is the one
state the page determines itself, because the server can't report its own absence.

Error handling:
- Every Twitch call goes through backoff (the reference's `ExponentialBackoff`, 60 s cap).
- 401 from `validate` → `signed_out` and a notification.
- PubSub reconnects per connection.
- Heartbeat failures retry next minute.
- Three consecutive failures on a channel → re-plan.

## 10. Notifications

The target is one URL: an ntfy topic or a Discord webhook, recognised by host. Three toggles, matching the
mockup's Settings:
- **A reward is claimed:** one message per claim. Several claims within 60 s are batched.
- **A campaign needs you:** sent once per campaign when it becomes unlinked-but-wanted, and once when its
  deadline verdict becomes "won't finish".
- **Twitch sign-in expires:** sent once per expiry.

## 11. Frontend

- `web/`: React 19 + Vite + Tailwind 4 + TypeScript. Built into `web/dist` and served by `api` at `/`.
- **The mockup is the visual spec.** Tokens, the Mining look (`data-look="ore"`) as the only look, the
  campaign-art backdrop, gem milestones, compact track mode, deadline bar, and the four views. The Plain
  look and the mockup-controls bar are dropped.
- Behaviour that the mockup only demonstrated must be preserved:
  - focus moves to the view heading on navigation;
  - Priorities announce moves in a live region and keep focus;
  - the Pause menu supports arrow keys, Home/End, Escape and outside click;
  - on phones Needs you comes first **in the DOM**;
  - inline confirms are used instead of dialogs;
  - non-breaking spaces between numbers and units.
- State comes from `GET /api/state` plus SSE events, held in one store. There is no polling except the
  SSE reconnect.
- **Before building them:** a mockup round for first-run setup and the browser sign-in view (section 4).

## 12. Deployment

- One image built from a `Dockerfile` in two stages: build the web UI with Node, then a Python 3.12-slim
  runtime with Chromium, Xvfb, x11vnc and noVNC. Expected size is about 400 MB, comparable to dungfu's
  415 MB.
- Runs as a non-root user. `/data` is the only volume. Port `5810` (dungfu uses 5800, so they don't
  clash while both exist). `TZ` env var.
- Unraid: added as a container through Nick's usual route. The image is built locally or in GitHub
  Actions to a private registry, decided in the plan.
- **Live-test protocol:**
  - Stop the dungfu container before the new miner signs in, because two miners on one account corrupt
    progress.
  - Restart dungfu only if the new one is being abandoned.

## 13. Testing

- **planner:** table-driven unit tests with a pinned `now`. Cover every rule in section 6, including:
  - Never beating Priority;
  - unlinked → Needs you;
  - spare-time ordering and ties;
  - favourite > allowed > any;
  - stickiness;
  - deadline verdicts.

  **Mutation check** on `planner`, because it decides everything.
- **twitch/*:** tests against recorded responses. A one-off capture script records `Inventory`,
  `ViewerDropsDashboard`, `CampaignDetails`, PubSub messages and a claim response from Nick's account.
  It scrubs the token, user id and login before anything is committed.
- **runner:** scenario tests with fakes for gql, pubsub and watch: stream goes offline, claim, pause,
  sign-in expiry, Twitch unreachable. Fakes return copies, not live references.
- **api:** FastAPI test client. Auth is required on every route, and SSE delivers events.
- **web:** component tests for the track layout (normal and compact), deadline bar, and Priorities
  focus. A Playwright smoke run against the API in fake mode.
- **Live acceptance on Unraid**, phase 1 and phase 5: it mines a real campaign for at least 2 hours,
  claims at least one reward, and survives a container restart without signing in again.

## 14. Build phases

Each phase ends tested and reviewed before the next one starts.

1. **Headless miner.**
   - auth, gql, pubsub, watch, models, planner, runner, store (lists + session only).
   - Run with a CLI: sign in through the browser locally, then mine and log.
   - Gate: mines and claims on Nick's account.
2. **API and store.** All endpoints, SSE, page auth, history tables, OpenAPI types.
3. **UI.**
   - Mockup round for first-run and the sign-in view first.
   - Then build the web app against the API.
4. **History, missed reasons, notifications, channel points.**
5. **Docker image and Unraid.** Image, container, live acceptance, then retire dungfu with Nick's say-so.

## 15. Not in v1

- Multiple Twitch accounts.
- Mining several channels at once (one session per account).
- Push channels other than ntfy and Discord.
- The TV-code sign-in plus an external campaign catalogue.
- Public release, a Docker Hub image, or docs for other users.

## 16. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Twitch changes login again (as on 2026-09-18) | medium | sign-in breaks; existing sessions usually keep working | `SessionProvider` is swappable; watch upstream issues #1165/#1178/#1180 |
| Persisted query hashes rotate | medium | a feature stops (e.g. discovery) | Hashes live in one module; failures are logged by operation name; check upstream for new hashes |
| Twitch adds integrity checks to the Android token's GQL | low–medium | the miner stops | Same as upstream; nothing better available |
| Account action for automation (Twitch ToS) | low, accepted | account penalty | Nick's decision. The app behaves like the original (one channel, minute heartbeats). |
| Chromium sign-in inside the container is fiddly (fonts, sandbox, memory) | medium | phase 5 friction | Reuse the fork's working setup (`Dockerfile.webui`, `entrypoint-webui.sh`) as reference |
