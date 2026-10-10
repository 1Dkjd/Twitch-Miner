# Dropwatch logo: the cut stone

One mark: the app's own milestone gem, cut into six facets with an ink rim. It is the same five-point shape the campaign track already draws, so the logo and the UI agree.

Geometry (percent of the bounding box): (50, 0) (100, 34) (80, 100) (20, 100) (0, 34). Girdle at 34%. Crown facets meet the girdle at 30% and 70%.

Colours are the ore tokens: rim `accent-ink` #1c1405; facets #ffd978 / #d4960f / #c98a0b above the girdle, #f2b632 / #8a5e05 / #a8700a below; highlight #fff3c4 at 60%.

## Files

- `mark/dropwatch-mark.svg`: the full-colour stone, transparent, 100×100 viewBox. Use at 20px and up.
- `mark/dropwatch-mark-mono-gold.svg`: one colour, gold with dark cut lines, for dark grounds where the facets would be noise.
- `mark/dropwatch-mark-mono-ink.svg`: one colour, ink with gold cut lines, for the gold tile and gold grounds.
- `mark/dropwatch-mark-currentcolor.svg`: inline-SVG version; fills `currentColor`, cut lines use `--dw-ground` (defaults to the dark bg). Drop into `Icons.tsx` beside the pickaxe.
- `icon/dropwatch-icon.svg` and `png/icon-*.png`: app icon, stone on a `surface` tile with a faint glow, rounded corners baked in (16 to 1024).
- `icon/dropwatch-icon-maskable.svg` and `png/icon-maskable-*.png`: square, stone inside the 80% safe zone, for a PWA manifest `purpose: "maskable"`.
- `icon/favicon.ico`: 16 / 32 / 48, the bare stone (the tile is too small to read at tab size).
- `icon/apple-touch-icon.png`: 180×180.
- `icon/dropwatch-hero.svg` and `png/hero-1024.png`: the stone with glow and glints on the dark bg, for the README and a splash.
- `lockup/dropwatch-lockup-*.svg`: stone + "Dropwatch" in Archivo (wdth 82, wght 760), text converted to outlines so no font is needed. Dark and light text versions, transparent.
- `lockup/dropwatch-stacked-*.svg`: stone over "DROPWATCH" (wdth 70, wght 800, 0.1em tracking), for a square slot.
- `lockup/preview-*.svg` and `png/preview-*`: the same lockups on their grounds, only for checking.

## In the app

Top bar: mark at 20px beside the 15px wordmark, replacing the pickaxe glyph. The pickaxe can keep its place as the "Mine now" action icon.

Favicon: `<link rel="icon" href="/favicon.ico" sizes="any">` plus `<link rel="icon" type="image/svg+xml" href="/dropwatch-mark.svg">`.

Manifest: `icon-192.png`, `icon-512.png` as `any`; `icon-maskable-192.png`, `icon-maskable-512.png` as `maskable`.
