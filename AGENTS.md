# Repository rules

These rules apply to the entire repository.

## Public boundary

- Keep this repository reproducible from tracked public files. Never add credentials, wallet or account material, browser profiles or storage, private endpoints, local logs, execution receipts, or operator-only evidence.
- Synchronize only files explicitly approved for public release. Treat private runtime state and the public reference implementation as separate systems.
- Preserve scientific-source, attribution, license, protocol, security, identity, money-movement, idempotency, recovery, and fail-closed context.
- Do not add or change the project license without an explicit owner decision.

## Change discipline

- Before editing or pushing, confirm the current remote `main` commit, the worktree status, active consumers, and the exact authorized scope. Use one code writer for a coordinated change.
- Keep comments sparse. Remove comments that restate code or narrate implementation; retain short comments that explain a non-obvious invariant, safety boundary, protocol constraint, compatibility reason, or source.
- Do not restructure the repository for appearance. Structural changes need evidence of coupling, duplication, unclear ownership, test isolation problems, or public/private leakage.
- Keep paper services unable to enable live execution. Live execution remains separately started, explicitly authorized, and fail-closed.
- Keep README paths, the canonical clone URL, and local documentation links synchronized with the tracked tree.
- Do not commit, push, deploy, publish, change accounts, or perform financial actions beyond the authority granted for the current task.

## Verification

Before a public update, run:

```bash
bash scripts/check.sh --offline
```

This command covers the offline Python suite, the three Node behavior checks, and the frontend production build. Also review the final diff and scan tracked files for credentials, private paths, browser artifacts, logs, and other non-public material.
