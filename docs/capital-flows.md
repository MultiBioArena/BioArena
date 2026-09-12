# External-capital evidence

**Implemented and tested infrastructure; not connected to live FOMO account scoring.** The arena remains paper-only. This module cannot sign, transfer or place orders.

`capital_flows.py` scans configured EVM wallets for confirmed ERC-20 Transfer logs. A private configuration binds each Bio to a network, wallet, monitored contracts, expected external funding wallets, internal wallets and a starting block. Chain ID and canonical block hashes are checked. Transaction/log IDs are stable; repeated scans do not duplicate events. Cursor changes, altered classification settings or a detected reorganization require review.

Automatic deposit/withdrawal classification is deliberately narrow: a single wallet transfer, an exact direct ERC-20 `transfer` call and a configured external counterparty. Transfers between configured owned wallets are internal. Previously identified trade/bridge operations need their own evidence reference. Unknown contracts, complex transactions and unrecognized counterparties remain unresolved; an arbitrary transfer is not assumed to be new capital.

This scanner does **not** cover native-currency transfers, internal execution traces, Solana, arbitrary smart-wallet batches or full FOMO cross-chain settlement. A scan of selected contracts does not prove complete account coverage. The live adapter must enumerate every relevant wallet, chain and funding asset before scoring can be enabled.

## Local use

Create a private JSON configuration, excluded from Git:

```json
{
  "networks": {
    "configured-network": {
      "rpc_url": "https://YOUR_READ_ONLY_RPC",
      "chain_id": 4663,
      "confirmations": 3
    }
  },
  "accounts": [{
    "network": "configured-network",
    "bio_id": "worm",
    "wallet": "VERIFIED_EVM_RECEIVING_ADDRESS",
    "tokens": ["VERIFIED_ERC20_CONTRACT"],
    "external_wallets": ["EXPECTED_FUNDING_ADDRESS"],
    "internal_wallets": [],
    "start_block": 123456
  }]
}
```

Replace every placeholder, including the chain and starting block, with verified settings. The Robinhood [canonical token list](https://docs.robinhood.com/chain/contracts/) identifies USDG; its contract and chain were checked in a zero-funds receive-wallet probe. An EVM address does not identify a network. FOMO cash assets can differ by deposit network; do not infer a USDC contract from a dollar-denominated UI balance.

```bash
.venv/bin/python scripts/scan_capital_flows.py \
  --config .private/capital-flows.json \
  --database .private/capital-flows.sqlite \
  --output .private/capital-flow-status.json
```

One invocation scans at most 200 confirmed blocks per configured wallet; repeated invocations continue the durable cursor. The public release has no account configuration. When an operator supplies `.private/capital-flows.json`, the [service installer](operations.md) adds an optional read-only timer: one bounded scan of up to 1,000 blocks per wallet, then 30 seconds before its next invocation. No unresolved event changes account cash or scores.

## Reconciliation before scoring

Discovery and USD accounting are separate. `FlowStore.reconcile` requires a local valuation record bound to Bio, wallet, chain, transaction, raw balance changes and one contemporaneous price snapshot. Every token needs verified decimals, a positive finite USD price and a source reference. Before/after account equity must reconcile exactly with contributed capital and separately recorded transaction costs. Gas costs reduce performance and are not hidden inside the external contribution.

Valuation records can be supplied through `--valuations` as a JSON list of `bio_id`, `tx_hash` and `valuation` objects. Their fields and complete fixture are in `tests/test_capital_flows.py`. These are trusted local reconciler inputs, not an automatic historical price service or proof that the CLI independently valued every holding.

`ChallengeStore(path, flow_provider=store)` consumes the durable events. Every registered scan must cover the full interval through a block after its closing timestamp. Pending classification, missing valuation, missing coverage and reorganization flags prevent scoring. A failed interval is voided under the current immutable settlement rules; it is not silently settled after late evidence arrives. A future live adapter must supply finalized boundaries at an appropriate delay before calling settlement.

Tests cover a deposit after losses, withdrawals, fee attribution, immutable reconciliation, duplicate scans, unknown transfers, missing coverage and chain reorganization. A refill cannot erase an earlier loss. The running audience collector still accepts paper states only and remains hidden. Real funded deposit/withdrawal reconciliation and automatic multi-chain USD valuation remain verification and integration work.

Evidence uses standard [Ethereum JSON-RPC logs and receipts](https://ethereum.org/en/developers/docs/apis/json-rpc/) and the [ERC-20 Transfer event](https://eips.ethereum.org/EIPS/eip-20).

The active private operator has configured the three observed Robinhood receive wallets for USDG monitoring. All three passed confirmed RPC scans and raw-balance checks without submitting transactions. Expected funding counterparties are not yet configured, so newly observed transfers require review. Other deposit networks and complete cash aggregation remain outside that monitor.
