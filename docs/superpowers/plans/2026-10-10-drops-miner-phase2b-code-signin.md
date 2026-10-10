# Drops Miner Phase 2b (Code Sign-in and Catalogue) Plan

**Goal:** Sign in with Twitch's TV code login (twitch.tv/activate + an 8-letter code), and find campaigns through the public catalogue when Twitch hides them from that login. Then switch the live miner over.

**Spec:** `docs/superpowers/specs/2026-10-09-drops-miner-design.md` §4 (2026-10-10 amendment), §7, §8, §9, §14 (2b).

**Executor:** inline (executing-plans), worktree `../drops-miner-2b`, branch `phase2b-code-signin` from main.

**Declared deviation from the writing-plans format:** this plan names tasks, interfaces and the failing tests, but gives no full code blocks. Every task is small and follows code that already exists. Writing the code out twice would roughly double Nick's usage for no gain. TDD per task still applies: write the named tests first, watch them fail, then implement. The final fresh review still applies.

## Global Constraints

- **Existing Android sessions keep working unchanged.** The session's `client_id` picks the client, and the dashboard path is used whenever it returns campaigns. The live miner must not notice this build until Nick switches.
- **Sending as the session's own client:**
  - GQL headers and the spade POST use `client_for(session.client_id)`.
  - The channel page (for the spade URL) and the playlist/segment requests keep the Android user agent. That exact combination earned 12/12 minutes in the 2026-10-10 spike, so don't change it.
- **Never send anything about the account to the catalogue.** It gets its own transport instance (its own cookie jar), with no Twitch headers.
- **Device-code polling has no client-side timeout.** Only Twitch's `expires_in` ends it (memory: no timeout on interactive auth).
- Commit as `Nick <37944729+weltern@users.noreply.github.com>`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, explicit paths only.
- **One miner per account.** At the live gate, stop `serve` before anything else mines.

## Review Focus

1. A TV session must send the TV Client-Id on GQL and on spade, and an Android session must still send the Android one.
2. A campaign whose link is unknown must neither be hidden as unlinked nor mined forever. Check the "may need linking" rule's entry and exit conditions.
3. A catalogue failure (down, malformed, stale, cache file corrupt) must never stop the miner, and never wipes campaigns already in `Inventory`.
4. Inventory must win over the catalogue on every field it has (progress, claimed, `self`).
5. Sign-in: expiry, cancel, a double start, and a non-TV token are all handled. Polling has no timeout of its own.

## Tasks

### Task 1: Client per session
- `constants.SMARTBOX` (TV client: `https://android.tv.twitch.tv`, `ue6666qo983tsx6so1t0vnawi233wa`, Smart Box UA). `client_for(client_id) -> ClientInfo` returns the Android client for anything else.
- `Gql(client=None)`: when no client is given, use `client_for(session().client_id)` per request.
- `Watcher._post_spade`: `base_headers(s, client_for(s.client_id))`. Everything else in the watcher is unchanged.
- **Tests first:** `test_gql_sends_session_client` (TV session → TV Client-Id, Android → Android); `test_spade_post_uses_session_client`; `test_client_for_unknown_is_android`.

### Task 2: Linked can be unknown
- `Campaign.linked: bool | None`. `parse.to_campaign`: `None` when the raw record has no `self`.
- `models.account_eligible`: an unknown link counts as eligible. The planner's `needs_you` takes only `linked is False`.
- API: `CampaignOut.linked: bool | None` and `CampaignOut.maybe_unlinked: bool`.
- **Tests first:**
  - `test_to_campaign_without_self_is_unknown`;
  - `test_planner_mines_unknown_link`;
  - `test_planner_needs_you_only_for_false`;
  - the existing planner and parse suites stay green.

### Task 3: Catalogue source (`twitch/catalog.py`)
- `Catalog(transport, cache_path, clock)`:
  - `async campaigns() -> dict[id, raw]`: fetches at most hourly, with forced refreshes allowed. Flattens `data[].rewards[]`, copies `gameBoxArtURL` into `game.boxArtURL`, and keeps only `ACTIVE` records that haven't ended.
  - `status -> (ok|stale|unreachable, since)`.
- On success, write `/data/catalog.json` with `write_bytes` (the file is LF-safe). On failure: memory, then the file, then empty, and set `unreachable` since the first failure. When `lastUpdatedAt` is more than 6 h old, set `stale`.
- **Tests first:**
  - `test_flattens_and_filters_ended`;
  - `test_box_art_copied`;
  - `test_hourly_ttl`;
  - `test_unreachable_uses_cache_file`;
  - `test_corrupt_cache_is_empty_not_crash`;
  - `test_stale_after_6h`;
  - `test_no_twitch_headers_sent`.

### Task 4: TwitchClient uses the catalogue when the dashboard is empty
- `TwitchClient(gql, user_id, catalog=None)`: when the dashboard is empty and a catalogue is set, use `parse.merge(inventory, catalog)`, with Inventory as primary.
- Runner: a `catalog_status` property, passed through to the state.
- **Tests first:**
  - `test_dashboard_wins_when_present` (the catalogue isn't even fetched);
  - `test_catalog_used_when_dashboard_empty`;
  - `test_inventory_overrides_catalog_fields` (progress, claimed, `self`).

### Task 5: "May need linking"
- Runner: while the current campaign's link is unknown, count successful watch ticks.
  - After 10 min (60 ticks) with no rise in that campaign's total minutes, mark it `maybe_unlinked` (campaign id → `now`).
  - Before planning, a marked campaign that is still unknown is planned as `linked=False`, so it goes to Needs you.
  - The mark clears when the link becomes known (`True`/`False` from Inventory), when progress rises, or after 6 h.
  - A `needs_you` event is published when a campaign is marked.
- **Tests first:**
  - `test_unknown_link_marked_after_10_min_flat`;
  - `test_progress_clears_probe`;
  - `test_mark_expires_after_6h`;
  - `test_known_link_never_probed`.

### Task 6: Device-code sign-in (`twitch/auth_device.py`)
- `DeviceCodeSignIn(transport)`:
  - `async start() -> DeviceCode(user_code, verification_uri, expires_at, interval, device_code)`;
  - `async wait(code, cancel) -> TwitchSession`. It polls with no timeout of its own and raises `SignInError("That code expired…")` on `expired_token` or after `expires_at`, and on a non-TV `client_id` from validate.
- Device id as in `auth_browser.device_id`.
- **Tests first** (fake transport):
  - `test_start_returns_code`;
  - `test_wait_polls_until_token` (`authorization_pending`, then a token);
  - `test_slow_down_respected`;
  - `test_expired`;
  - `test_cancel`;
  - `test_rejects_non_tv_token`.

### Task 7: Sign-in API and CLI
- `SignInManager`: `async start() -> dict`. It awaits `start()` so the code can be returned, then runs `wait` in the background.
  - Status is `{status: idle|waiting|done|expired|failed, message, code, verification_uri, expires_at}`.
  - `SignInStatus` gains those fields. `POST /api/twitch/signin` returns 202 with the status.
- CLI:
  - `dropsminer signin` prints the link and code, then waits.
  - `dropsminer signin --browser` runs the phase-1 browser sign-in.
  - `serve` builds `DeviceCodeSignIn`.
- `zendriver` moves to an optional extra, `[browser]`. `auth_browser` imports it lazily. Regenerate `docs/api/openapi.json`.
- **Tests first:**
  - `test_post_signin_returns_code`;
  - `test_status_expired`;
  - `test_cli_signin_prints_code` (fake provider);
  - the existing sign-in API tests, adapted.

### Task 8: Wire it
- `service.build_parts`: a second `AiohttpTransport` for the catalogue, and `Catalog(data_dir/catalog.json)` handed to `TwitchClient`. Close both transports.
- `StateOut.catalog: {status, since} | None`.
- **Tests first:** `test_state_includes_catalog_status`, `test_build_parts_closes_catalog_transport`.

### Task 9: Gate
1. The whole suite, then ruff, then mutation checks on `catalog.py` (TTL, fallback, stale) and on the link rule. Then a fresh whole-branch review, with the Review Focus above as its checklist.
2. **Live gate:**
   1. Back up `drops.db`.
   2. Stop `serve`.
   3. Run `dropsminer signin`. Nick enters the code.
   4. Start `serve`.
   5. Confirm in `/api/state` that the client is TV, the catalogue status is ok, the campaign count is about 120, and it is mining. Confirm the drop minutes rise.
3. **Claim proof:** leave it running. The first `claimed` in the log, together with Twitch's inventory showing `isClaimed`, proves claiming. If a drop sits at 100% unclaimed for more than an hour, roll back to the Android session from the backup.
4. Record the result in the README, and merge locally on Nick's say-so.
