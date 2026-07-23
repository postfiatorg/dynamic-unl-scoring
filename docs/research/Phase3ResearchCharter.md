# Phase 3 Research Charter

## Deterministic and Verifiable AI-Assisted Validator-Set Governance for UNL-Based Consensus Networks

**Status:** Research charter and experimental design, version 0.1

**Date:** 2026-07-22

**Owner:** Post Fiat Foundation

**Evidence cutoff:** 2026-07-22

**Canonical format:** Markdown; the PDF is a rendered distribution copy

## 1. Purpose and decision to be made

Phase 3 proposes moving Post Fiat's dynamic Unique Node List (UNL) system from observational scoring to protocol-relevant validator-set governance. This is not a routine implementation milestone. It changes who can influence consensus membership, how that influence is justified, and what happens when the scoring system, its data, or the current validator set is attacked.

This document is the charter for the research that must precede that change. It does not assume that every item in the current roadmap is correct. The roadmap is a working hypothesis informed by successful Phase 0, Phase 1, and Phase 2 results [R0]. The research process is explicitly allowed to revise it when threat analysis, experiments, or protocol modeling reveal a safer design.

The decision this research must support is:

> Under what measurable conditions, if any, may the output of a deterministic AI-assisted scoring process safely become binding validator-set state on a UNL-based consensus network?

The proposed answer is not "let an LLM control the network." The candidate architecture is a constrained governance pipeline in which independent observers produce signed evidence, hard rules enforce non-negotiable safety requirements, an open-weight deterministic LLM performs bounded contextual evaluation, a mechanical algorithm constructs the proposed UNL, and the current authorized validator set automatically ratifies the exact result it independently reproduced. A transitional Foundation control may pause or reject a suspicious change, but may not install an arbitrary replacement UNL through that path.

## 2. Executive summary

Post Fiat has already demonstrated several prerequisites for this research:

- deterministic inference under pinned model, runtime, prompt, and input conditions;
- multiple sidecars independently producing matching raw output, parsed scores, and selected UNLs;
- commit-reveal and artifact publication that make a scoring round auditable;
- a live model-governance process for comparing an incumbent model with challengers; and
- an operating history service and scoring pipeline that can be evaluated against real rounds.

The latest public testnet evidence available at the cutoff is round 15, sealed on 2026-07-21. It reports 18 committers, 18 valid participants, 18 matches at each of the RAW, PARSED, and SELECTED_UNL levels, and no divergence categories [R1]. Earlier Phase 2 campaigns also showed that sidecars can expose anomalies rather than merely reproduce Foundation output [R2]. These results establish feasibility of deterministic reproduction. They do not yet establish safe decentralized governance.

Five unresolved problems dominate Phase 3:

1. **Evidence can be incomplete, centralized, or manipulated.** The Validator History Service (VHS) is presently a privileged observation point. Location and provider data can represent a VPN, proxy, NAT gateway, relay, or sentry rather than the validator's true infrastructure. Websites can be broken, misleading, or adversarial.
2. **A real-world identity is not the same as an independent operator.** KYC or KYB can raise the cost of Sybil attacks, but related companies, affiliates, common infrastructure, or a single controlling party can still appear as separate validators.
3. **Determinism does not make an LLM transparent or correct.** Open weights and deterministic execution make results reproducible, not inherently safe. Attackers can repeatedly test public logic and optimize evidence against it.
4. **Matching output is not the same as protocol authorization.** Sidecars can converge on an identical UNL without that result having a valid, replay-resistant authorization certificate or preserving the quorum and overlap assumptions of consensus.
5. **Safety and liveness can conflict during transition.** A veto can prevent a bad change but can also freeze a good one. An incumbent validator threshold can prevent hostile capture but can also create a cartel that blocks successors.

The research must therefore test the complete system, not only scoring quality. Its core comparison is between the LLM-assisted design and transparent non-LLM baselines. The formula baseline is a null hypothesis and operational fallback, not an assumption that a simple formula can capture the same contextual reasoning. The LLM is justified only if it provides measurable value beyond those baselines without weakening reproducibility, adversarial robustness, or protocol safety.

## 3. Scope

### 3.1 In scope

- validator evidence collection, normalization, signing, publication, and independent reconstruction;
- validator identity, controller independence, and privacy-preserving credential requirements;
- hard eligibility rules, correlated-failure constraints, contextual scoring, and mechanical UNL construction;
- deterministic model execution and model-governance risks;
- automated sidecar ratification, authorization thresholds, challenge periods, and rollback behavior;
- adversarial tests for Sybil behavior, evidence manipulation, prompt injection, collusion, incumbency, and common-mode model error;
- consensus-safety analysis for UNL overlap, membership churn, quorum thresholds, and failure recovery; and
- empirical criteria that can approve, revise, postpone, or reject the proposed Phase 3 design.

### 3.2 Out of scope for this first paper

- a complete production implementation in Cobalt or Rust;
- claims that the design is production-safe before protocol modeling and adversarial experiments are complete;
- a comprehensive legal or regulatory opinion on KYC, KYB, sanctions, or data protection;
- post-quantum migration beyond noting compatibility requirements; and
- a general theory of decentralized AI governance outside validator-set selection.

## 4. Terminology and separation of authority

The architecture must keep five different decisions separate. Combining them in one model prompt would make failures difficult to diagnose and governance difficult to constrain.

| Layer | Question | Proposed authority |
|---|---|---|
| Observation | What verifiable events and attributes were observed? | Independent observers producing signed records |
| Eligibility | Which candidates satisfy non-negotiable safety requirements? | Deterministic hard rules |
| Contextual evaluation | How strong is each eligible candidate across interacting evidence and edge cases? | Pinned deterministic LLM with bounded inputs |
| Construction | Which exact set satisfies size, diversity, overlap, and churn constraints? | Deterministic mechanical selector |
| Authorization | May this exact set become network state? | Threshold-signed reproduction by authorized validators, subject to transition safeguards |

"Deterministic" means that the pinned model artifact, inference runtime, decoding parameters, prompt, rule versions, and canonical input package reproduce the same output. It does not mean that the model's reasoning is mathematically proven, that an explanation is a faithful causal account, or that the output is secure against manipulated inputs.

"Decentralized" does not require every source to be equally trusted. It requires that no single unchallengeable source can silently define the facts, scoring result, or authorized successor set.

## 5. Evidence baseline and limits of current claims

### 5.1 Results that support proceeding with research

Phase 0 documented bit-identical repeatability across five complete runs and later pinned the Qwen3.6 27B FP8 execution profile used in the active path [R3]. Scoring prompt version 6 improved reasoning quality while replaying the same 35-validator selected set and preserving cutoff membership [R4]. The prompt also correctly treats country and Autonomous System Number (ASN) as evidence about the observable public endpoint, not proof of physical location or operator independence [R5].

Phase 2 introduced signed commit-reveal commitments over a round's input and output artifacts [R6]. Devnet shadow verification recorded 27 of 27 level matches across three sidecars in rounds 279-281, while later failure-oriented rounds demonstrated that the verification path can detect inconsistent Foundation execution [R2]. The M2.8.1 work then removed mid-window output leakage as a source of false independence and recorded a clean multi-round campaign with fault injection [R7].

The model-governance repository defines a frozen evaluation procedure, ledger-derived judge selection, mechanical disqualification, challenger evaluation, and sidecar verification [R8]. Its first recorded pool refresh pinned an incumbent and two challenger artifacts [R9]. This is a meaningful governance foundation, although the use of an LLM judge remains a research risk rather than a resolved fact.

### 5.2 What these results do not prove

Current results do not show that:

- VHS observations are complete or independent;
- identity claims correspond to distinct controlling parties;
- a selected UNL preserves consensus safety through all transitions;
- deterministic agreement remains stable across heterogeneous production hardware and failure modes;
- public evidence cannot be optimized to game the scorer;
- an LLM judge is unbiased when comparing models, especially models from related families;
- validators will remain available and willing to run the process; or
- the Foundation's current authority can be removed without introducing capture or deadlock.

These are the target claims of the research, not assumptions available to it.

## 6. Proposed target architecture

The candidate end-to-end flow is:

```text
independent observers
        |
        v
signed, content-addressed evidence packages
        |
        v
canonical normalization and conflict reporting
        |
        v
hard eligibility and correlated-risk gates
        |
        v
bounded deterministic LLM evaluation
        |
        v
mechanical constrained UNL construction
        |
        v
independent sidecar reproduction
        |
        v
threshold-signed convergence certificate
        |
        v
challenge delay and transitional emergency brake
        |
        v
activation, or retention of the previous known-good UNL
```

Every arrow must be auditable. Every artifact needed to replay a decision must be content-addressed and versioned. A failure to produce a valid next-state certificate must leave the previous known-good UNL active; it must not create an implicit empty set or an arbitrary fallback set.

### 6.1 Independent evidence layer

The near-term VHS design should adopt two existing proposals from its own trust analysis [R10][R11]:

1. Publish the signed validation messages used to calculate participation and agreement, allowing third parties to recompute the derived values.
2. Accept observations from multiple genuinely independent collectors and deterministically aggregate the union of valid signed messages while explicitly reporting disagreements and observation gaps.

An initial deployment could include a Foundation observer, a community-operated observer, and an academic or otherwise independent institutional observer. Independence must be demonstrated through separate administration, credentials, infrastructure, and publication paths; three nominal processes under one controller are one trust domain.

The Foundation may assemble and relay evidence packages, but it must not be able to silently alter, omit, or redefine source observations. For each field, the package must include provenance, observation time, signature or attestation, normalization version, and confidence or conflict status.

### 6.2 Identity and controller independence

The exact identity mechanism remains an open design decision. A candidate is a third-party KYC or KYB credential cryptographically bound to the validator master key and published as an on-chain commitment or reference. The credential must support expiration, revocation, key rotation, and minimum necessary disclosure.

Identity verification is a Sybil-resistance input, not proof of operational independence. The system also needs evidence about beneficial control or organizational relationship, infrastructure correlation, common administration, and repeated coordinated behavior. Hard caps should prevent one verified controller or a closely related controller group from occupying multiple positions beyond an explicitly justified limit.

Research must compare privacy and accountability options, including public entity claims, selective-disclosure credentials, and attestations that reveal uniqueness or relationship constraints without publishing unnecessary personal information.

### 6.3 Website, domain, and public-endpoint evidence

A domain or website should not receive trust merely for existing or passing a one-time attestation. The evidence layer should produce normalized facts such as:

- signed ownership challenge under a well-known path;
- DNS and HTTPS availability over time;
- certificate and domain-history signals;
- consistency with an identity credential;
- change frequency and failure history; and
- bounded, schema-validated metadata.

Raw webpage content must not be placed in the model prompt. Web content is untrusted data and can contain instructions intended to manipulate an LLM. Existing structured strings such as domain, entity name, ISP name, and future metadata must also be length-limited, normalized, escaped, and tested for indirect prompt-injection behavior [R12][R13]. This is a prospective attack surface to test; it is not a claim that the current prompt has been successfully exploited.

Country and ASN must remain endpoint evidence only. The design should use multi-vantage reachability and latency, ASN and route history, provider correlation, sudden endpoint changes, and observer disagreement. It should reward measurable reduction in correlated failure risk, not rarity of a country label. A VPN endpoint in a rare jurisdiction must not by itself improve a score.

### 6.4 Hard rules and the bounded role of the LLM

The LLM must not decide whether cryptographic evidence is valid, whether a mandatory identity credential is present, whether an authorization threshold is reached, or whether a proposed set violates an absolute safety bound. Those are deterministic rule-engine responsibilities.

Candidate hard gates include:

- valid validator master key and signatures;
- current identity credential where required;
- minimum observation history and participation;
- no disqualifying software or protocol incompatibility;
- controller, organization, provider, ASN, region, and infrastructure caps;
- minimum overlap with the previous known-good set;
- maximum additions, removals, and total churn per activation;
- evidence freshness and minimum independent-observer coverage; and
- valid recovery and rollback references.

After those gates, the LLM may evaluate interacting evidence, ambiguous operational tradeoffs, maturity, reputation, reliability patterns, and edge cases that are impractical to enumerate in one fixed formula. Its output must conform to a strict schema and include per-dimension values, normalized evidence references, and concise justification. The selector then constructs the exact UNL mechanically from eligible scores and constraints.

The system should remain open: model weights, prompt, inference profile, rule code, input package, and selector must all be replayable. Openness enables audit, but also enables gaming. Therefore security must come primarily from independently measured, costly-to-fake evidence and hard constraints, not from hidden scoring logic.

### 6.5 Mechanical UNL construction

Selecting the top scores is insufficient because individual quality and set-level safety are different objectives. The selector must solve a constrained set-construction problem with explicit rules for:

- maximum size and score cutoff;
- continuity with the current set;
- controller and correlated-infrastructure concentration;
- diversity floors or caps supported by reliable evidence;
- tie-breaking;
- newcomer admission and probation;
- incumbent removal; and
- deterministic behavior when constraints cannot all be satisfied.

The selector's inputs, constraint version, result, and proof of constraint checks must be part of the convergence artifact. Any optimization objective must be public and independently implementable.

### 6.6 Automatic sidecar ratification and protocol authorization

Validators should not manually vote on whether they like the model's answer. Each authorized sidecar should independently retrieve the canonical evidence package, apply the same rule and model versions, construct the same proposed UNL, and automatically sign a commitment to that exact result.

The current commit-reveal protocol is a plausible base but must be extended or replaced with a replay-resistant next-state authorization certificate. At minimum, the signed statement should bind:

- network and round or epoch;
- previous authorized registry or UNL hash;
- evidence-package hash;
- normalization, rule, prompt, model, runtime, and selector versions;
- proposed UNL hash;
- challenge-window and activation parameters; and
- signer identity and signature scheme.

This creates a critical distinction:

- **computational convergence:** independent executions produced the same output; and
- **protocol authorization:** the required current authorities signed the same eligible next state under the correct transition rules.

The signature is not a discretionary approval of model reasoning. It is an automated attestation that the signer reproduced the exact deterministic state transition and found it valid under hard rules.

The final threshold cannot be selected by intuition alone. A value such as two-thirds may sound reasonable but must be derived from PFTL's actual quorum, UNL-overlap, fault, and liveness assumptions. Threshold and maximum-churn parameters must be studied together.

### 6.7 Challenge period and transitional Foundation role

During the first Phase 3 deployment, the Foundation may operate an emergency brake with a narrowly defined power: pause or reject an activation during a challenge window when evidence of manipulation, software failure, unsafe overlap, or model failure appears. The same mechanism must not allow the Foundation to install a different arbitrary UNL.

Any brake action must be signed, time-bounded, public, reason-coded, and followed by an incident report. Repeated or indefinite use must trigger an automatic governance review. The current known-good UNL remains active while a rejected round is investigated.

This is an emergency brake, not a steering wheel. A later stage should replace the single-Foundation brake with a multi-party guardian structure or remove it when empirical and formal safety evidence supports doing so. The research must specify the exit criteria in advance.

## 7. Threat model and required mitigations

| Threat | Why it matters | Candidate control | Required evidence before activation |
|---|---|---|---|
| Sybil validators | One controller can capture apparent diversity | Key-bound identity, controller graph, caps, history requirement | Red-team attempts and false-positive/negative analysis |
| VHS omission or equivocation | A central observer can alter derived reputation | Signed raw votes, multiple observers, deterministic union, conflict reports | Reproduction across independent collectors under packet loss and Byzantine behavior |
| VPN or sentry location gaming | Endpoint rarity can be mistaken for independence | Multi-vantage history and correlation, no reward for country rarity alone | Controlled proxy, migration, and route-manipulation experiments |
| Website or metadata prompt injection | Untrusted text can redirect model behavior | No raw pages, strict schemas, normalization, allowlists, injection suite | Zero unauthorized instruction-following in a published attack corpus |
| Public-score optimization | Open rules allow cosmetic behavior | Costly-to-fake longitudinal evidence, withheld test periods, behavioral correlation | Adaptive attacker simulation against LLM and baselines |
| Common-mode model error | All honest sidecars can identically reproduce a bad answer | Hard gates, selector constraints, model diversity tests, challenge delay | Counterexample and distribution-shift evaluation |
| LLM-as-judge bias | Model governance may favor family, style, or self | Blinded evaluation, multiple judge families, human rubric audit, stability analysis | Measured judge agreement and bias bounds [R14][R15] |
| Incumbent cartel | Current validators can block legitimate successors | Bounded terms, transparent non-signing, liveness path, staged admission | Governance simulation under strategic abstention |
| Unsafe churn or overlap | A good-looking set may break consensus assumptions | Hard overlap/churn constraints derived from protocol model | Safety and liveness analysis across worst-case transitions [R16][R17] |
| Compromised current set | Threshold authorization can certify hostile state | Challenge delay, guardians, out-of-band recovery constitution | Recovery exercise with explicit trust assumptions |
| Foundation veto abuse | Transitional safety control becomes permanent control | Narrow reject-only power, transparency, time limit, exit criteria | Public drill and measurable decentralization milestones |
| KYC privacy or exclusion | Accountability can create surveillance or gatekeeping | Minimal disclosure, revocation, multiple issuers, appeals | Privacy and accessibility review before mandatory deployment |

The threat taxonomy should align with NIST's adversarial machine-learning terminology so attacks and mitigations are reported consistently [R18].

## 8. Research questions and hypotheses

### RQ1 - Does the LLM add value beyond transparent formulas?

**Hypothesis H1:** Under identical hard gates and set-construction constraints, the LLM-assisted evaluator will outperform reasonable transparent baselines on blinded expert assessment of multi-factor validator quality and on prediction of subsequent operational outcomes.

Baselines should include the current scoring approach, an interpretable weighted formula, a rules-only selector, and ablations that remove one evidence family at a time. The formula is deliberately strong and public. Failure to beat it means the additional LLM complexity is not justified for binding governance.

### RQ2 - Can adversarial evidence change decisions without changing real validator quality?

**Hypothesis H2:** Schema normalization, signed longitudinal evidence, hard gates, and multi-observer corroboration will materially reduce score and selection changes caused by websites, metadata strings, VPNs, proxies, fabricated affiliations, and coordinated endpoint changes.

### RQ3 - Can independent observers reconstruct the same factual input?

**Hypothesis H3:** Given a defined observation window and signed validation messages, independent collectors will produce equivalent canonical evidence packages or explicit, bounded conflict reports. Silent disagreement is a failure.

### RQ4 - Is model governance stable and sufficiently unbiased?

**Hypothesis H4:** Challenger promotion decisions will remain materially stable across qualified judge families, randomized presentation, repeated trials, and human rubric audits. A candidate must not win primarily because of judge-family affinity, verbosity, or explanation style.

### RQ5 - Does the transition protocol preserve safety and useful liveness?

**Hypothesis H5:** For the modeled Byzantine bound, no authorized transition violates required UNL overlap or quorum conditions, while honest validators can still activate a valid successor under defined crash, network-partition, abstention, and observer-failure scenarios.

### RQ6 - Are participation and operating costs sustainable?

**Hypothesis H6:** Honest validators and observers can reproduce, sign, store, and audit rounds within a bounded resource budget, and the system has a credible incentive or requirement for continued participation without relying on invisible Foundation operations.

## 9. Experimental program

### 9.1 Dataset and artifact design

Construct a versioned corpus from completed Phase 1 and Phase 2 rounds, preserving the exact evidence packages available at each historical cutoff. Add synthetic and controlled adversarial cases without contaminating the historical ground truth. Every case should include a manifest, provenance, expected invariant checks, and a disclosure of which fields were modified.

Future rounds should preserve raw signed observations, canonical normalized inputs, model and runtime artifacts, scores, selector outputs, commitments, reveals, authorization certificates, challenges, and later operational outcomes. Evaluation must prevent future information from leaking into historical decisions.

### 9.2 Comparative scoring study

Run all eligible candidates through:

1. rules-only eligibility and deterministic selection;
2. a transparent weighted-formula evaluator;
3. the incumbent LLM evaluator;
4. qualified challenger models; and
5. ablated versions without identity, geography, website, or selected operational signals.

Compare ranking and selected-set stability, calibration, expert rubric scores, later uptime and agreement, correlated-failure exposure, turnover, explanation usefulness, and computational cost. Report both aggregate metrics and cutoff-sensitive cases because small ranking differences near admission boundaries can have protocol-level effects.

### 9.3 Adversarial evidence study

The attack suite should include indirect prompt injection, Unicode and serialization attacks, exaggerated or broken websites, domain transfer, KYC-valid related entities, VPN and sentry relocation, ASN churn, observer omission, observer equivocation, short-term reliability boosting, coordinated validator behavior, stale credentials, and targeted attacks on candidates near the cutoff.

Success means the system either preserves the decision, rejects the malformed evidence, or explicitly lowers confidence and pauses activation. Producing the same wrong output on all sidecars is not success.

### 9.4 Observer-independence study

Deploy at least three independently administered observers. Compare signed-message sets, derived agreement, timing, reachability, and normalized packages under normal operation, packet loss, regional partition, malicious omission, and delayed publication. Quantify how much one observer can influence a candidate and whether the aggregation rule introduces new denial-of-service opportunities.

### 9.5 Governance and protocol study

Use trace-driven simulation and, where feasible, formal specification to analyze authorization thresholds, validator faults, partitions, abstention, overlap, and churn. Model the current set authorizing a successor, successive rounds of membership change, simultaneous model and UNL changes, and recovery when the current set or Foundation brake is compromised.

The study must distinguish safety from liveness and state every trust assumption. Cobalt provides a relevant framework for reasoning about Byzantine agreement in open networks, but its existence does not by itself validate the proposed governance transition [R16]. XRPL's UNL and amendment practices provide useful comparison points, including the importance of overlap and sustained validator support, but PFTL parameters require their own derivation [R17][R19].

### 9.6 Model-governance audit

Replay promotion exams with randomized candidate order, blinded names, multiple qualified judge models, structured human review, and robustness tests against style and verbosity. Measure inter-judge agreement, promotion stability, self or family preference, and downstream scoring differences. A model change and a validator-set change should not activate in the same epoch until their combined risk is understood.

## 10. Metrics and decision gates

Exact numerical thresholds should be registered before the final evaluation dataset is opened. The research team must justify them from protocol requirements and measured baselines rather than selecting favorable values after results are known.

Minimum gate categories are:

- **Reproducibility:** artifact-complete reruns produce byte-identical or explicitly equivalent results across supported independent environments.
- **Evidence integrity:** signed observations can be independently verified; observer disagreement cannot be silently collapsed.
- **Adversarial robustness:** attacks cannot create unauthorized prompt behavior or unsafe set changes within the registered threat model.
- **Marginal value:** the LLM shows meaningful benefit over transparent baselines on pre-registered quality measures.
- **Set safety:** every proposed transition satisfies derived overlap, concentration, churn, and quorum invariants.
- **Authorization safety:** only the exact reproduced next state can receive a valid certificate; replay and cross-round substitution fail.
- **Liveness:** honest operation can progress under the registered fault and participation assumptions.
- **Recovery:** failed or challenged rounds retain the previous known-good state, and emergency procedures are exercised.
- **Governance accountability:** vetoes, abstentions, model changes, evidence conflicts, and exceptions are public and attributable.
- **Operational feasibility:** resource use and round duration are sustainable for non-Foundation validators and observers.

Phase 3 activation should be rejected or redesigned if any of the following occurs:

- the LLM does not materially outperform a transparent baseline;
- modest metadata or endpoint manipulation repeatedly changes admission outcomes;
- one observer can materially define results without detectable evidence;
- controller independence cannot be enforced to an acceptable confidence level;
- model promotion depends strongly on the judge model or presentation style;
- no threshold and churn configuration satisfies both safety and useful liveness;
- Foundation intervention remains necessary in ordinary rounds; or
- independent operators cannot reproduce the process at acceptable cost.

Rejection of the LLM component would not invalidate dynamic UNLs. A rules-only or formula-assisted protocol may remain a viable fallback. Rejection of binding automation may likewise leave a transparent advisory system as the correct near-term outcome.

## 11. Staged deployment implications

The research should produce explicit gates for three stages:

### Stage A - Research and shadow governance

No scoring output changes authoritative consensus membership. Independent evidence collection, baselines, attack testing, protocol modeling, and professor review occur here.

### Stage B - Transitional binding governance

The current authorized validator set automatically ratifies exact reproduced successors. A public challenge period and narrow Foundation reject-only emergency brake remain. Churn is conservative, failure preserves the old set, and every activation publishes a complete certificate.

### Stage C - Mature decentralized governance

The Foundation loses unilateral emergency power and becomes one guardian among independently governed participants, or the brake is removed. Observer diversity, controller-independence controls, and recovery procedures meet registered targets across a sustained operational period.

Moving between stages is an evidence-based protocol decision, not a calendar milestone.

## 12. Open design decisions

The paper must resolve or narrow these questions before implementation is treated as production work:

1. Which identity issuers and credential scheme can bind an entity to a validator key while supporting privacy, revocation, and appeal?
2. What constitutes the same controlling party, and how is uncertain relationship evidence handled?
3. How many independent observers are required, and what aggregation rule resists both omission and flooding?
4. Which evidence fields are safe and useful enough to reach the LLM?
5. Which hard gates, concentration caps, overlap rules, and churn limits follow from the consensus model?
6. What exact threshold authorizes a successor, and what happens when incumbents abstain strategically?
7. How long is the challenge window, who may raise a challenge, and what objective effects does it have?
8. What are the Foundation brake's sunset conditions and the recovery path if the Foundation or current set is compromised?
9. How often may the model, prompt, rules, or UNL change, and which changes must be separated across epochs?
10. What incentives or duties keep observers and sidecars available over time?

## 13. Research integrity and external collaboration

Academic collaborators should be engaged before experiments and acceptance thresholds are finalized, not asked only to endorse finished results. Suitable contributions include threat-model review, consensus modeling, experiment design, statistical analysis, adversarial testing, and independent replication.

Funding, Foundation employment, infrastructure sponsorship, model-provider relationships, and protocol-development roles must be disclosed. Authorship should follow actual contributions using a recognized taxonomy such as CRediT [R20]. Negative findings, failed hypotheses, and design changes should be preserved in the public research record when disclosure does not create an immediate unmitigated security risk.

The first paper's intended contribution is a falsifiable architecture and evaluation of constrained AI-assisted validator governance. Its credibility will come from stating where the LLM is useful, where it has no authority, what evidence could disprove the design, and how the network remains safe when any one component fails.

## 14. Immediate next deliverables

1. Convert this charter into a pre-registered experiment matrix with datasets, attacks, metrics, owners, and thresholds.
2. Write the Phase 3 system and threat model, including trust domains and state-transition diagrams.
3. Specify the canonical signed evidence package and multi-observer aggregation protocol.
4. Specify hard eligibility and set-level safety constraints separately from the scoring prompt.
5. Define and implement the transparent formula and rules-only baselines.
6. Draft the next-state authorization certificate and model its safety and liveness properties.
7. Recruit independent observers and academic reviewers before collecting the final evaluation corpus.
8. Update `CurrentRoadmap.md` only after the research changes have been reviewed and accepted.

## References

[R0] Post Fiat, [Dynamic UNL Scoring - Current Roadmap](https://github.com/postfiatorg/dynamic-unl-scoring/blob/339c9dd724be55f11eea33338a6872400d3b9945/docs/CurrentRoadmap.md), repository snapshot 339c9dd.

[R1] Post Fiat, [Testnet round 15 convergence report](https://scoring-testnet.postfiat.org/api/scoring/rounds/15/convergence), sealed 2026-07-21.

[R2] Post Fiat, [Phase 2 Devnet Shadow Verification](https://github.com/postfiatorg/dynamic-unl-scoring/blob/339c9dd724be55f11eea33338a6872400d3b9945/docs/phase2/DevnetShadowVerification.md), repository snapshot 339c9dd.

[R3] Post Fiat, [Phase 0 deterministic scoring evidence](https://github.com/postfiatorg/dynamic-unl-scoring/blob/339c9dd724be55f11eea33338a6872400d3b9945/phase0/docs/README.md), repository snapshot 339c9dd.

[R4] Post Fiat, [Scoring Prompt V6 review](https://github.com/postfiatorg/dynamic-unl-scoring/blob/339c9dd724be55f11eea33338a6872400d3b9945/docs/ScoringPromptV6.md), repository snapshot 339c9dd.

[R5] Post Fiat, [Active scoring prompt V6](https://github.com/postfiatorg/dynamic-unl-scoring/blob/339c9dd724be55f11eea33338a6872400d3b9945/prompts/scoring_v6.txt), repository snapshot 339c9dd.

[R6] Post Fiat, [Phase 2 Commit-Reveal Protocol](https://github.com/postfiatorg/dynamic-unl-scoring/blob/339c9dd724be55f11eea33338a6872400d3b9945/docs/phase2/CommitRevealProtocol.md), repository snapshot 339c9dd.

[R7] Post Fiat, [M2.8.1 Go Record](https://github.com/postfiatorg/dynamic-unl-scoring/blob/339c9dd724be55f11eea33338a6872400d3b9945/docs/phase2/M2.8.1-GoRecord.md), repository snapshot 339c9dd.

[R8] Post Fiat, [Scoring Model Governance Methodology](https://github.com/postfiatorg/scoring-model-governance/blob/1eff9281be889869d91a88b1f8b159332ae9af10/docs/Methodology.md), repository snapshot 1eff928.

[R9] Post Fiat, [First Devnet Pool Refresh Record](https://github.com/postfiatorg/scoring-model-governance/blob/1eff9281be889869d91a88b1f8b159332ae9af10/records/pool-refreshes/devnet/2026-07-21-refresh-1.md), 2026-07-21.

[R10] Post Fiat, [Verifying Agreement Scores](https://github.com/postfiatorg/validator-history-service/blob/3a94ec57e6813cbe3556ecd5632fe68bdebd20f2/docs/VERIFYING_AGREEMENT_SCORES.md), repository snapshot 3a94ec5.

[R11] Post Fiat, [Nitro Enclave Trust Decision](https://github.com/postfiatorg/validator-history-service/blob/3a94ec57e6813cbe3556ecd5632fe68bdebd20f2/docs/NITRO_ENCLAVE_TRUST_DECISION.md), repository snapshot 3a94ec5.

[R12] Kai Greshake et al., [Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection](https://arxiv.org/abs/2302.12173), 2023.

[R13] Jingwei Yi et al., [Benchmarking and Defending Against Indirect Prompt Injection Attacks on Large Language Models](https://arxiv.org/abs/2312.14197), 2023.

[R14] Koki Wataoka, Tsubasa Takahashi, and Ryokan Ri, [Self-Preference Bias in LLM-as-a-Judge](https://arxiv.org/abs/2410.21819), 2024.

[R15] Jiayi Ye et al., [Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge](https://proceedings.iclr.cc/paper_files/paper/2025/file/fdca08d371e4b6c031397909e20043bd-Paper-Conference.pdf), ICLR 2025.

[R16] Ethan MacBrough, [Cobalt: BFT Governance in Open Networks](https://arxiv.org/abs/1802.07240), 2018.

[R17] XRP Ledger Foundation, [Unique Node Lists](https://xrpl.org/docs/concepts/consensus-protocol/unl), accessed 2026-07-22.

[R18] Apostol Vassilev et al., [Adversarial Machine Learning: A Taxonomy and Terminology of Attacks and Mitigations](https://doi.org/10.6028/NIST.AI.100-2e2025), NIST AI 100-2 E2025, 2025.

[R19] XRP Ledger Foundation, [Amendments](https://xrpl.org/docs/concepts/networks-and-servers/amendments), accessed 2026-07-22.

[R20] NISO, [CRediT Contributor Roles Taxonomy](https://credit.niso.org/), accessed 2026-07-22.
