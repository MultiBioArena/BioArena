# Persistent paper operations

The paper supervisor restores the latest complete compatible checkpoint. It never creates replacement capital during recovery. A source-code or data mismatch, missing recovery bundle, or repeated early failure stops automatic recovery for operator review.

## Linux user services

With prepared project dependencies and a valid `runs/active-run.json`:

```bash
.venv/bin/python scripts/install_services.py --enable
systemctl --user start bio-arena.service bio-arena-monitor.service bio-arena-market.service
systemctl --user start bio-arena-comparison.timer bio-arena-archive.timer
systemctl --user status bio-arena.service
systemctl --user list-timers 'bio-arena-*'
```

The installer renders and verifies only project service names, then links them from the user's service directory. Keep `output/service-units/` and the project path intact. An existing manually managed service with the same name is rejected. Stop an existing project server at a validated paused checkpoint before starting its replacement; do not run two supervisors on the same port.

User services require a persistent user manager to start without an interactive login. Check `loginctl show-user "$USER" -p Linger`. The active deployment has lingering enabled; another host may require its administrator to enable it. Installing services does not reboot the machine. Private operators can additionally install their retained browser launcher; login profiles are never distributed with this repository. Other installations must arrange their own market-discovery browser startup.

- Simulation, local monitoring and the display market feed restart on failure.
- The supervisor checks HTTP health and decision progress. After 60 seconds without an HTTP response, or 180 seconds without progress while the market is fresh and the arena is running, it stops its owned process group and attempts compatible recovery.
- Intentional pauses, finished runs and missing market data do not trigger a decision-stall restart. An engine error stops the supervisor for review.
- A process gets 15 seconds for graceful shutdown before its remaining owned process group is killed. Recovery retains pause state, balances, positions and learning, and explicitly discards labels spanning unobserved downtime.
- Health and learning reports are written every minute. No external messages are sent.
- An optional privately configured ERC-20 scanner runs read-only on a 30-second timer; unresolved transfers never change the paper accounts.
- Every six hours, a separate low-priority job captures up to 1,000 recent observations per Bio and runs three seeded policy comparisons. It has a one-core CPU quota and a 45-minute timeout; it cannot alter the active accounts or models.

The active deployment passed a controlled HTTP-hang test: the paper arena was paused, the server process was suspended, the watchdog detected the outage and restored a new child run. Cash, held quantities, learning counters and pause state matched before the operator resumed. This verifies recovery from that failure, not every possible host failure. A whole-host reboot was not performed.

## Verified archival

Supervisor output rotates at 5 MiB with five backups in `runs/operations/`. A daily timer compresses explicitly stopped experiment directories older than 24 hours. The active run and its entire recovery/migration ancestry are protected.

```bash
# Compress and verify without removing source files:
.venv/bin/python scripts/archive_runs.py
# Remove only eligible sources after verified, durable archival:
.venv/bin/python scripts/archive_runs.py --prune-verified
```

Archives live in `archives/`, outside Git. Each bundle has a JSON index of all file SHA-256 hashes. Compression is followed by a complete archive reread, checksum comparison, source recheck and durable disk writes. Only then may pruning remove that stopped source directory. Symlinks are rejected. A write failure retains the source. To inspect or restore, use the local tar tool in a separate empty directory, verify against the index, and review compatibility before selecting a recovery run.

One stopped experiment was actually compressed from 57,083,318 bytes to 11,400,888 bytes and verified before removal. An archive on the same disk is not an off-host backup. Active histories and protected ancestors remain unpruned and can grow; disk monitoring continues to be necessary.
