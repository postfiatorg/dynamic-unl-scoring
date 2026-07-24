# Deterministic Final Score — Devnet Rollout Record

As-run record of the devnet rollout that took the deterministic final-score stage (`docs/DeterministicFinalScore.md`) into live use on 2026-07-23: scoring service commit `7f2efea` (score formula v1, prompt v8, RAW/PARSED convergence acceptance) and validator sidecar v1.2.0 (commit `433bda5`, bimodal vendored formula). Two live rounds prove the three compatibility scenarios with deliberately mixed sidecar versions — **scenario 1**: a v1.2.0 sidecar on a pre-formula round (legacy mode); **scenario 2**: a v1.1.0 sidecar on a formula round (old images stay valid participants); **scenario 3**: v1.2.0 sidecars on a formula round (the full new chain). **Testnet was not changed in any way by this rollout** — no branch, image, host, or trigger; the testnet rollout is a separate, foundation-operator-driven step.

## Pre-rollout state

| Surface | State |
|---|---|
| Scoring service devnet branch | `29cba2e` (pre-formula); latest round 317 `COMPLETE` |
| Sidecar devnet branch | `640023b` (v1.1.0) |
| Participation sidecars | tzeentch `108.61.85.238`, nurgle `207.148.22.37`, slaanesh `64.176.199.51` — all `devnet-participate-latest` v1.1.0 |
| Devnet parameters | cadence 672 h (manual triggers), cutoff 40, max UNL size 3, min gap 5, commit window 900 s, reveal window 300 s |

Both manual triggers below used `reanchor=false`, leaving the standing schedule untouched.

## Executed sequence

1. **Sidecar v1.2.0 devnet images published** — sidecar `devnet` moved `640023b` → `972baa3` (merge of `433bda5`). All three workflows green: [publish](https://github.com/postfiatorg/validator-scoring-sidecar/actions/runs/30034522103), [ci](https://github.com/postfiatorg/validator-scoring-sidecar/actions/runs/30034522076), [vendor-freshness](https://github.com/postfiatorg/validator-scoring-sidecar/actions/runs/30034522225). The blocking vendor gate passed against the still-pre-formula foundation devnet branch, confirming the freshness check's pre-formula-branch tolerance in production.
2. **slaanesh upgraded to v1.2.0** (tzeentch, nurgle deliberately left on v1.1.0). Operational note, recorded honestly: the first `docker compose up -d` used the base compose file only and briefly recreated the container from the verify-only image (~2 minutes, no round active); corrected immediately with the participation overlay (`-f docker-compose.yml -f docker-compose.participate.yml`).
3. **Scenario 1 — round 318** (pre-formula service, v1.2.0 in legacy mode): see below.
4. **Scoring service deployed to devnet** — `devnet` moved `29cba2e` → `9491fcb` (merge of `7f2efea`). [Deploy workflow green](https://github.com/postfiatorg/dynamic-unl-scoring/actions/runs/30036608707); `/health` ok; `/api/scoring/config` now exposes `score_formula` (version 1, weights 50/20/10/10/10, gate margin 25).
5. **nurgle upgraded to v1.2.0** — version matrix for the mixed round: tzeentch v1.1.0, nurgle v1.2.0, slaanesh v1.2.0.
6. **Scenario 2+3 — round 319** (formula service, mixed sidecars): see below.
7. **tzeentch upgraded to v1.2.0** after round 319 sealed — all three hosts now v1.2.0.

## Round 318 — v1.2.0 legacy mode on a pre-formula round

Proves the bimodal sidecar's legacy path live: a v1.2.0 sidecar participating in a round whose manifest has no `code.score_formula` reproduces selection exactly as v1.1.0, so upgrade ordering between operators and the foundation deployment is free.

| Item | Value |
|---|---|
| Round | 318, `COMPLETE`; VL sequence 310 |
| Frozen input package | [`QmbGMKch4fsTG6cjTdxEap2WTqx25Z94WhPihao6v4xTD4`](https://ipfs-testnet.postfiat.org/ipfs/QmbGMKch4fsTG6cjTdxEap2WTqx25Z94WhPihao6v4xTD4) (hash `0ab2e299…5f23`) |
| Final audit bundle | [`QmbC4ex9LpbbvE6MdvXgdkrkHS2KEzgiq2Dr3GeLwczdmk`](https://ipfs-testnet.postfiat.org/ipfs/QmbC4ex9LpbbvE6MdvXgdkrkHS2KEzgiq2Dr3GeLwczdmk) |
| VL receipt memo | `D6596479B1788F7CC20AD4FBD369DDAA60FD82FC99A1DDC91FF40C215B89AB84` |
| VL distribution | [pages commit `1095496e`](https://github.com/postfiatorg/postfiatorg.github.io/commit/1095496e03491ea7f47133b3ff5d64924131c640) |
| Convergence | 3 committers, **3 valid, all at RAW, PARSED, SELECTED_UNL** — sealed under the pre-formula code (no `acceptance_levels` field, as expected) |
| Sealed report | [`QmdcAX52MHCB8AGqvN97TPDKpMdJT8xELB5SKX62A3jAEm`](https://ipfs-testnet.postfiat.org/ipfs/QmdcAX52MHCB8AGqvN97TPDKpMdJT8xELB5SKX62A3jAEm), anchor `57703341CEB03723215FCCEB0A8E5B1F0B34FEC92A8055D8DBA61B663787BA27` |

Per-validator (version → outcome): slaanesh `nHBXSCTw…` **v1.2.0** → valid 3/3 (commit `A6BFAD53…`, reveal `414BBD05…`); nurgle `nHBg5iGp…` v1.1.0 → valid 3/3 (commit `E91E4A3C…`, reveal `247EEA30…`); tzeentch `nHBgo2xS…` v1.1.0 → valid 3/3 (commit `4259B792…`, reveal `5363EAFD…`).

## Round 319 — the first formula round, mixed sidecar versions

Proves the deterministic final-score stage live end to end, with an old-image sidecar participating against it.

| Item | Value |
|---|---|
| Round | 319, `COMPLETE`; VL sequence 311 |
| Frozen input package | [`QmQPFsbgdNjBpodobpG1LAEDZkUSx2Fzpf1pZ2uSJVXs2P`](https://ipfs-testnet.postfiat.org/ipfs/QmQPFsbgdNjBpodobpG1LAEDZkUSx2Fzpf1pZ2uSJVXs2P) (hash `6f6567cf…052f`) |
| Frozen manifest | prompt **v8** (`prompts/scoring_v8.txt`), `code.score_formula` present with `content_sha256 fd4b4306…35ec` (matching the sidecar's vendored set), `schema_version` still 1, selector parameters unchanged |
| Final audit bundle | [`QmX5cEdZcjhjvkJj6AHthQQEXmtQDQxfbHiVujSUhpkGNW`](https://ipfs-testnet.postfiat.org/ipfs/QmX5cEdZcjhjvkJj6AHthQQEXmtQDQxfbHiVujSUhpkGNW) — includes the first published `outputs/final_scores.json` (formula v1 parameters; all three validators model score 82 → final score 87) and `outputs/verification_hashes.json` with the new `final_scores_hash` |
| VL receipt memo | `F4A3DB2E77A4B6DF7BC7188101DF157839A5D18BA7E0C2990584A698EF4FCD82` |
| VL distribution | [pages commit `da5510e5`](https://github.com/postfiatorg/postfiatorg.github.io/commit/da5510e50e5ca47c4381e3f763fec4e53fef678f) — the first formula-selected devnet VL |
| Convergence | 3 committers, **3 valid** — sealed with **`acceptance_levels: ["PARSED", "RAW"]`**, the new self-description live |
| Sealed report | [`QmRmEM77u4xER3D5b71WJQbNzUe8CyxEiiauNcfmiPN4Tb`](https://ipfs-testnet.postfiat.org/ipfs/QmRmEM77u4xER3D5b71WJQbNzUe8CyxEiiauNcfmiPN4Tb), anchor `41E544B123035B8A717EB89B3A7467DE2BCDCE2C562351107F597576DBF4C10C` |

Per-validator (version → outcome): tzeentch `nHBgo2xS…` **v1.1.0** → valid at RAW, PARSED, SELECTED_UNL (commit `86FED13D…`, reveal `0C24AA3E…`); nurgle `nHBg5iGp…` **v1.2.0** → valid 3/3 (commit `184C9201…`, reveal `C4296F29…`); slaanesh `nHBXSCTw…` **v1.2.0** → valid 3/3 (commit `7111FDDF…`, reveal `B5F69A35…`).

### What round 319 proves — and one honest caveat

Live-proven: the v8 response schema parses on the old image's vendored parser (compatibility invariant 1); the additive `code.score_formula` manifest section is ignored by the old image's manifest gate (invariant 3); the foundation publishes formula-based selection with the new artifact and hash; the sealed report self-describes its acceptance levels; the formula-selected VL distributed and anchored without disruption.

The caveat: the old image matched even at `SELECTED_UNL`, because on devnet's three-validator set — every validator far above the cutoff, maximum UNL size 3 — legacy selection (over model scores) and formula selection (over final scores) produce the identical UNL document. The intended diagnostic behavior for an old image (valid on RAW/PARSED with a selection-hash mismatch localizing to the deterministic tail) cannot manifest on a set this small; it is exercised by the automated suites in both repositories, where legacy and formula selection genuinely differ (`tests/test_score.py::test_full_score_formula_round_selects_over_final_scores` in the sidecar, the convergence acceptance tests here). The first environment where it can appear live is one with old-image sidecars and a score distribution that actually straddles selection — which is expected during a community rollout and is, by design, harmless: acceptance ignores the selection level.

## Post-rollout state

All three devnet participation sidecars run `devnet-participate-latest` v1.2.0; the devnet scoring service runs `9491fcb` (v8 + formula + acceptance rule); the standing round schedule was never re-anchored. Testnet remains exactly as it was.
