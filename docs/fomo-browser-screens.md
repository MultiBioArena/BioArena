# Actual FOMO screens in the studio

The execution preview can place cropped snapshots from each Bio's existing FOMO browser on its main 3D monitor. Clicking that monitor or its **FOMO screen** button opens a larger view with Worm, Fly and Larva tabs. Snapshots refresh every few seconds; this is not a continuous video stream or visual input to the brains.

The collector observes the current token page without navigating, choosing a token, moving the pointer or sending input. A strategy's execution attempt can navigate to its chosen token; the display then follows that actual page. Opening a token page or obtaining a quote does not confirm a fill. Inactive accounts can show a stationary page, with execution marked as not enabled. Pages never rotate at random.

## Screen and movement behavior

In the execution preview, all three creatures remain at their desks, with small idle motions. New verified real fills can trigger a labeled BUY/SELL replay. Paper signals, rejected attempts, page changes and quotes do not trigger a successful trade gesture. Historical fills are not replayed on initial page load. Browser images remain independent of the presentation, so camera controls cannot delay execution.

The six candidate monitors, portfolio cards, neural views and equity chart still use paper data. Paper balances are labeled. The production paper view retains its existing screens and roaming behavior; the browser screens are enabled only by `VITE_EXECUTION_PREVIEW=true`.

## Read-only capture boundary

- Only the current supported token chart/header and trade form are eligible for capture: Solana, Ethereum, Base, BNB Chain, Monad and Robinhood. Solana addresses retain their original case.
- Navigation, Profile, login and settings pages are excluded. Visible dialogs, menus or wallet/login frames pause capture. Unsupported layouts show an unavailable state.
- The account area below the trade form is covered before an image is published. A second inspection rejects a capture if the eligible page, layout or privacy state changed during acquisition.
- The public service exposes only metadata and processed JPEGs. It has no keyboard, pointer, signing, browser-debugging or execution endpoints, and serves no session credentials or raw screenshots.
- Frames older than twelve seconds cannot be served. The frontend drops images on expiry or connection failure; private or unavailable pages never fall back to an older screenshot.

The visible trade form can include the order amount and available balance. Publicly displaying a cropped trading screen is distinct from making an account or remote desktop controllable. Operator credentials, private configurations and diagnostic images stay outside Git.

## Local setup

The optional collector requires FFmpeg and the existing Playwright CLI browser sessions. Copy [the example configuration](../configs/fomo-screens.example.json) to a private path and set the three assigned session names and directories. It contains no order settings and never starts a browser or trader.

```bash
BIO_FOMO_SCREENS_CONFIG=/private/fomo-screens.json bash scripts/serve_fomo_screens.sh
```

The service listens on loopback port 8144. The existing market display service exposes GET-only proxies for `/api/fomo-screens` and `/api/fomo-screens/:bio/frame`; point deployed frontend rewrites at that service. The collector needs no additional public port. The proxy accepts only the three Bio identifiers, limits response size and time, and forwards no browser credentials or input. The development proxy targets the local collector directly. The public example contains no deployment hostname.

The collector uses [Chrome's screenshot protocol](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot) through the existing Playwright session and [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) to cover excluded pixels and fit the monitor image. It does not use screenshots to make trading decisions.

## Verification

Tests cover rejection of private paths, stale frames, invalid bounds and image data; account-area pixel masking; expired-image rejection; and the absence of POST controls. Isolated browser fixtures check actual token-layout capture, modal/menu blocking, profile exclusion and page changes during capture. Frontend checks distinguish actual screen changes and verified-fill replays from paper exploration and failed orders. These display checks do not place trades or validate a strategy.
