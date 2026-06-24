# Devnet Shadow Verification — Milestone 2.8 As-Run Log

As-run evidence for M2.8 (see `docs/CurrentRoadmap.md`). Each normal round exercised
under 2.8.2 is recorded here with its on-chain participation, output match level, and
any manual intervention, so the 2.8.4 readiness report can be assembled from concrete
rounds rather than recollection.

## Environment

- Three foundation-controlled devnet validators run the participation sidecar
  (`agtipft/validator-scoring-sidecar:devnet-participate-latest`): **tzeentch**
  (`nHBgo2xS…`), **nurgle** (`nHBg5iGp…`), **slaanesh** (`nHBXSCTw…`). Host, relay
  wallet, and Modal app per validator are registered in agent-hub `instances.md`.
- Each validator scores on its **own distinct Modal app** (tzeentch default,
  nurgle/slaanesh suffixed) — independent deployments, not a shared endpoint.
- Foundation publisher: `rsm4H6JbPGB7o9P5mVQZxhzKBXs2iv88cn`.
- Announced windows (from `/api/scoring/config`): commit `900s`, reveal `300s`,
  reveal gap `0s`.

## 2.8.2 — Repeated normal scoring rounds

### Round 279 — 2026-06-23 — PASS (3/3 commit-reveal, 3/3 three-level match)

First round with all three sidecars participating on-chain (nurgle and slaanesh joined
2026-06-23, after round 276's windows had closed).

**Round inputs (foundation):**
- `input_frozen_at` 2026-06-23T15:39:35Z · status COMPLETE
- `input_package_hash` `e1320b16…1f3bf3`
- `input_package_cid` `QmbdHeTSb29qmepNVJd3RiR8Ne3QWHWrwwnWVHZFMugQ74`
- `final_bundle_cid` `QmfKJDxVu9mJftJbG1DXo89XzeKCsK4qJBwmMX1d22QcJs`

**Windows (on-chain announcement):**
- Commit: 15:39:42Z → 15:54:42Z (900s)
- Reveal: 15:54:42Z → 15:59:42Z (300s, gap 0)

**Per-validator participation:**

| Validator | Backend | Scored (UTC) | Commit tx | Reveal tx | Levels matched | Convergence outcome |
|---|---|---|---|---|---|---|
| tzeentch | modal | 15:47:45 | `10446C772B33…` | `7961FCCB1BF1…` | RAW, PARSED, SELECTED_UNL | valid |
| nurgle | modal | 15:47:21 | `5FBD7D527381…` | `26A9CE26D899…` | RAW, PARSED, SELECTED_UNL | valid |
| slaanesh | modal | 15:46:44 | `93BF34781C85…` | `E79C506A4370…` | RAW, PARSED, SELECTED_UNL | valid |

Full reveal tx hashes:
- tzeentch `7961FCCB1BF18E9C74F1AD3D6C78CBE1251BB0065472C90ADC79D1D430E58523`
- nurgle `26A9CE26D8991B0B315D806E60AB97C5BA59620AD60127B77034247AE6628661`
- slaanesh `E79C506A43701DD8F9E8270A214372407E828347D8632250A53AF6B26AFB4467`

**Timing:** the two new nodes scored ~7–8 min after input freeze (cold Modal), all
three committed well inside the 900s commit window, and all three revealed 26–70s
after the reveal window opened — comfortably inside the 300s reveal window. No reveal
came close to the window edge.

**Participation:** 3/3 committed, 3/3 revealed, 3/3 matched the foundation at all
three reproducible levels. Three independently deployed Modal apps produced identical
output fingerprints.

**Manual intervention:** none. nurgle logged one transient `HTTP 502` from
`/api/scoring/config` during publisher discovery and auto-recovered on the next pass;
it did not affect the round.

**Operational note — reading the unsealed convergence report:** while `phase=live` and
before reveals are ingested, a committed-but-not-yet-revealed validator is reported as
`missing_reveal`. This is provisional, not terminal — it flips to `valid` once the
reveal lands. Do not treat live-phase `missing_reveal` as a miss; only the sealed
report is authoritative.

**Convergence report (sealed):** sealed 2026-06-23T16:04:08Z — ~4.5 min after reveal
close (15:59:42Z), i.e. the post-reveal grace window. Final summary: 3 committers,
3/3 `valid`, levels matched RAW 3 / PARSED 3 / SELECTED_UNL 3, no divergence
categories, no conflicting commits or reveals.
- `convergence_bundle_cid` `QmTwrrGdiwiNbQyjSDvdxYVKtCUAPGT49PQhoH41uUBUea`
- on-chain anchor (`pf_dynamic_unl_convergence_report_v1`)
  `051F52C6EEF85452400F285708DDECA9464B0209ADF5626A033929F4215F69A6`

### Round 280 — 2026-06-24 — PASS (3/3 commit-reveal, 3/3 three-level match)

Second normal round. All three sidecars now on the identical updated image
(`0ead912bff89`); tzeentch participated on the freshly-pulled image, confirming the
update did not perturb its scoring or signing.

**Round inputs (foundation):**
- status COMPLETE
- `input_package_hash` `4c17c2038385…df3e01`
- `input_package_cid` `QmQiJyoKvNTEtJThhEF9wWnR4ezJJD7Fx6cuq1EvYnQzbE`

**Windows (on-chain announcement):**
- Commit: 09:25:42Z → 09:40:42Z (900s)
- Reveal: 09:40:42Z → 09:45:42Z (300s, gap 0)

**Per-validator participation:**

| Validator | Backend | Commit tx | Reveal tx | Levels matched | Outcome |
|---|---|---|---|---|---|
| tzeentch | modal | `094BFB65434A…` | `05D6ED6056C3…` | RAW, PARSED, SELECTED_UNL | valid |
| nurgle | modal | `3066F5705698…` | `396D1059A43C…` | RAW, PARSED, SELECTED_UNL | valid |
| slaanesh | modal | `66C873573EEC…` | `094B051BC6A9…` | RAW, PARSED, SELECTED_UNL | valid |

Full reveal tx hashes:
- tzeentch `05D6ED6056C35F50A56B9D249EA031860734ED1A76C01FF57A5E96403875C511`
- nurgle `396D1059A43C2A26067A5C2EE5ECBFA298F568E35068E7963E9BDEEC5DE091CA`
- slaanesh `094B051BC6A9CF0E51F5D07FC84405D5BB4B5F04F549FE1520A0A485E5F490D0`

**Timing:** tzeentch scored 09:33:52Z (~8 min after freeze; cold Modal following its
image update). All three committed inside the 900s commit window and revealed inside
the 300s reveal window. Sealed 2026-06-24T09:50:23Z (~4.7 min grace after reveal close).

**Participation:** 3/3 committed, 3/3 revealed, 3/3 matched the foundation at all three
levels.

**Manual intervention:** none.

**Convergence report (sealed):** 3 committers, 3/3 `valid`, levels RAW 3 / PARSED 3 /
SELECTED_UNL 3, no divergence, no conflicting commits or reveals.
- `convergence_bundle_cid` `Qma6HZL2XbF9n7jAniGYTWRUsDVMYKWZdAqRC1Mua2adAW`
- on-chain anchor (`pf_dynamic_unl_convergence_report_v1`)
  `27E20CF528F6C340FC4B0D9F9482E4BB8B112580D851D731D469B6D64B66C371`

### Round 281 — 2026-06-24 — PASS (3/3 commit-reveal, 3/3 three-level match)

Third normal round, immediately after 280.

**Round inputs (foundation):**
- status COMPLETE
- `input_package_hash` `b17d82d76838…09ae4`
- `input_package_cid` `QmPkKnPYA5Cx2GAFDWbysTEE5unL4sVaZmV9uatBzncFEw`

**Windows (on-chain announcement):**
- Commit: 09:51:46Z → 10:06:46Z (900s)
- Reveal: 10:06:46Z → 10:11:46Z (300s, gap 0)

**Per-validator participation:**

| Validator | Backend | Commit tx | Reveal tx | Levels matched | Outcome |
|---|---|---|---|---|---|
| tzeentch | modal | `1D93D1E7DA74…` | `7CA5B87D54C4…` | RAW, PARSED, SELECTED_UNL | valid |
| nurgle | modal | `9A541F79BD00…` | `EA7BB273F075…` | RAW, PARSED, SELECTED_UNL | valid |
| slaanesh | modal | `33D37AE0C6A0…` | `33B3BE8F76E7…` | RAW, PARSED, SELECTED_UNL | valid |

Full reveal tx hashes:
- tzeentch `7CA5B87D54C4851AA227676EC190E1BE0CF27AC5C5907D806842321EB6E64477`
- nurgle `EA7BB273F075982AACE7A15B9027D6B5ACA8A84E9C3C01363E561D5934057567`
- slaanesh `33B3BE8F76E7DB6CCBAC02F18DBC0360E05937877EDDD33DF926DE5162EF3A3A`

**Timing:** tzeentch scored 09:53:55Z (~2 min after freeze; Modal now warm — contrast
with round 280's ~8 min cold start). All three committed inside the commit window and
revealed inside the reveal window. Sealed 2026-06-24T10:14:40Z (~2.9 min grace).

**Participation:** 3/3 committed, 3/3 revealed, 3/3 matched at all three levels.

**Manual intervention:** none.

**Convergence report (sealed):** 3 committers, 3/3 `valid`, levels RAW 3 / PARSED 3 /
SELECTED_UNL 3, no divergence, no conflicting commits or reveals.
- `convergence_bundle_cid` `QmRzFAEsqA1JkPVkUA7e8W4eQqp9NS7wkdGqL8k4CpwWh5`
- on-chain anchor (`pf_dynamic_unl_convergence_report_v1`)
  `03E0033FD6D0E2AF11C74464967F09FA7A6804A7A7B6E3C70C3CAA02DB87FCE1`

## 2.8.2 — Status: COMPLETE (2026-06-24)

Three consecutive normal rounds (279, 280, 281) ran the full lifecycle end to end —
freeze/announce → independent score on three separate Modal apps → commit → reveal →
sealed, on-chain-anchored convergence report.

Aggregate across the three rounds:
- **9/9 validator-rounds `valid`**; **27/27 level matches** (RAW/PARSED/SELECTED_UNL
  across 3 validators × 3 rounds).
- Zero divergence, zero conflicting commits/reveals, zero missed reveals.
- No manual intervention beyond one transient foundation `HTTP 502` (round 279) that
  the sidecar auto-recovered.
- Scoring latency ~2 min (warm Modal) to ~8 min (cold) — always well inside the 900s
  commit window; reveals always landed inside the 300s reveal window.
- Convergence reports sealed ~3–4.7 min after reveal close.

**Remaining for M2.8:** 2.8.3 (override/failure scenarios — rounds 277–278 already
provide real `FAILED`-round data to fold in) and 2.8.4 (devnet readiness report).

## 2.8.3 — Failure and override scenarios

Each scenario deliberately drives an abnormal path and confirms two things: the failure
is reported clearly (sidecar local state **and** foundation convergence outcome), and
the foundation's canonical VL still publishes (the round reaches COMPLETE). Failures are
forced by stopping or altering **sidecar containers only** — the validator nodes and
consensus are untouched — and the fleet is restored to healthy 3/3 after each.

### Round 282 — 2026-06-24 — Missed commit + missed reveal + low participation

One round exercising three failure modes at once, with one healthy participant as
contrast. Forced by stopping sidecar containers: nurgle stopped before the round (never
commits); tzeentch stopped at 15:50:11Z — after its commit landed, ~17s before its
reveal window opened (15:50:28Z) — so it commits but cannot reveal.

**Round inputs:** status COMPLETE; `input_package_hash` `10d2fa3b…ad137`;
`input_package_cid` `QmSzoAXenceyneJXbkXn9xdSfLi9oyiLtJ9ijpHVuNtc5n`.
**Windows:** commit 15:35:28Z → 15:50:28Z; reveal 15:50:28Z → 15:55:28Z.

| Validator | Forced condition | Sidecar local state | Convergence outcome |
|---|---|---|---|
| nurgle | sidecar stopped before round | no commit (absent) | absent — **missed commit** |
| tzeentch | stopped after commit, before reveal | `COMMITTED`, `reveal_error_category=REVEAL_WINDOW_MISSED` | **`missing_reveal`** (commit `AC8C1B83…`, reveal null) |
| slaanesh | untouched (contrast) | `REVEALED`, 3/3 levels | **`valid`** (commit `0B9E138F…`, reveal `1C798743…`) |

**Reported clearly:** ✓ both sides agree — tzeentch's local `REVEAL_WINDOW_MISSED`
matches the foundation's `missing_reveal`; nurgle's absence from the participant set is
the missed-commit signal; slaanesh is `valid` at all three levels.

**VL not disrupted:** ✓ the round reached COMPLETE and sealed despite 2 of 3 validators
failing — summary 2 committers, 1 `valid`, 1 `missing_reveal` (low participation).
- sealed 2026-06-24T15:59:35Z
- `convergence_bundle_cid` `QmeJw5bfhZKfojomJpHQiHSstYuVWpqALc337vFJ98Gz3U`
- on-chain anchor `C1C371DD50F1AB881AD2ACA713862D3E8C48371FE6B37BDCFC92D55A75F6E9DF`

**Restore:** nurgle and tzeentch sidecars restarted after the seal; fleet back to
running 3/3.

### Override rounds — 2026-06-24 — sidecars correctly skip; VL publishes

Two custom-UNL admin overrides (`POST /api/scoring/admin/publish-unl/custom`),
confirming the sidecars never participate in override rounds — which carry no
commit-reveal announcement and no frozen input package — and that override VL
publication is independent of sidecar participation.

- **Round 283 — override rejected (input validation).** A six-key custom UNL that
  included validators not present on devnet failed at VL signing:
  `VL_SIGNED: Missing manifest for validator nHUKG1ZY…`. The round ended `FAILED`, the
  canonical UNL was left unchanged (still the three devnet validators), and round 283
  convergence is `not_tracked` (0 participants). Clean failure, no disruption.
- **Round 284 — override published.** A custom UNL of the three devnet validators ran
  the override state machine to `COMPLETE`: VL signed (vl_sequence 277), distributed to
  GitHub Pages (commit `9c4573d…`), and anchored on-chain (`pf_dynamic_unl_override`
  memo `06F124C8C0…`). Round 284 convergence is `not_tracked` with **0 participants** —
  the sidecars did not commit or reveal, exactly as expected for an override round.

**Reported clearly / VL not disrupted:** ✓ override rounds are excluded from convergence
tracking (`not_tracked`); the failed override surfaced a precise `error_message` and
preserved the prior UNL; the successful override published a VL through the canonical
path (GitHub Pages + on-chain memo) with no sidecar involvement.

### Round 285 — 2026-06-24 — Runtime mismatch + an unplanned output divergence

Intended as the runtime-mismatch test: nurgle's deployment record was flipped to
local-mode with a bogus model revision (a local-mode record is never auto-repaired by
the Modal provisioner). It produced that failure mode cleanly and, unexpectedly, also
surfaced a genuine output divergence on the two untouched validators.

**Round inputs:** `input_package_hash` `23ff44114b40…e663`;
`input_package_cid` `QmQWS2syqieaJgxqBnMd3oW9MJTQZaYgWg5PzqUJPhi5jw`.
**Sealed** 2026-06-24T18:32:06Z · `convergence_bundle_cid`
`QmT9kbq3F8vKXswbD8mqo3Zi5P2fhquB5ErZJUs2BYntxP` · anchor `9654458B1CD8…`.

| Validator | Condition | Sidecar local state | Convergence |
|---|---|---|---|
| nurgle | record → local-mode, revision `MISMATCH-TEST-DO-NOT-USE` | `SCORING_FAILED` / `MANIFEST_INCOMPATIBLE` (field `model.revision`), no commit | absent |
| tzeentch | untouched | `REVEALED`, `OUTPUT_DIVERGENCE` — diverged RAW + PARSED, matched SELECTED_UNL | `divergent` (stage RAW) |
| slaanesh | untouched | `REVEALED`, `OUTPUT_DIVERGENCE` — diverged RAW + PARSED, matched SELECTED_UNL | `divergent` (stage RAW) |

**Runtime mismatch — reported clearly:** ✓ nurgle's `MANIFEST_INCOMPATIBLE` carried the
exact field and mismatch (`manifest model.revision 'e89b16eb…' does not match deployed
'MISMATCH-TEST-DO-NOT-USE'`); auto-provision did not silently repair the local-mode
record; nurgle skipped scoring and did not commit. The record was restored from backup
afterward.

**Unplanned finding — OUTPUT_DIVERGENCE:** both untouched validators, on the same
deployed model revision (`e89b16eb…`) and the same hash-verified frozen inputs, produced
raw model responses that diverged from the foundation's (RAW and PARSED levels), while
the downstream UNL selection still matched. Rounds 279–282 matched at all three levels,
so this divergence is new. The shadow path detected and reported it precisely on both
sides (sidecar `error_details` listing diverged/matched levels; convergence
`OUTPUT_DIVERGENCE`, stage RAW).

A hash comparison localizes the cause: tzeentch and slaanesh — on **separate** Modal
deployments — produced **byte-identical** `model_response_hash` (`88114937…`) and
`validator_scores_hash` (`d77c4363…`) to each other, while the foundation's published
hashes differ (`6ec9c61c…`, `3e929ecb…`); all three agree on `selected_unl_hash`
(`214007ba…`). So this is **not** sidecar nondeterminism — the two independent
reproductions agree with each other, and the **foundation's round-285 scoring is the
outlier**. It also incidentally demonstrates genuine independent execution: had the
sidecars merely echoed the foundation they would match it; instead they reproduce each
other and disagree with it. The likely cause is a foundation-side model/runtime
inconsistency for this round (e.g. the scoring endpoint not serving the manifest-pinned
revision `e89b16eb…`).

**Resolution (round 286).** The clean follow-up round came back **3/3 `valid` at all
levels** — the foundation and both sidecars (plus the restored nurgle) matched again.
So the round-285 divergence was a **transient, single-round foundation anomaly** that
self-corrected; the deterministic reproductions never broke. Worth a foundation-side
look at why round 285 specifically produced a non-reproducible scoring (intermittent
endpoint/revision behavior), but it is not an ongoing break.

**VL not disrupted:** ✓ the round reached COMPLETE and sealed despite the failures.

### Artifact-validation failure — covered by the per-round hash binding (not force-tested)

A fetched input package failing its content-hash check is impractical to force on the
live network without serving deliberately altered content: the sidecar's retrieval falls
back from the IPFS gateway to the foundation's HTTPS source, so it always obtains content
that matches the announced hash, and corrupting the local cache produces a different
failure (parser / model-request errors), not the hash-mismatch path. Rather than stand up
a tampering gateway, this mode is taken as covered by:
- the sidecar's verification unit tests (hash-mismatch and tampered-file cases); and
- the on-chain hash binding exercised on **every** round — the sidecar resolves each
  announced round by `input_package_hash`, confirms the `input_package_cid`, and verifies
  every file against the canonical JSON hash before scoring. Rounds 279–286 all passed
  this check, so the artifact-validation guard runs continuously in production, not just
  in a one-off test.

## 2.8.3 — Status: COMPLETE (2026-06-24)

All failure and override modes were exercised; each was reported clearly on both the
sidecar and foundation sides, and none disrupted canonical VL publication (every round
still reached COMPLETE):
- **Missed commit / missed reveal / low participation** (round 282) — nurgle absent,
  tzeentch `missing_reveal` / local `REVEAL_WINDOW_MISSED`, slaanesh `valid`.
- **Override rounds** (283 rejected, 284 published) — sidecars `not_tracked`, 0
  participants; canonical UNL preserved on the rejected override.
- **Runtime mismatch** (round 285, nurgle) — `MANIFEST_INCOMPATIBLE` with the exact field
  and message; auto-provision did not silently repair a local-mode record.
- **Output divergence** (round 285, unplanned) — detected and reported precisely; the
  hash comparison showed the two independent sidecars agree byte-for-byte while the
  foundation was the single-round outlier (self-corrected at round 286). This also
  evidences genuine independent execution.
- **Artifact validation** — covered by the continuous per-round hash binding and the
  sidecar's verification unit tests (above).

**Follow-up (not a 2.8.3 blocker):** investigate why the foundation's round-285 scoring
was non-reproducible for that one round (intermittent endpoint/revision behavior).

**Remaining for M2.8:** 2.8.4 (devnet readiness report).
