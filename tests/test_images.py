"""Keep copies of the images History shows (2026-10-10): Twitch's links can stop working after a campaign
ends. Only Twitch's image host is fetched."""
from datetime import timedelta

from apihelpers import NOW, logged_in, make_app

from dropwatch.images import ImageCache, box_art_144


class FakeGet:
    def __init__(self, body=b"\x89PNG...", ctype="image/png", status=200):
        self.body, self.ctype, self.status, self.urls = body, ctype, status, []

    async def __call__(self, url):
        self.urls.append(url)
        return self.status, self.ctype, self.body


async def test_fetches_twitch_images_once_and_names_them_by_url(tmp_path):
    get = FakeGet()
    cache = ImageCache(tmp_path / "images", get)
    url = "https://static-cdn.jtvnw.net/twitch-quests-assets/REWARD/abc.png"
    assert cache.local_url(url) is None
    assert await cache.ensure([url, url]) == 1
    assert await cache.ensure([url]) == 0  # already kept
    assert get.urls == [url]
    local = cache.local_url(url)
    assert local and local.startswith("/api/img/") and local.endswith(".png")
    assert cache.file(local.rsplit("/", 1)[1]).read_bytes() == b"\x89PNG..."


async def test_refuses_other_hosts_non_images_and_huge_files(tmp_path):
    for url, get in [("https://evil.example/x.png", FakeGet()),
                     ("http://static-cdn.jtvnw.net/x.png", FakeGet()),  # not https
                     ("https://static-cdn.jtvnw.net/x.png", FakeGet(ctype="text/html")),
                     ("https://static-cdn.jtvnw.net/y.png", FakeGet(body=b"x" * (3 * 1024 * 1024 + 1))),
                     ("https://static-cdn.jtvnw.net/z.png", FakeGet(status=404))]:
        cache = ImageCache(tmp_path / "images", get)
        assert await cache.ensure([url]) == 0, url
        assert cache.local_url(url) is None
        if "static-cdn.jtvnw.net/" not in url or url.startswith("http:"):
            assert get.urls == [], url  # never even asked for


def test_box_art_is_kept_at_the_size_the_page_shows():
    assert box_art_144("https://static-cdn.jtvnw.net/ttv-boxart/491931_IGDB-{width}x{height}.jpg") \
        == "https://static-cdn.jtvnw.net/ttv-boxart/491931_IGDB-144x192.jpg"
    assert box_art_144("https://static-cdn.jtvnw.net/ttv-boxart/1_IGDB-120x160.jpg").endswith("1_IGDB-144x192.jpg")
    assert box_art_144("https://static-cdn.jtvnw.net/ttv-boxart/1338428218_IGDB.jpg").endswith("_IGDB-144x192.jpg")
    assert box_art_144("") == ""


async def test_history_serves_kept_copies_and_wanted_lists_every_history_image(tmp_path):
    app, ctx = make_app(tmp_path)
    art = "https://static-cdn.jtvnw.net/ttv-boxart/1_IGDB-{width}x{height}.jpg"
    reward = "https://static-cdn.jtvnw.net/twitch-quests-assets/REWARD/r.png"
    ctx.store.add_claim(NOW, "c1", "Frights", "Palia", [("Glasses", reward)], box_art_url=art)
    ctx.images = ImageCache(tmp_path / "images", FakeGet(body=b"IMG"))
    assert set(ctx.store.history_image_urls(NOW - timedelta(days=400))) == {reward, art}
    c = await logged_in(app)
    (claim,) = (await c.get("/api/history")).json()["claims"]
    assert claim["rewards"][0]["image_url"] == reward  # not kept yet: Twitch's own link
    await ctx.images.ensure([reward, box_art_144(art)])
    (claim,) = (await c.get("/api/history")).json()["claims"]
    local = claim["rewards"][0]["image_url"]
    assert local.startswith("/api/img/") and claim["box_art_url"].startswith("/api/img/")
    r = await c.get(local)
    assert r.status_code == 200 and r.content == b"IMG" and r.headers["content-type"] == "image/png"
    assert (await c.get("/api/img/..%2Fd.db")).status_code == 404
    assert (await c.get("/api/img/nothere00000000000000000.png")).status_code == 404
    await c.aclose()
