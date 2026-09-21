"""Tests for the prompt-variant replay harness template derivation."""

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest  # noqa: E402

from replay_prompt_variants import (  # noqa: E402
    V8_TEMPLATE,
    V9_TEMPLATE,
    V10_TEMPLATE,
    V11_TEMPLATE,
    VARIANT_BUILDERS,
    VARIANTS,
    VARIANTS_DIR,
    _inject_incomplete_flags,
    _master_keys_failing_minimum,
    _snapshot_has_flags,
    _strip_flags_from_user_content,
    _strip_verdict_from_user_content,
    _validator_entries,
    _without_agreement_flags,
    render_variant,
    build_concentration_template,
    build_no_unl_template,
    build_reliability_template,
)

from scoring_service.models import (  # noqa: E402
    AgreementScore,
    ScoringSnapshot,
    ValidatorProfile,
)
from scoring_service.services.prompt_builder import PromptBuilder  # noqa: E402


def _v8() -> str:
    return V8_TEMPLATE.read_text()


class TestCommittedVariantFiles:
    def test_committed_templates_match_their_builders(self):
        v8 = _v8()
        for filename, builder in VARIANT_BUILDERS.items():
            committed = (VARIANTS_DIR / filename).read_text()
            assert committed == builder(v8), (
                f"{filename} drifted from its builder; regenerate with "
                "`python scripts/replay_prompt_variants.py write-variants`"
            )


class TestNoUnlVariant:
    def test_removes_every_membership_reference(self):
        text = build_no_unl_template(_v8())
        assert "UNL membership" not in text
        assert "currently on the UNL" not in text

    def test_keeps_v8_reliability_semantics(self):
        text = build_no_unl_template(_v8())
        assert "Domain verification: a verified domain shows the operator" in text
        assert "Judge reliability from operational evidence only" not in text


class TestReliabilityVariant:
    def test_redefines_reliability_and_keeps_membership_guardrails(self):
        text = build_reliability_template(_v8())
        assert "Judge reliability from operational evidence only" in text
        assert "must not raise or lower the reliability sub-score" in text
        assert "Current UNL membership is useful context for continuity" in text

    def test_penalty_policy_no_longer_touches_reliability(self):
        text = build_reliability_template(_v8())
        assert "where appropriate, the reliability sub-score" not in text
        assert "Lower the identity sub-score only" in text


class TestConcentrationVariant:
    def test_adds_concentration_section_and_keeps_membership(self):
        text = build_concentration_template(_v8())
        assert "NETWORK CONCENTRATION:\n{network_concentration}" in text
        assert "provider_family" in text
        assert "UNL membership" in text

    def test_diversity_scores_from_supplied_counts(self):
        text = build_concentration_template(_v8())
        assert "Score diversity from the supplied concentration counts" in text
        assert "Order diversity sub-scores by the supplied counts" in text
        assert "Order diversity sub-scores by concentration." not in text


V10_FLAG_BLOCK = """AGREEMENT DATA QUALITY FLAGS:
   - Each agreement window carries an `incomplete` boolean flag from the measurement service. When true, the service's own observation of that window was partial: its recorded ledger stream had gaps, the window was measured right after a service restart, or an aggregation window is missing too many hourly measurements (typical for newly tracked validators).
   - The flag describes the measurement, never the validator. Ledgers the service did not observe are already excluded from `total` and `missed`, so a flagged window's numbers are not inflated against the validator.
   - The flag is one-directional. `incomplete: true` lowers confidence that the window represents the validator's full record - especially when the window's `total` is small - but the evidence recorded in the window still counts fully: never use a true flag to excuse degraded agreement evidence that is present in the window, and never penalize a validator merely because a window is flagged. `incomplete: false` or null carries no extra endorsement and never raises a sub-score.

"""

V9_DATA_DESCRIPTION = (
    "agreement scores across three time windows (1h, 24h, 30d), "
    "domain and verification status"
)
V10_DATA_DESCRIPTION = (
    "agreement scores across three time windows (1h, 24h, 30d) each carrying "
    "the measurement service's `incomplete` data-quality flag, "
    "domain and verification status"
)

V9_KEY_RULE = (
    "Do not invent IDs and do not use any public keys as output keys."
)
V10_KEY_RULE = (
    "Do not invent IDs and do not use any public keys as output keys. "
    "Before writing each entry, restate its exact validator_id from the "
    "input as the key; never emit an empty, whitespace, or quote-character key."
)


class TestV10Template:
    def test_v10_is_v9_plus_exactly_the_flag_revision(self):
        v9 = V9_TEMPLATE.read_text()
        v10 = V10_TEMPLATE.read_text()
        assert v10.count(V10_FLAG_BLOCK) == 1
        assert V10_FLAG_BLOCK not in v9
        assert v10.count(V10_DATA_DESCRIPTION) == 1
        assert v10.count(V10_KEY_RULE) == 1
        reverted = (
            v10.replace(V10_FLAG_BLOCK, "", 1)
            .replace(V10_DATA_DESCRIPTION, V9_DATA_DESCRIPTION, 1)
            .replace(V10_KEY_RULE, V9_KEY_RULE, 1)
        )
        assert reverted == v9, (
            "scoring_v10.txt drifted from 'v9 plus the flag revision'; "
            "update the anchors here if the drift is intentional"
        )

    def test_v10_variant_registered_with_flag_injection(self):
        spec = VARIANTS["v10"]
        assert spec["template"] == V10_TEMPLATE
        assert spec["hidden_fields"] == {"unl"}
        assert spec["inject_flags"] is True
        assert not any(
            variant.get("inject_flags")
            for name, variant in VARIANTS.items()
            if name not in {"v10", "v11"}
        )


def _snapshot_for_injection() -> ScoringSnapshot:
    return ScoringSnapshot(
        round_number=1,
        network="testnet",
        snapshot_timestamp="2026-08-07T00:00:00Z",
        validators=[
            ValidatorProfile(
                master_key="nHBv1",
                signing_key="n9s1",
                agreement_1h=AgreementScore(score=1.0, total=900, missed=0),
                agreement_24h=AgreementScore(score=1.0, total=21000, missed=0),
                agreement_30d=AgreementScore(score=1.0, total=630000, missed=0),
            )
        ],
    )


class TestFlagInjection:
    def test_injects_flags_by_master_key(self, tmp_path):
        (tmp_path / "vhs_validators.json").write_text(
            json.dumps(
                {
                    "validators": [
                        {
                            "master_key": "nHBv1",
                            "agreement_1h": {"missed": 0, "total": 900, "score": "1.00000", "incomplete": False},
                            "agreement_24h": {"missed": 0, "total": 21000, "score": "1.00000", "incomplete": True},
                            "agreement_30day": {"missed": 0, "total": 630000, "score": "1.00000", "incomplete": True},
                        }
                    ]
                }
            )
        )
        snapshot = _snapshot_for_injection()
        assert _inject_incomplete_flags(snapshot, tmp_path) is True
        validator = snapshot.validators[0]
        assert validator.agreement_1h.incomplete is False
        assert validator.agreement_24h.incomplete is True
        assert validator.agreement_30d.incomplete is True

    def test_returns_false_without_raw_file(self, tmp_path):
        snapshot = _snapshot_for_injection()
        assert _inject_incomplete_flags(snapshot, tmp_path) is False
        assert snapshot.validators[0].agreement_1h.incomplete is None

    def test_rejects_raw_file_missing_a_snapshot_validator(self, tmp_path):
        (tmp_path / "vhs_validators.json").write_text(
            json.dumps({"validators": [{"master_key": "nHBother"}]})
        )
        with pytest.raises(ValueError, match="no entry for"):
            _inject_incomplete_flags(_snapshot_for_injection(), tmp_path)

    def test_rejects_raw_windows_disagreeing_with_frozen_evidence(self, tmp_path):
        (tmp_path / "vhs_validators.json").write_text(
            json.dumps(
                {
                    "validators": [
                        {
                            "master_key": "nHBv1",
                            "agreement_1h": {"missed": 7, "total": 900, "score": "0.99222", "incomplete": False},
                            "agreement_24h": {"missed": 0, "total": 21000, "score": "1.00000", "incomplete": False},
                            "agreement_30day": {"missed": 0, "total": 630000, "score": "1.00000", "incomplete": False},
                        }
                    ]
                }
            )
        )
        with pytest.raises(ValueError, match="disagrees with the frozen evidence"):
            _inject_incomplete_flags(_snapshot_for_injection(), tmp_path)

    def test_snapshot_with_own_flags_needs_no_injection(self):
        snapshot = _snapshot_for_injection()
        assert _snapshot_has_flags(snapshot) is False
        snapshot.validators[0].agreement_24h.incomplete = False
        assert _snapshot_has_flags(snapshot) is True

    def test_strips_flags_from_rendered_user_content(self):
        entries = [
            {
                "validator_id": "v001",
                "agreement_1h": {"score": 1.0, "total": 900, "missed": 0, "incomplete": False},
            }
        ]
        content = (
            "SELECTOR CONTEXT:\n\nVALIDATOR DATA:\n"
            + json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
            + "\n\nRespond with ONLY a valid JSON object."
        )
        stripped = _strip_flags_from_user_content(content)
        assert '"incomplete"' not in stripped
        assert '"total":900' in stripped
        assert stripped.endswith("Respond with ONLY a valid JSON object.")

    def test_strip_helper_removes_only_flags_and_keeps_original(self):
        entry = {
            "validator_id": "v001",
            "domain": "alpha.example.com",
            "agreement_1h": {"score": 1.0, "total": 900, "missed": 0, "incomplete": False},
            "agreement_24h": {"score": 1.0, "total": 21000, "missed": 0},
        }
        cleaned = _without_agreement_flags(entry)
        assert "incomplete" not in cleaned["agreement_1h"]
        assert cleaned["agreement_1h"]["score"] == 1.0
        assert cleaned["agreement_24h"] == entry["agreement_24h"]
        assert cleaned["domain"] == "alpha.example.com"
        assert entry["agreement_1h"]["incomplete"] is False


V11_PENALTY_RULE = (
    "- fails_minimum_safe_version: true - the scoring service could not confirm that "
    "the validator runs the network's minimum safe version or newer: its release is older "
    "and carries a known security hole, or it reports no readable version. The software "
    "sub-score is exactly 0, and the reasoning names this as the penalty. Take the field "
    "as given; it affects no other sub-score, and a false value has no effect at all.\n"
)
V10_VERSION_DESCRIPTION = "domain and verification status, server version, fee votes,"
V11_VERSION_DESCRIPTION = (
    "domain and verification status, server version with its "
    "`fails_minimum_safe_version` verdict, fee votes,"
)


class TestV11Template:
    def test_v11_is_v10_plus_exactly_the_minimum_safe_version_revision(self):
        v10 = V10_TEMPLATE.read_text()
        v11 = V11_TEMPLATE.read_text()
        for added in (V11_PENALTY_RULE, V11_VERSION_DESCRIPTION):
            assert v11.count(added) == 1
            assert added not in v10
        reverted = (
            v11.replace(V11_PENALTY_RULE, "", 1)
            .replace(V11_VERSION_DESCRIPTION, V10_VERSION_DESCRIPTION, 1)
        )
        assert reverted == v10, (
            "scoring_v11.txt drifted from 'v10 plus the minimum safe version revision'; "
            "update the anchors here if the drift is intentional"
        )

    def test_v11_variant_registered_with_version_flagging(self):
        spec = VARIANTS["v11"]
        assert spec["template"] == V11_TEMPLATE
        assert spec["hidden_fields"] == {"unl"}
        assert spec["inject_flags"] is True
        assert spec["compute_verdicts"] is True
        assert not any(
            variant.get("compute_verdicts")
            for name, variant in VARIANTS.items()
            if name != "v11"
        )


def _entries_without_verdict(content: str) -> str:
    """Rewrite a rendered user message the way a pre-v11 builder produced it."""
    head, rest = content.split("VALIDATOR DATA:\n", 1)
    entries_str, tail = rest.split("\n\nRespond with ONLY", 1)
    entries = json.loads(entries_str)
    for entry in entries:
        del entry["fails_minimum_safe_version"]
    return (
        head
        + "VALIDATOR DATA:\n"
        + json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
        + "\n\nRespond with ONLY"
        + tail
    )


def _write_frozen_round(
    round_dir: Path, template: Path, hidden_fields: set[str], carries_verdict: bool
) -> None:
    """Freeze a two-validator round under the given template."""
    snapshot = ScoringSnapshot(
        round_number=1,
        network="testnet",
        snapshot_timestamp="2026-09-15T00:00:00Z",
        validators=[
            ValidatorProfile(
                master_key=f"nHBv{index}",
                signing_key=f"n9s{index}",
                agreement_1h=AgreementScore(score=1.0, total=900, missed=0, incomplete=False),
                agreement_24h=AgreementScore(score=1.0, total=21000, missed=0, incomplete=False),
                agreement_30d=AgreementScore(score=1.0, total=630000, missed=0, incomplete=False),
                server_version=version,
            )
            for index, version in enumerate(["1.0.4", "1.0.8"], start=1)
        ],
    )
    if carries_verdict:
        snapshot.validators[0].fails_minimum_safe_version = True
    messages, _ = PromptBuilder(prompt_path=template, hidden_fields=hidden_fields).build(snapshot)
    messages = [dict(message) for message in messages]
    evidence = snapshot.model_dump(mode="json")
    if not carries_verdict:
        messages[1]["content"] = _entries_without_verdict(messages[1]["content"])
        for validator in evidence["validators"]:
            del validator["fails_minimum_safe_version"]
    (round_dir / "validator_evidence.json").write_text(json.dumps(evidence))
    (round_dir / "model_request.json").write_text(json.dumps({"messages": messages}))


def _write_round_frozen_before_v11(round_dir: Path) -> None:
    _write_frozen_round(round_dir, V10_TEMPLATE, {"unl"}, carries_verdict=False)


class TestSafeVersionVerdict:
    def test_v11_render_computes_verdicts_for_a_round_frozen_before_v11(self, tmp_path):
        _write_round_frozen_before_v11(tmp_path)

        messages, _, _ = render_variant(tmp_path, "v11", minimum_safe_version="1.0.8")

        entries = _validator_entries(messages[1]["content"])
        assert [entry["fails_minimum_safe_version"] for entry in entries] == [True, False]
        assert "- fails_minimum_safe_version: true -" in messages[0]["content"]

    def test_v11_render_refuses_a_pre_v11_round_without_a_minimum(self, tmp_path):
        _write_round_frozen_before_v11(tmp_path)

        with pytest.raises(ValueError, match="pass --minimum-safe-version"):
            render_variant(tmp_path, "v11")

    def test_v11_render_refuses_a_minimum_that_is_not_a_final_release(self, tmp_path):
        _write_round_frozen_before_v11(tmp_path)

        with pytest.raises(ValueError, match="must be a final release"):
            render_variant(tmp_path, "v11", minimum_safe_version="1.0.8-rc1")

    def test_a_variant_that_computes_no_verdicts_refuses_the_minimum(self, tmp_path):
        _write_round_frozen_before_v11(tmp_path)

        with pytest.raises(ValueError, match="would ignore it"):
            render_variant(tmp_path, "v10", minimum_safe_version="1.0.8")

    def test_a_round_frozen_under_v11_keeps_its_own_verdicts(self, tmp_path):
        _write_frozen_round(tmp_path, V11_TEMPLATE, {"unl"}, carries_verdict=True)

        messages, id_map, _ = render_variant(tmp_path, "v11")

        entries = _validator_entries(messages[1]["content"])
        assert [entry["fails_minimum_safe_version"] for entry in entries] == [True, False]
        assert _master_keys_failing_minimum(messages, id_map) == ["nHBv1"]
        with pytest.raises(ValueError, match="would ignore it"):
            render_variant(tmp_path, "v11", minimum_safe_version="1.0.8")

    def test_baseline_gate_tolerates_the_verdict_a_pre_v11_round_cannot_carry(self, tmp_path):
        _write_frozen_round(tmp_path, V8_TEMPLATE, set(), carries_verdict=False)

        messages, _, frozen = render_variant(tmp_path, "baseline")

        assert "fails_minimum_safe_version" in messages[1]["content"]
        assert "fails_minimum_safe_version" not in frozen["messages"][1]["content"]

    def test_v10_render_of_a_pre_v11_round_passes_the_fidelity_gate(self, tmp_path):
        _write_round_frozen_before_v11(tmp_path)

        messages, _, _ = render_variant(tmp_path, "v10")

        entries = _validator_entries(messages[1]["content"])
        assert [entry["fails_minimum_safe_version"] for entry in entries] == [False, False]

    def test_strips_the_verdict_from_rendered_user_content(self):
        entries = [{"validator_id": "v001", "server_version": "1.0.4", "fails_minimum_safe_version": True}]
        content = (
            "SELECTOR CONTEXT:\n\nVALIDATOR DATA:\n"
            + json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
            + "\n\nRespond with ONLY a valid JSON object."
        )
        stripped = _strip_verdict_from_user_content(content)
        assert "fails_minimum_safe_version" not in stripped
        assert '"server_version":"1.0.4"' in stripped
