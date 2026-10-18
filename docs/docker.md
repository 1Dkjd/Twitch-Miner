# Running Dropwatch in Docker (Unraid)

One container is one miner. Never run two against the same Twitch account (a PC copy and a container,
or two containers): they fight over watch progress.

## Build

The image needs the commit it was built from. Without it every build looks the same, so the page's
"Dropwatch was updated" notice and the copy of the database before an upgrade both stop working, and
the build refuses to run:

```
docker build --build-arg DROPWATCH_COMMIT=main@$(git rev-parse --short HEAD) -t dropwatch:latest .
```

## Run

```
docker run -d --name dropwatch --restart unless-stopped \
  -p 5800:5800 -v /mnt/user/appdata/dropwatch:/data \
  -e TZ=America/New_York \
  --log-opt max-size=10m --log-opt max-file=3 \
  dropwatch:latest
```

| Setting | What it does |
|---|---|
| `--restart unless-stopped` | **Required.** When mining crashes or stops ticking for two checks in a row, Dropwatch exits on purpose and the restart policy starts a fresh one. Without a restart policy it stays stopped. |
| `/data` | The database (`drops.db`: Twitch sign-in, lists, history), the campaign catalogue and kept images. Owned by `PUID:PGID`. |
| `PUID` / `PGID` | The user the miner runs as; default `99:100` (Unraid's nobody:users), so the host can read `/data`. |
| `TZ` | The server's time zone (the weekly summary's default zone and log times). Default UTC. |
| `DROPWATCH_HOSTS` | Only for a public domain name, such as a reverse proxy's (`dropwatch.example.com`), comma-separated. IP addresses, `localhost`, bare server names (`tower`) and private suffixes (`.local`, `.lan`, `.home`, `.home.arpa`, `.internal`, `.localdomain`) always work. Other names are refused so a web page can't reach Dropwatch through DNS rebinding. `*` turns the check off. |
| `FORWARDED_ALLOW_IPS` | Behind a reverse proxy, the proxy's address, so the login lockout sees each visitor's own address instead of the proxy's (otherwise five wrong guesses through the proxy lock everyone out). |
| `DROPWATCH_CATALOG_URL` | Where campaigns are discovered. Empty: the public catalogue (`twitch-drops-api.sunkwi.com`), only ever sent a plain GET with no Twitch data. A URL: a mirror in the same format. `off`: Twitch only, which shows the TV sign-in just the campaigns already in progress on the account, so most new campaigns go unseen. Whatever the source, only Twitch-CDN images and https account links are taken from it, and a fetch that suddenly lists far fewer campaigns is ignored in favour of the last good list. |
| `--log-opt` | Docker keeps the miner's log (it writes to standard output); this caps it at 3 files of 10 MB. |

## Health

The image's health check calls `GET /api/health/miner`, which answers 503 when the mining loop crashed or
hasn't ticked for 15 minutes (longer than any back-off). Signed out, paused or idle are healthy.
Unraid shows the status; the restart itself comes from the watchdog plus the restart policy above.

## Upgrades

On start, a new build copies `drops.db` to `drops.db.before-<build>` before touching it (the two newest
copies are kept). To roll back: stop the container, copy the file back over `drops.db`, run the old image.

## Signing in on Twitch's login page

Settings › Account & security › **Sign in on Twitch's page** opens Twitch's real login page inside Dropwatch's
page. The image ships Chromium for this: during the sign-in it runs on a virtual screen (Xvfb) and the page shows
it live through Dropwatch's own WebSocket (behind the page password; the VNC server listens only inside the
container). Twitch then issues an Android-app token, which lists every campaign and whether each game account is
linked, before it starts. The code sign-in can't: Twitch hides both from it. The browser, screen and VNC server
stop as soon as the sign-in ends, so they use nothing the rest of the time.
