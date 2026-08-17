"""Offline prompt-variant replay harness for the v9 and v10 scoring revisions.

Renders production-baseline, single-change, and combined-v9 model requests
from a completed round's frozen inputs, replays them against the pinned
inference runtime, and compares the outputs on the defect signatures the v9
revision targets (incumbent reliability bias, domain-status double counting,
diversity versus actual concentration).

The `v10` variant renders prompts/scoring_v10.txt, which adds the VHS
per-window `incomplete` data-quality flag to the rendered agreement
evidence. Pre-v10 frozen rounds were parsed without the flag, so the v10
render reconstructs the flags from the round's raw `vhs_validators.json`
(the untouched VHS response archived in the frozen input package); place
that file in the round dir alongside the frozen inputs. Injection
cross-checks every window's score/total/missed against the frozen evidence
and fails on any mismatch; rounds frozen under v10+ carry their flags in
the evidence itself and need no raw file.

Single-change templates are derived from prompts/scoring_v8.txt by exact
string edits: every edit asserts its anchor text occurs exactly once, so a
variant can never silently drift from "v8 plus one change".

Usage:
    python scripts/replay_prompt_variants.py write-variants
    python scripts/replay_prompt_variants.py run --round-dir DIR --variant baseline --out FILE [--dry-render]
    python scripts/replay_prompt_variants.py compare --round-dir DIR --baseline FILE --outputs FILE...

A round dir holds the round's frozen `validator_evidence.json` and
`model_request.json` (from the scoring API's `/input/` fallback routes),
plus `vhs_validators.json` when replaying the v10 variant.

A compare baseline is a `run` output, or a production response wrapped into
the same shape: `variant`, `round`, `content` (the round's published
`outputs/model_response.json` raw_response), and `validator_id_map`
(validator_id to master_key, from the round's `inputs/validator_map.json`).
"""

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
for path in (SCRIPT_DIR, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from query import create_client  # noqa: E402

from scoring_service.config import settings  # noqa: E402
from scoring_service.models import ScoringSnapshot  # noqa: E402
from scoring_service.services.prompt_builder import (  # noqa: E402
    PROVIDER_FAMILY_FIELD,
    PromptBuilder,
)
from scoring_service.services.provider_families import (  # noqa: E402
    UNKNOWN_FAMILY,
    family_for,
)
from scoring_service.services.score_formula import compute_final_score  # noqa: E402

V8_TEMPLATE = REPO_ROOT / "prompts" / "scoring_v8.txt"
V9_TEMPLATE = REPO_ROOT / "prompts" / "scoring_v9.txt"
V10_TEMPLATE = REPO_ROOT / "prompts" / "scoring_v10.txt"
AGREEMENT_WINDOW_FIELDS = ("agreement_1h", "agreement_24h", "agreement_30d")
RAW_VHS_WINDOW_FIELDS = (
    ("agreement_1h", "agreement_1h"),
    ("agreement_24h", "agreement_24h"),
    ("agreement_30d", "agreement_30day"),
)
VARIANTS_DIR = SCRIPT_DIR / "prompt_variants"
REQUEST_PASSTHROUGH_KEYS = ("model", "extra_body", "max_tokens", "temperature", "response_format")
DEFAULT_TIMEOUT_SECONDS = 900

V8_RELIABILITY_BLOCK = """2. OPERATIONAL RELIABILITY (high weight) -> sub-score field: "reliability"
   - Domain verification: a verified domain shows the operator has invested in proper configuration and public accountability.
   - Current UNL membership is useful context for continuity, but it is not proof of intrinsic reliability by itself. Do not materially downgrade a non-UNL validator solely because it is not an incumbent if its agreement, software, domain, and diversity evidence are strong.
   - Do not award a high reliability score solely because a validator is currently on the UNL. The final UNL selector applies separate churn control after scoring."""

V9_RELIABILITY_OPERATIONAL = """2. OPERATIONAL RELIABILITY (high weight) -> sub-score field: "reliability"
   - Reliability measures demonstrated operational stability: sustained participation, low missed-ledger tails, and the absence of recent outages or instability across the agreement windows.
   - Judge reliability from operational evidence only: the agreement windows, missed-ledger counts, and stability patterns over time (steady performance versus outage-and-recovery churn). Consensus scores the agreement numbers themselves; reliability scores the stability story they tell over time.
   - Domain and identity evidence is accountability, not operation. It belongs to the identity dimension only and must not raise or lower the reliability sub-score.
   - Validators whose operational evidence is identical must receive identical reliability sub-scores regardless of any other field in their profiles."""

V8_MEMBERSHIP_GUARDRAILS = """   - Current UNL membership is useful context for continuity, but it is not proof of intrinsic reliability by itself. Do not materially downgrade a non-UNL validator solely because it is not an incumbent if its agreement, software, domain, and diversity evidence are strong.
   - Do not award a high reliability score solely because a validator is currently on the UNL. The final UNL selector applies separate churn control after scoring."""

V8_PENALTY_DOMAIN = "- domain: null or domain_verified: false - no public accountability. Lower the identity sub-score and, where appropriate, the reliability sub-score."
V9_PENALTY_DOMAIN = "- domain: null or domain_verified: false - no public accountability. Lower the identity sub-score only; accountability evidence must not affect the reliability sub-score."

V8_SHORTCUT_RULE = "- Current UNL membership should not become a scoring shortcut. It can explain continuity, but it should not override current evidence.\n"

V8_REPORT_MEMBERSHIP = " Use current UNL membership only as close-case continuity context, not as proof of validator quality."

V8_DATA_DESCRIPTION = "Each validator entry includes a `validator_id` (anonymous identifier) and all scoring-relevant data: agreement scores across three time windows (1h, 24h, 30d), domain and verification status, server version, UNL membership, fee votes, ASN/ISP information, country, and identity status."

V8_REASONING_EVIDENCE = "Reference concrete evidence when relevant: agreement windows, domain verification, software version, country, ASN/provider, UNL context, or missing fields."

V8_EXAMPLE_RELIABILITY_BODY = '"body": "Reliability is strongest in the selected group where high agreement is supported by verified domains and stable operational signals. Current UNL membership provides useful continuity context near the selection boundary, but current evidence still drives the score."'

V8_DIVERSITY_BLOCK = """   - Country concentration: if many validators are in the same country, additional validators in that country contribute less diversity. Validators in underrepresented countries score higher on this dimension.
   - ASN / ISP concentration: if many validators share the same ISP or cloud provider (e.g., multiple validators on "Vultr Holdings" or "Hetzner Online"), additional validators on that provider contribute less infrastructure diversity.
   - Country diversity and ASN diversity are separate. A validator in an underrepresented country still helps geographic spread, but if it shares the same ASN/provider as the rest of the set, the diversity bonus should be moderate rather than high.
   - A validator with resolved public endpoint evidence should receive more diversity confidence than one with no endpoint evidence, all else equal. Treat this as a modest transparency signal, not definitive proof of infrastructure origin.
   - Use the provided country and ASN fields to assess observable endpoint concentration across the full validator set.
   - Order diversity sub-scores by concentration. A validator no more concentrated than another on either axis (country or ASN) and strictly less concentrated on at least one (for example, the only validator in its country on a provider no other validator uses, versus a validator in an equally unique country on a provider shared with several peers) must receive a strictly higher diversity sub-score. Validators in equivalent concentration situations - the same number of set peers sharing their country and their ASN - must receive identical diversity sub-scores."""

V9_DIVERSITY_BLOCK = """   - The user prompt supplies a NETWORK CONCENTRATION block with precomputed counts: how many validators in the set belong to each provider family and each country. Provider families group corporate variants of the same operator (for example, a provider's dedicated and cloud ASNs count as one family). Each validator's provider_family field names its family in that block.
   - Score diversity from the supplied concentration counts. Do not count provider or country representation across the validator entries yourself, and do not judge concentration from raw ASN name strings.
   - Country concentration: the more validators the concentration block counts in a country, the less marginal diversity an additional validator in that country contributes. Validators in underrepresented countries score higher on this dimension.
   - Provider concentration: the more validators the concentration block counts in a provider family, the less infrastructure diversity an additional member of that family contributes.
   - Country diversity and provider diversity are separate. A validator in an underrepresented country still helps geographic spread, but if it belongs to a dominant provider family, the diversity bonus should be moderate rather than high.
   - A validator with resolved public endpoint evidence should receive more diversity confidence than one with no endpoint evidence, all else equal. Treat this as a modest transparency signal, not definitive proof of infrastructure origin.
   - Order diversity sub-scores by the supplied counts. A validator no more concentrated than another on either axis (country count or provider-family count) and strictly less concentrated on at least one must receive a strictly higher diversity sub-score. Validators in equivalent concentration situations - the same country count and the same provider-family count - must receive identical diversity sub-scores."""

CONCENTRATION_SECTION = "NETWORK CONCENTRATION:\n{network_concentration}\n\nVALIDATOR DATA:"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"variant edit '{label}' matched {count} times, expected exactly 1")
    return text.replace(old, new)


def build_no_unl_template(v8: str) -> str:
    text = _replace_once(v8, V8_MEMBERSHIP_GUARDRAILS + "\n", "", "reliability membership guardrails")
    text = _replace_once(text, V8_SHORTCUT_RULE, "", "scoring shortcut rule")
    text = _replace_once(text, V8_REPORT_MEMBERSHIP, "", "report membership context")
    text = _replace_once(
        text,
        ", server version, UNL membership, fee votes,",
        ", server version, fee votes,",
        "data description membership",
    )
    text = _replace_once(
        text,
        "country, ASN/provider, UNL context, or missing fields",
        "country, ASN/provider, or missing fields",
        "reasoning evidence membership",
    )
    text = _replace_once(
        text,
        V8_EXAMPLE_RELIABILITY_BODY,
        '"body": "Reliability is strongest in the selected group where high agreement is supported by verified domains and stable operational signals. Current evidence drives the score."',
        "example reliability membership",
    )
    return text


def build_reliability_template(v8: str) -> str:
    text = _replace_once(
        v8,
        V8_RELIABILITY_BLOCK,
        V9_RELIABILITY_OPERATIONAL + "\n" + V8_MEMBERSHIP_GUARDRAILS,
        "reliability block",
    )
    text = _replace_once(text, V8_PENALTY_DOMAIN, V9_PENALTY_DOMAIN, "penalty domain line")
    text = _replace_once(
        text,
        V8_EXAMPLE_RELIABILITY_BODY,
        '"body": "Reliability is strongest in the selected group where sustained agreement shows no outage tail across the 1-hour, 24-hour, and 30-day windows. Current UNL membership provides useful continuity context near the selection boundary, but current evidence still drives the score."',
        "example reliability body",
    )
    return text


def build_concentration_template(v8: str) -> str:
    text = _replace_once(v8, V8_DIVERSITY_BLOCK, V9_DIVERSITY_BLOCK, "diversity block")
    text = _replace_once(
        text,
        V8_DATA_DESCRIPTION,
        V8_DATA_DESCRIPTION.replace(
            "fee votes, ASN/ISP information, country",
            "fee votes, ASN/ISP information, a `provider_family` field naming the validator's provider family in the concentration block, country",
        )
        + "\n\nThe NETWORK CONCENTRATION block below the selector context carries precomputed counts of validators per provider family and per country across the full candidate set. Use it as the sole source of concentration evidence for the diversity dimension.",
        "data description concentration",
    )
    text = _replace_once(
        text,
        "country, ASN/provider, UNL context, or missing fields",
        "country, provider family, concentration counts, UNL context, or missing fields",
        "reasoning evidence concentration",
    )
    text = _replace_once(text, "VALIDATOR DATA:", CONCENTRATION_SECTION, "concentration section")
    return text


VARIANT_BUILDERS = {
    "scoring_v8_no_unl.txt": build_no_unl_template,
    "scoring_v8_reliability.txt": build_reliability_template,
    "scoring_v8_concentration.txt": build_concentration_template,
}

VARIANTS = {
    "baseline": {"template": V8_TEMPLATE, "hidden_fields": set()},
    "no-unl": {"template": VARIANTS_DIR / "scoring_v8_no_unl.txt", "hidden_fields": {"unl"}},
    "reliability": {"template": VARIANTS_DIR / "scoring_v8_reliability.txt", "hidden_fields": set()},
    "concentration": {"template": VARIANTS_DIR / "scoring_v8_concentration.txt", "hidden_fields": set()},
    "combined": {"template": V9_TEMPLATE, "hidden_fields": {"unl"}},
    "v10": {"template": V10_TEMPLATE, "hidden_fields": {"unl"}, "inject_flags": True},
}


def write_variants() -> None:
    VARIANTS_DIR.mkdir(exist_ok=True)
    v8 = V8_TEMPLATE.read_text()
    for filename, builder in VARIANT_BUILDERS.items():
        path = VARIANTS_DIR / filename
        path.write_text(builder(v8))
        print(f"wrote {path.relative_to(REPO_ROOT)}")


def _load_round(round_dir: Path) -> tuple[ScoringSnapshot, dict]:
    evidence = json.loads((round_dir / "validator_evidence.json").read_text())
    frozen = json.loads((round_dir / "model_request.json").read_text())
    return ScoringSnapshot.model_validate(evidence), frozen


def _without_agreement_flags(entry: dict) -> dict:
    """Drop builder-added incomplete flags for comparison against pre-v10 rounds."""
    cleaned = dict(entry)
    for window in AGREEMENT_WINDOW_FIELDS:
        value = cleaned.get(window)
        if isinstance(value, dict) and "incomplete" in value:
            trimmed = dict(value)
            trimmed.pop("incomplete")
            cleaned[window] = trimmed
    return cleaned


def _raw_vhs_by_master(round_dir: Path) -> dict[str, dict]:
    """Index the round's raw VHS validators response by master key."""
    raw_path = round_dir / "vhs_validators.json"
    if not raw_path.exists():
        return {}
    raw = json.loads(raw_path.read_text())
    validators = raw.get("validators", raw) if isinstance(raw, dict) else raw
    if isinstance(validators, dict):
        validators = list(validators.values())
    by_master: dict[str, dict] = {}
    for entry in validators:
        key = entry.get("master_key") or entry.get("validation_public_key")
        if key:
            by_master[key] = entry
    return by_master


def _snapshot_has_flags(snapshot: ScoringSnapshot) -> bool:
    """True when the frozen evidence itself carries incomplete flags (v10+ rounds)."""
    return any(
        getattr(validator, attr).incomplete is not None
        for validator in snapshot.validators
        for attr, _raw_field in RAW_VHS_WINDOW_FIELDS
    )


def _inject_incomplete_flags(snapshot: ScoringSnapshot, round_dir: Path) -> bool:
    """Set per-window incomplete flags from the round's raw VHS evidence.

    Pre-v10 frozen validator evidence was parsed without the flag, so a v10
    render reconstructs it from the untouched VHS response archived with the
    round. Every snapshot validator must appear in the raw file and every
    window's score/total/missed must match the frozen evidence exactly —
    otherwise the raw file is not this round's archive and injection fails
    loudly rather than rendering wrong or null flags. Returns False when the
    round dir has no raw VHS file.
    """
    by_master = _raw_vhs_by_master(round_dir)
    if not by_master:
        return False
    for validator in snapshot.validators:
        raw_entry = by_master.get(validator.master_key)
        if raw_entry is None:
            raise ValueError(
                f"raw vhs_validators.json has no entry for {validator.master_key[:16]}...; "
                "is it this round's archive?"
            )
        for attr, raw_field in RAW_VHS_WINDOW_FIELDS:
            window = getattr(validator, attr)
            raw_window = raw_entry.get(raw_field)
            if not isinstance(raw_window, dict):
                if (window.score, window.total, window.missed) != (None, None, None):
                    raise ValueError(
                        f"raw vhs_validators.json lacks the {attr} window for "
                        f"{validator.master_key[:16]}... that the frozen evidence has; "
                        "is it this round's archive?"
                    )
                continue
            raw_score = raw_window.get("score")
            expected = (
                float(raw_score) if raw_score is not None else None,
                raw_window.get("total"),
                raw_window.get("missed"),
            )
            if (window.score, window.total, window.missed) != expected:
                raise ValueError(
                    f"raw vhs_validators.json disagrees with the frozen evidence for "
                    f"{validator.master_key[:16]}... {attr}; is it this round's archive?"
                )
            window.incomplete = raw_window.get("incomplete")
    return True


def _strip_flags_from_user_content(content: str) -> str:
    """Remove builder-added incomplete flags from a rendered user message.

    Adapts the baseline byte-for-byte gate to pre-v10 frozen rounds: the
    builder now always renders the flag keys, which a request frozen before
    v10 cannot contain.
    """
    data = content.split("VALIDATOR DATA:")[1].strip()
    entries_str = data.split("\n\nRespond with ONLY")[0]
    stripped = json.dumps(
        [_without_agreement_flags(entry) for entry in json.loads(entries_str)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return content.replace(entries_str, stripped, 1)


def _apply_selector_context(frozen: dict) -> None:
    """Pin selector-context placeholders to the frozen round's values."""
    user_content = frozen["messages"][1]["content"]
    for pattern, attr in (
        (r"Maximum selected UNL validators: (\d+)", "unl_max_size"),
        (r"Minimum score cutoff for UNL eligibility: (\d+)", "unl_score_cutoff"),
        (r"Churn-control score gap for replacing close-scoring incumbents: (\d+)", "unl_min_score_gap"),
    ):
        match = re.search(pattern, user_content)
        if not match:
            raise ValueError(f"frozen request lacks selector context for {attr}")
        setattr(settings, attr, int(match.group(1)))


def _validator_entries(user_content: str) -> list[dict]:
    data = user_content.split("VALIDATOR DATA:")[1].strip()
    return json.loads(data.split("\n\nRespond with ONLY")[0])


def render_variant(round_dir: Path, variant: str) -> tuple[list, dict, dict]:
    snapshot, frozen = _load_round(round_dir)
    _apply_selector_context(frozen)
    spec = VARIANTS[variant]
    if spec.get("inject_flags") and not _snapshot_has_flags(snapshot):
        if not _inject_incomplete_flags(snapshot, round_dir):
            raise ValueError(
                f"variant '{variant}' reconstructs incomplete flags from raw VHS "
                "evidence; add vhs_validators.json to the round dir instead of "
                "silently rendering null flags"
            )
    builder = PromptBuilder(
        prompt_path=spec["template"], hidden_fields=spec["hidden_fields"]
    )
    messages, id_map = builder.build(snapshot)
    messages = [dict(message) for message in messages]

    frozen_raw = _validator_entries(frozen["messages"][1]["content"])
    frozen_has_flags = any(
        isinstance(entry.get(window), dict) and "incomplete" in entry[window]
        for entry in frozen_raw
        for window in AGREEMENT_WINDOW_FIELDS
    )

    if variant == "baseline":
        # The builder always renders the v10 flag keys, which a request
        # frozen before v10 cannot contain; the byte-for-byte gate therefore
        # compares modulo exactly those builder-added keys on such rounds.
        baseline_messages = messages
        if not frozen_has_flags:
            baseline_messages = [dict(message) for message in messages]
            baseline_messages[1]["content"] = _strip_flags_from_user_content(
                baseline_messages[1]["content"]
            )
        if baseline_messages != frozen["messages"]:
            for index, (rebuilt, original) in enumerate(
                zip(baseline_messages, frozen["messages"])
            ):
                if rebuilt != original:
                    raise ValueError(
                        f"baseline rebuild diverges from the frozen request in message {index}; "
                        "the snapshot-to-request reconstruction is not faithful for this round"
                    )
            raise ValueError("baseline rebuild diverges from the frozen request in message count")

    # Every variant must carry the frozen round's validator data verbatim,
    # modulo exactly the fields this variant deliberately hides or adds — a
    # variant configured to keep `unl` therefore has its `unl` values
    # checked too, preserving the "v8 plus one change" isolation. Rounds
    # frozen under an older template can't match at the full-message level
    # but data fidelity still must. When the frozen round itself carries the
    # builder-added provider_family field (frozen under v9), those family
    # assignments are compared too, so normalization drift cannot silently
    # replay a different request than the frozen one. Replaying a v8-style
    # variant against a v9-frozen round is unsupported: the gate would fail
    # on the deliberately absent `unl` field.
    frozen_has_family = any(PROVIDER_FAMILY_FIELD in entry for entry in frozen_raw)
    rebuilt_strip = set() if frozen_has_family else {PROVIDER_FAMILY_FIELD}
    frozen_entries = [
        {k: v for k, v in entry.items() if k not in spec["hidden_fields"]}
        for entry in frozen_raw
    ]
    rebuilt_entries = [
        {k: v for k, v in entry.items() if k not in rebuilt_strip}
        for entry in _validator_entries(messages[1]["content"])
    ]
    # Agreement windows gained the builder-added incomplete flag in v10; a
    # round frozen before that cannot carry it, so drop the flag from the
    # rebuilt entries for comparison — mirroring the provider_family
    # handling above. Rounds frozen under v10 keep their flags compared.
    if not frozen_has_flags:
        rebuilt_entries = [_without_agreement_flags(entry) for entry in rebuilt_entries]
    if frozen_entries != rebuilt_entries:
        raise ValueError(
            f"variant '{variant}' validator data diverges from the frozen round; "
            "refusing to replay unfaithful evidence"
        )

    frozen_user = frozen["messages"][1]["content"]
    if "NETWORK CONCENTRATION:" in frozen_user:
        frozen_block = frozen_user.split("NETWORK CONCENTRATION:")[1].split("VALIDATOR DATA:")[0]
        rebuilt_block = messages[1]["content"].split("NETWORK CONCENTRATION:")[1].split("VALIDATOR DATA:")[0]
        if frozen_block != rebuilt_block:
            raise ValueError(
                f"variant '{variant}' concentration block diverges from the frozen round"
            )

    return messages, id_map, frozen


def run_variant(round_dir: Path, variant: str, out_path: Path, timeout: float, dry_render: bool) -> None:
    messages, id_map, frozen = render_variant(round_dir, variant)
    request = {key: frozen[key] for key in REQUEST_PASSTHROUGH_KEYS if key in frozen}
    request["messages"] = messages

    if dry_render:
        out_path.write_text(json.dumps({"variant": variant, "request": request}, indent=1))
        print(f"rendered {variant} -> {out_path} (no inference call)")
        return

    endpoint = settings.modal_endpoint_url.rstrip("/")
    if not endpoint.endswith("/v1"):
        endpoint = f"{endpoint}/v1"
    client = create_client(endpoint, timeout=timeout)

    print(f"calling {variant} against {request['model']} (timeout {timeout:.0f}s)...")
    start = time.time()
    response = client.chat.completions.create(**request)
    duration = time.time() - start
    content = response.choices[0].message.content

    result = {
        "variant": variant,
        "round": round_dir.name,
        "duration_seconds": round(duration, 1),
        "model": request["model"],
        "usage": response.usage.model_dump() if response.usage else None,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "validator_id_map": {vid: keys["master_key"] for vid, keys in id_map.items()},
        "content": content,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1))
    print(f"{variant}: {duration:.1f}s, content sha256 {result['content_sha256'][:16]}..., saved {out_path}")


def _scores_by_master_key(output_path: Path) -> dict[str, dict]:
    data = json.loads(output_path.read_text())
    parsed = json.loads(data["content"])
    id_map = data["validator_id_map"]
    return {
        id_map[vid]: entry
        for vid, entry in parsed.items()
        if vid != "network_report" and vid in id_map
    }


def compare(round_dir: Path, baseline_path: Path, output_paths: list[Path]) -> None:
    evidence = json.loads((round_dir / "validator_evidence.json").read_text())
    profiles = {v["master_key"]: v for v in evidence["validators"]}
    baseline = _scores_by_master_key(baseline_path)

    for output_path in output_paths:
        scores = _scores_by_master_key(output_path)
        variant = json.loads(output_path.read_text())["variant"]
        print(f"\n=== {variant} ({output_path.name}) vs baseline ===")

        ceiling_violations = []
        band_violations = []
        for mk, s in scores.items():
            windows = [
                profiles[mk][w]["score"]
                for w in ("agreement_1h", "agreement_24h", "agreement_30d")
                if profiles[mk][w]["score"] is not None
            ]
            # Integer ceiling with a deliberate one-point tolerance at the
            # top: validated rolls resolve a fractional 99.9x worst window
            # either way (100 on the testnet rolls, 99 on the devnet
            # regression roll), and both are harmless, while degraded
            # validators hold the ceiling exactly in every roll. Rounding
            # the bound up also sidesteps float lowball artifacts.
            if windows and s["consensus"] > math.ceil(min(windows) * 100):
                ceiling_violations.append(mk[:10])
            if any(s[dim] % 5 for dim in ("reliability", "software", "diversity", "identity")):
                band_violations.append(mk[:10])
        print(
            f"consensus ceiling violations (sub-score above worst window): "
            f"{len(ceiling_violations)} {ceiling_violations[:5]}"
        )
        print(
            f"band violations (rel/soft/div/ident not multiples of 5): "
            f"{len(band_violations)} {band_violations[:5]}"
        )

        healthy = [
            mk
            for mk, s in scores.items()
            if s["consensus"] >= 99
            and profiles[mk].get("domain_verified")
            and (profiles[mk]["agreement_30d"]["score"] or 0) >= 0.999
        ]
        incumbents = [scores[mk]["reliability"] for mk in healthy if profiles[mk].get("unl")]
        challengers = [scores[mk]["reliability"] for mk in healthy if not profiles[mk].get("unl")]
        if incumbents and challengers:
            print(
                f"incumbent-bias signature (healthy verified set): "
                f"incumbents rel mean {statistics.mean(incumbents):.1f} (n={len(incumbents)}), "
                f"challengers rel mean {statistics.mean(challengers):.1f} (n={len(challengers)})"
            )

        perfect = [
            mk
            for mk, s in scores.items()
            if s["consensus"] >= 99 and (profiles[mk]["agreement_30d"]["score"] or 0) >= 0.999
        ]
        verified = [scores[mk]["reliability"] for mk in perfect if profiles[mk].get("domain_verified")]
        no_domain = [
            scores[mk]["reliability"]
            for mk in perfect
            if not profiles[mk].get("domain") and profiles[mk].get("domain_verified") is None
        ]
        if verified and no_domain:
            print(
                f"domain-coupling signature (perfect-agreement set): "
                f"verified rel mean {statistics.mean(verified):.1f} (n={len(verified)}), "
                f"no-domain rel mean {statistics.mean(no_domain):.1f} (n={len(no_domain)})"
            )

        family_counts: dict[str, int] = {}
        country_counts: dict[str, int] = {}
        for profile in profiles.values():
            family = family_for((profile.get("asn") or {}).get("as_name"))
            if family != UNKNOWN_FAMILY:
                family_counts[family] = family_counts.get(family, 0) + 1
            country = (profile.get("geolocation") or {}).get("country")
            if country:
                country_counts[country] = country_counts.get(country, 0) + 1

        violations = 0
        comparable = 0
        keys = [mk for mk in scores if (profiles[mk].get("asn") or {}).get("as_name")]
        for a in keys:
            for b in keys:
                fa = family_counts[family_for(profiles[a]["asn"]["as_name"])]
                fb = family_counts[family_for(profiles[b]["asn"]["as_name"])]
                ca = country_counts.get((profiles[a].get("geolocation") or {}).get("country"), 0)
                cb = country_counts.get((profiles[b].get("geolocation") or {}).get("country"), 0)
                if fa <= fb and ca <= cb and (fa < fb or ca < cb):
                    comparable += 1
                    if scores[a]["diversity"] <= scores[b]["diversity"]:
                        violations += 1
        print(
            f"diversity ordering: {violations}/{comparable} strictly-less-concentrated "
            f"pairs not scored strictly higher"
        )

        deltas = {dim: [] for dim in ("consensus", "software", "identity")}
        for mk, s in scores.items():
            if mk in baseline:
                for dim in deltas:
                    deltas[dim].append(abs(s[dim] - baseline[mk][dim]))
        drift = ", ".join(
            f"{dim} mean |delta| {statistics.mean(values):.2f}" for dim, values in deltas.items() if values
        )
        print(f"untouched-dimension drift vs baseline: {drift}")

        flags_by_master = _raw_vhs_by_master(round_dir)
        if flags_by_master:

            def _has_true_flag(mk: str) -> bool:
                entry = flags_by_master.get(mk, {})
                return any(
                    isinstance(entry.get(raw_field), dict)
                    and entry[raw_field].get("incomplete")
                    for _attr, raw_field in RAW_VHS_WINDOW_FIELDS
                )

            all_dims = ("consensus", "reliability", "software", "diversity", "identity")
            for label, group in (
                ("unflagged", [mk for mk in scores if mk in baseline and not _has_true_flag(mk)]),
                ("flagged", [mk for mk in scores if mk in baseline and _has_true_flag(mk)]),
            ):
                if not group:
                    print(f"{label} validators vs baseline: none")
                    continue
                dim_drift = ", ".join(
                    f"{dim} {statistics.mean(abs(scores[mk][dim] - baseline[mk][dim]) for mk in group):.2f}"
                    for dim in all_dims
                )
                print(f"{label} validators (n={len(group)}) mean |delta| vs baseline: {dim_drift}")

        finals = {
            mk: compute_final_score(
                consensus=s["consensus"],
                reliability=s["reliability"],
                software=s["software"],
                diversity=s["diversity"],
                identity=s["identity"],
            )
            for mk, s in scores.items()
        }
        moved = sum(
            1
            for mk in finals
            if mk in baseline
            and finals[mk]
            != compute_final_score(
                consensus=baseline[mk]["consensus"],
                reliability=baseline[mk]["reliability"],
                software=baseline[mk]["software"],
                diversity=baseline[mk]["diversity"],
                identity=baseline[mk]["identity"],
            )
        )
        print(f"final scores moved vs baseline: {moved}/{len(finals)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("write-variants")

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--round-dir", type=Path, required=True)
    run_parser.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    run_parser.add_argument("--dry-render", action="store_true")

    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("--round-dir", type=Path, required=True)
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--outputs", type=Path, nargs="+", required=True)

    args = parser.parse_args()
    if args.command == "write-variants":
        write_variants()
    elif args.command == "run":
        run_variant(args.round_dir, args.variant, args.out, args.timeout, args.dry_render)
    elif args.command == "compare":
        compare(args.round_dir, args.baseline, args.outputs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
