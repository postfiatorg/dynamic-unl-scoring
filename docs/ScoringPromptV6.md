# Scoring Prompt v6 — Diversity Narration Revision

`prompts/scoring_v6.txt` replaces `scoring_v5.txt` as the active scoring prompt. It corrects how the model narrates a validator's geographic and infrastructure diversity. No scoring rubric, dimension weight, selection threshold, or operating parameter changed; `scoring_v5.txt` is retained on disk for audit.

## Why

In testnet round 13, the five Hetzner/Finland validators received a diversity sub-score of 75 but reasoning text such as "Finland location on Hetzner provides good geographic diversity." That phrasing overstates a 75 and does not acknowledge that those validators share the Hetzner ASN with the largest provider group in the set. The cause was the prompt's own few-shot example: it praised a concentrated setup ("Geographic diversity is useful because Germany is underrepresented") while Germany was in fact the most common country in the scored set. The model reproduced that framing.

## The change

Two lines differ from v5 — the two worked-example `reasoning` strings in the few-shot block. The rewritten examples describe diversity relative to the scored set, name the shared country and provider as the limiting factor, and use countries/providers that do not appear in the live set so nothing is anchored. No instruction, rubric, or weight was altered.

## Validation

The template is hash-pinned in each round's execution manifest and independently reproduced by validator sidecars, so the change was validated by replaying a completed round through v6 on the pinned deterministic runtime.

Round 13's frozen `model_request.json` was re-rendered through v6 (validator data byte-identical to the round; the v5 re-render reproduced the round's messages exactly) and run on the same pinned endpoint (model revision `e89b16eb…`, SGLang image digest `5d9ec715…`, H100, temperature 0). Comparison against the published round 13 outputs:

- **Selected validator set unchanged** — the same 35 master keys are selected; only intra-list ordering shifts.
- **No cutoff crossings** — no validator moved across the score-40 eligibility line.
- **Diversity group ordering preserved** — median diversity ordering held: Singapore/CherryServers > Finland/Hetzner > US > Germany/Hetzner.
- **Narration corrected** — all five Finland/Hetzner validators now name Hetzner and are no longer described as good/strong diversity; all ten unresolved-endpoint validators name no country and state the endpoint is unresolved.

Expected tradeoff, inherent to editing a single-pass model's prompt: overall scores shifted on 16 of 45 validators, 15 of them by 1–2 points and one by 7, with the trusted set and the eligibility cutoff unaffected. Diversity sub-scores for concentrated groups shifted down while preserving the relative ordering.
