# Devnet Shadow Verification — Readiness Report

Assesses whether validator-side Dynamic UNL shadow verification is ready for testnet
shadow rollout, from the as-run evidence in `DevnetShadowVerification.md` (rounds 279–286
on devnet, three foundation-controlled validators each scoring on its own Modal
deployment).

## Recommendation: Superseded by M2.8.1 hardening

The full shadow-verification lifecycle ran end to end across both normal and abnormal
conditions. Every failure mode was reported clearly on both the sidecar and foundation
sides, and shadow participation never disrupted canonical VL publication. This was the
correct recommendation before the 2026-07-01 independent assessment. It is now a
historical pre-hardening report; the current M2.9 prerequisite is the M2.8.1
hash-withholding and announcement-binding rerun campaign.

## Convergence behavior (rounds 279–286)

- **Normal rounds (279, 280, 281, 286):** 12/12 validator-rounds `valid`; full
  three-level matches (RAW / PARSED / SELECTED_UNL); zero divergence; convergence reports
  sealed and on-chain-anchored ~3–5 min after reveal close.
- **Pre-hardening sidecar execution signal:** on round 285 the two sidecar deployments
  produced byte-identical output hashes to each other while differing from the
  foundation. This remains useful debugging evidence for that campaign, but the
  post-assessment public claim now depends on the M2.8.1 hash-withholding rerun.
- **Failure and override modes (282–285):** all exercised, each reported clearly, none
  disrupting VL publication (every round reached COMPLETE):
  - missed commit, missed reveal, low participation (282);
  - override rejected and override published (283/284), sidecars correctly `not_tracked`;
  - runtime mismatch → `MANIFEST_INCOMPATIBLE` (285);
  - output divergence detected and reported on both sides (285);
  - artifact validation covered by the continuous per-round hash binding.

## Known issues

| Item | Severity | Classification |
|---|---|---|
| Foundation round-285 single-round non-reproducible scoring (self-corrected at 286; sidecars deterministic and in agreement) | Low — intermittent, foundation-side, no validator-path impact | Follow-up |
| Convergence API `live` phase transiently reports `missing_reveal` before reveals ingest | Low — tooling/reading caveat | Follow-up |
| Cold-Modal scoring latency ~8 min (vs ~2 min warm); the 5-min reveal window is the tightest margin | Low — windows adequate at the 60s poll cadence | Operational note |
| Custom-UNL override fails if any listed key lacks a manifest on the network | Low — expected input validation | Documentation note |

## Blocker for testnet rollout

- **Superseded by the 2026-07-01 hardening gate.** This report remains the
  as-run record for the pre-hardening devnet campaign, but its GO is no longer
  sufficient for M2.9. The Phase 2 independent assessment found that final
  output hashes were public during the commit window, so testnet announcement now
  depends on the M2.8.1 hash-withholding and announcement-binding hardening
  campaign in `docs/CurrentRoadmap.md`.
- **The testnet sidecar image is parked.** The sidecar's `testnet`-participate image
  publication is held by the blocking vendor-freshness gate because the foundation's
  `testnet` branch predates the commit-reveal module. The foundation `testnet` branch
  must catch up to the commit-reveal protocol and the sidecar testnet image must publish
  before testnet shadow verification can run. This is the single hard prerequisite for
  rollout and is operational, not a devnet verification gap.

## Follow-ups (not blockers)

1. Investigate the foundation's round-285 non-reproducible scoring (intermittent
   endpoint/revision behavior); confirm it does not recur under load.
2. `awaiting_reveal` live labeling is addressed by the M2.8.1 hardening work;
   sealed reports still use terminal `missing_reveal`.
3. Operator guidance on warm-vs-cold inference latency relative to the reveal window.

## Conclusion

Devnet shadow verification was proven across normal and abnormal conditions under the
pre-hardening protocol. The GO recorded here is superseded: M2.9 now waits for the
M2.8.1 hardening deployment and rerun campaign.
