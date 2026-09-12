#!/usr/bin/env python3
"""Capture public market data from the owner's existing FOMO browser session."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import subprocess
import shlex

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get('BIO_ARENA_BROWSER_DIR', ROOT / '.private/fomo-market')).expanduser().resolve()
CLI = shlex.split(os.environ.get('BIO_ARENA_PLAYWRIGHT_COMMAND',
    'npx --yes --package @playwright/cli@0.1.19 playwright-cli'))
SESSION = os.environ.get('BIO_ARENA_BROWSER_SESSION', 'fomo-market')

# Observe the web app's own market responses. No auth headers, cookies, account
# holdings, order endpoints, or identity-provider pages are accessed here.
BROWSER_CODE = r'''async (page) => {
    if (!page.url().startsWith("https://fomo.family/")) {
        throw new Error("FOMO market page is not open");
    }
    const tab = page.getByRole("button", {name:"Trending", exact:true});
    if (await tab.count() !== 1) {
        throw new Error("Expected one FOMO discovery panel; login or panel layout needs attention");
    }
    const jobs = [];
    const batches = [];
    const capture = response => {
        if (response.url().split("?")[0] !== "https://prod-api.fomo.family/proxy/filterTokens"
            || response.status() !== 200) return;
        const received = Date.now();
        jobs.push(response.json().then(body => {
            if (body.success && Array.isArray(body.responseObject)) {
                batches.push({received, rows:body.responseObject});
            }
        }).catch(() => {}));
    };
    page.on("response", capture);
    let board;
    try {
        await tab.click();
        await page.waitForTimeout(5000);
        board = await page.evaluate(() => {
            const tab = [...document.querySelectorAll("button")]
                .find(e => e.textContent.trim() === "Trending");
            if (!tab?.classList.contains("bg-bg-tertiary-solid")) {
                throw new Error("Trending is not the active board");
            }
            let panel = tab.parentElement;
            for (let depth=0; panel && depth<5; depth++, panel=panel.parentElement) {
                const links = [...panel.querySelectorAll('a[href*="/tokens/"]')];
                if (!links.length) continue;
                return {observed_at: new Date().toISOString(),
                    visible_links: links.map((link, index) => ({
                        href:link.getAttribute("href"),
                        display_text:link.innerText,
                        visible_position:index+1
                    }))};
            }
            throw new Error("No candidate links found in the discovery panel");
        });
    } finally {
        page.off("response", capture);
    }
    await Promise.all(jobs);
    const candidates = [];
    const seen = new Set();
    const candidateAddresses = new Set();
    const normalizeAddress = address => /^0x[0-9a-fA-F]{40}$/.test(address)
        ? address.toLowerCase() : address;
    for (const row of board.visible_links) {
        const match = /^\/tokens\/([a-z0-9-]+)\/([a-zA-Z0-9]+)$/.exec(row.href || "");
        if (!match) continue;
        const chain = match[1];
        const address = normalizeAddress(match[2]);
        // EVM addresses are case-insensitive; Solana addresses are not.
        if (chain === "solana" ? !/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(address)
                               : !/^0x[0-9a-f]{40}$/.test(address)) continue;
        const assetId = chain + ":" + address;
        if (seen.has(assetId)) continue;
        seen.add(assetId);
        candidateAddresses.add(address);
        candidates.push({asset_id:assetId, chain, address,
            symbol:row.display_text.split("\n")[0].trim(),
            visible_global_position:row.visible_position,
            url:"https://fomo.family"+row.href,
            display_text:row.display_text,
            display_values_are_rounded:true});
    }
    const latest = new Map();
    const number = value => {
        if (value === null || value === undefined || value === "") return null;
        const result = Number(value);
        return Number.isFinite(result) && result >= 0 ? result : null;
    };
    for (const batch of batches.sort((a,b) => a.received-b.received)) {
        for (const row of batch.rows) {
            const token = row.token;
            const address = normalizeAddress(String(token?.address || ""));
            const networkId = Number(token?.networkId);
            const price = number(row.priceUSD);
            if (!Number.isSafeInteger(networkId) || networkId <= 0
                || !candidateAddresses.has(address) || !(price > 0)) continue;
            // Provider network IDs need explicit mapping before joining these
            // observations to board assets; never join on an EVM address alone.
            const quoteId = networkId + ":" + address;
            latest.set(quoteId, {source_asset_id:quoteId, source_network_id:networkId,
                address, symbol:token.symbol,
                decimals:Number.isInteger(token.decimals)?token.decimals:null,
                price_usd:price, liquidity_usd:number(row.liquidity),
                volume_5m_usd:number(row.volume5m), volume_24h_usd:number(row.volume24),
                reported_market_cap_usd:number(row.marketCap),
                source_received_at:new Date(batch.received).toISOString(),
                source_market_timestamp:null,
                source:"FOMO web /proxy/filterTokens", executable_quote:false});
        }
    }
    return {schema:"bio_arena.fomo_market_snapshot.v2",
        source:"FOMO authenticated web discovery panel", board:"trending",
        scope:"Currently rendered FOMO global board; no chain restriction",
        complete_board:false, observed_at:board.observed_at,
        rendered_global_count:board.visible_links.length,
        candidates, quotes:[...latest.values()],
        quote_scope:"Only matching market responses observed during this capture",
        quote_binding:"Provider network IDs must be resolved before binding to board chain slugs",
        execution:"read_only; no orders or wallet actions"};
}'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/fomo-market-snapshot.json')
    args = parser.parse_args()
    result = subprocess.run(
        [*CLI, f'-s={SESSION}', 'run-code', BROWSER_CODE], cwd=PRIVATE,
        env=os.environ.copy(),
        capture_output=True, text=True, timeout=35)
    marker = '### Result\n'
    if result.returncode or marker not in result.stdout:
        # CLI diagnostics may contain private page information; do not publish them.
        raise RuntimeError('FOMO capture unavailable; check the private browser session')
    payload, _ = json.JSONDecoder().raw_decode(result.stdout.split(marker, 1)[1].lstrip())
    if payload.get('schema') != 'bio_arena.fomo_market_snapshot.v2' or not payload['candidates']:
        raise RuntimeError('No valid FOMO candidates; previous snapshot was not replaced')
    payload['saved_at'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    temporary.replace(args.output)
    print(json.dumps({'output':str(args.output), 'observed_at':payload['observed_at'],
                      'candidates':len(payload['candidates']),
                      'chains':sorted({r['chain'] for r in payload['candidates']}),
                      'market_quotes':len(payload['quotes']), 'complete_board':False,
                      'symbols':[r['symbol'] for r in payload['candidates']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
