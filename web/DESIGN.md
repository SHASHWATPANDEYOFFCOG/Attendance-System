# Design system

Single source of truth: the `:root` block in [app.css](app.css). Nothing in the five pages
should hardcode a colour, duration, radius or shadow — if you need a new one, add a token.

## Scope of this pass

The palette, typefaces and the attendance-register metaphor are **fixed by the build spec (B8)
and were not redesigned.** This pass added the system layer around them: motion, elevation,
spacing, focus and a dark palette.

Deliberately **not** done, and why:

| Asked for | Verdict |
|---|---|
| Mesh gradients, aurora, glass panels on the dashboard | Cut. This screen carries a red banner reading *"a printed photo or a phone screen can be stamped present."* Decorative depth competing with a safety warning is a regression. |
| 3D hero (Three.js / R3F / Spline) | Cut. Violates the no-build/no-CDN constraint, and a particle field on a compliance tool is noise. Login got CSS-only depth instead. |
| Parallax, smooth-scroll library (Lenis), route transitions | Cut. This is a dense data tool used dozens of times a day; scroll-jacking a ledger and adding latency to every navigation is a usability tax. |
| Framer Motion / GSAP | Cut. **Zero new dependencies** — everything is plain CSS plus ~70 lines of vanilla JS. |

## Tokens

**Colour** — brand set is fixed; `--verdant` and `--focus` were added because green was
hardcoded as `#2E6B4F` in three places and could not be lifted for dark mode.

```
--paper --card --rule --ink --oxide --amber --ash      brand (B8, fixed)
--verdant --focus                                      semantic
--card-hover --tint --tint-hard --glass                derived surfaces
```

Dark mode is a full second palette applied two ways: `@media (prefers-color-scheme: dark)` for
system preference, and `:root[data-theme="dark"]` for the explicit toggle, which wins in both
directions. `color-scheme` is set so form controls and scrollbars follow.

**Type** — `--label` Barlow Condensed (uppercase, letterspaced) · `--data` IBM Plex Mono (all
numbers, tabular) · `--body` IBM Plex Sans.

**Spacing** — 8pt scale `--s1`(4) … `--s8`(64). `--line-h: 30px` is the ruled-paper rhythm and
ledger rows lock to it; changing it changes the register metaphor.

**Radius** — `--r-sm`(2) `--r-md`(3) `--r-lg`(6) `--r-xl`(10).

**Elevation** — `--shadow-sm/md/lg/xl`, layered rather than single-blur so cards read as paper
on paper. `--shadow-focus` is the focus halo.

**Motion**

```
--dur-fast   150ms   micro-interactions (hover, press, pill)
--dur        240ms   state changes, row reveal
--dur-slow   420ms   stamp, counters, card entrance
--ease-out       cubic-bezier(.22,.8,.3,1)     entrances
--ease-in-out    cubic-bezier(.5,0,.3,1)       movement
--ease-spring    cubic-bezier(.2,1.25,.4,1)    stamp, counter tick
```

Only `transform` and `opacity` are animated. Nothing animates a layout-triggering property, so
there is no CLS from motion.

## Changelog

**Fixed — real defects, not polish**

- **No visible keyboard focus** anywhere except inputs. Buttons, tabs and links had none, which
  is a WCAG failure. Now `:focus-visible` rings on everything, off for mouse clicks.
- **Touch targets below 44px.** `.btn.small` (Override, Sign out) measured 38px. Now every
  control, including `.small`, has a 44px floor under `@media (hover: none)`.
- **Zero `transition` declarations** in the entire stylesheet — every hover and state change
  snapped. Now tokenised transitions on buttons, tabs, cards, inputs, pills, marks, rows.
- **`prefers-reduced-motion` guarded only the stamp.** Now one global guard collapses every
  animation and transition. No animation carries information that isn't also in text.

**Added**

- **Dark mode** with a persisted toggle, injected by `initTheme()` into the page header so no
  page markup needed changing. Applied before first paint — no light flash for dark users.
- **One-shot keyed row reveal** (`revealNew`). The critical constraint: every list re-renders
  wholesale via `innerHTML` on each SSE event, so a naive entrance animation would restart the
  whole roll every time anyone checked in. Keys are remembered per scope; a row animates once.
  Stagger is 35ms, capped at 280ms.
- **Counters that fire only on change** (`setStat`). Counting on every poll would make the tiles
  twitch and mean nothing; a tick now signals *this number moved*.
- **Pip pulse** on the newest filled confirmation pip — the most informative moment in the
  product ("one more agreeing frame").
- **Heartbeat on running cameras**, paired with the text label so status is never conveyed by
  motion alone.
- **Paper grain** — a ~0.4 KB inline SVG, `position: fixed` and `pointer-events: none`, so it
  never repaints on scroll and never intercepts a click.
- **Login hero** — gradient wordmark, ruled underline, elevated card, two soft radial washes
  built from existing tokens. No new hue, no image, no canvas.

## Cost

| | |
|---|---|
| New dependencies | **none** |
| `app.css` | 9.2 KB → ~16 KB (uncompressed, unminified) |
| `app.js` | 5.9 KB → ~9 KB |
| New network requests | 0 (grain is an inline data URI; icons are inline SVG) |
| Render-blocking additions | 0 |

## Verified

20 automated browser checks in both themes, plus reduced-motion and a 390×844 mobile viewport:

- Contrast ≥ 4.5:1 for body text, muted text and the P/A/L marks, **in both palettes**.
- Focus ring present and measurable after keyboard `Tab`.
- Reduced motion: no reveal classes added, transitions collapsed, looping animation stopped.
- Reveal is staggered, applied to new rows, and **not** re-applied to already-seen rows.
- Theme persists across reload; no horizontal overflow at 390px; touch targets ≥ 44px.
- Zero JS errors and zero failed requests across all five pages, both roles.

Backend untouched and still green: 101 pytest tests, 34 HTTP checks.

## Gaps

- Contrast was checked on the tokens in use on the dashboard. The `.pill.warn` amber on card in
  **light** mode sits near the AA boundary for small text; it is always paired with a text label,
  but if you add amber-on-paper body copy, re-check it.
- No visual-regression baseline. Screenshots are captured but not diffed between runs.
- The `.card.ruled` ruling is subtle at the current `--rule` value in dark mode. It reads as
  texture rather than as ledger lines; raise `--rule` lightness in the dark block if you want it
  more literal.
