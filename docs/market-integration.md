# Market integration

## SOL/USDT baseline

The default configuration uses public SOL/USDT market observations and a fixed opportunity policy. No trading account is required. Start it with:

```bash
bash scripts/serve.sh
```

The baseline is useful for exploring neural activity and verifying the simulation/accounting pipeline. Multi-token learning uses the separate configuration below.

## Optional FOMO discovery

The multi-token adapter reads the currently rendered [FOMO Trending](https://fomo.family/) candidates from a browser session that you authenticate yourself. It uses [Playwright CLI](https://github.com/microsoft/playwright-cli); the command was checked against version 0.1.19. A machine with a graphical browser session is needed for interactive sign-in.

From the repository root, create a local browser workspace and open the session:

```bash
mkdir -p .private/fomo-market
cd .private/fomo-market
npx --yes --package @playwright/cli@0.1.19 playwright-cli \
  -s=fomo-market open https://fomo.family/ --headed --persistent --profile=browser
```

Complete sign-in directly in the browser and leave that session running. From another terminal at the repository root, verify one read-only capture:

```bash
.venv/bin/python scripts/capture_fomo_market.py
```

Then start the multi-token arena:

```bash
BIO_ARENA_CONFIG=configs/fomo.yaml bash scripts/serve.sh
```

The collector defaults to the `fomo-market` session and `.private/fomo-market` working directory. Optional overrides are:

| Variable | Purpose |
| --- | --- |
| `BIO_ARENA_BROWSER_DIR` | Browser working directory |
| `BIO_ARENA_BROWSER_SESSION` | Playwright session name |
| `BIO_ARENA_PLAYWRIGHT_COMMAND` | CLI command, parsed as arguments without invoking a shell |

A browser session supplies market discovery, not trading permission for the arena. Credentials and browser storage remain local and are ignored by Git. The adapter does not read account balances or place orders.

## Candidate and quote semantics

FOMO discovery returns a rendered subset, not a complete ranking. Every snapshot records source and observation time and sets `complete_board=false`. Rounded page prices are not used for paper settlement. A changed page layout or expired session can interrupt discovery; old snapshots retain their original timestamps and eventually block new entries.

[DEX Screener's public API](https://docs.dexscreener.com/api/reference) supplies reference prices, pool liquidity, recent volume, and trade counts. The adapter matches both chain and base-token contract. EVM addresses are normalized to lowercase; Solana addresses preserve case. Pool changes reset the affected price window and invalidate labels spanning pools.

Discovery is configured around once per minute and quote polling around every ten seconds. These are polling intervals, not promises about provider freshness. Aggregate reference prices are not executable bid/ask quotes. Observing other traders sell does not prove this account can sell.

## Rear market display

The optional read-only display service provides BTC, ETH, SOL, NVDA, and AAPL quotes:

```bash
bash scripts/serve_market_board.sh
```

The Vite frontend proxies this service at `/api/market-board`. Crypto quotes use Binance public market data; stock quotes use the Nasdaq quote-page endpoint. The display retains source times and market status, labels stale data, and does not manufacture price history. Its quotes do not enter the agents' trading inputs.
