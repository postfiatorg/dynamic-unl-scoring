"""Tests for the PromptBuilder scoring prompt construction."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scoring_service.config import settings
from scoring_service.models import (
    AgreementScore,
    ASNInfo,
    GeoLocation,
    ScoringSnapshot,
    ValidatorProfile,
)
from scoring_service.services.prompt_builder import PROMPT_PATH, PromptBuilder


def _make_snapshot(validators=None):
    if validators is None:
        validators = [
            ValidatorProfile(
                master_key="nHBval2",
                signing_key="n9sign2",
                domain="beta.example.com",
                domain_verified=True,
                agreement_1h=AgreementScore(score=1.0, total=900, missed=0),
                agreement_24h=AgreementScore(score=0.998, total=21000, missed=42),
                agreement_30d=AgreementScore(score=0.995, total=630000, missed=3150),
                server_version="3.0.0",
                unl=True,
                base_fee=10,
                ip="144.202.24.188",
                asn=ASNInfo(asn=20473, as_name="Vultr Holdings"),
                geolocation=GeoLocation(country="United States"),
            ),
            ValidatorProfile(
                master_key="nHBval1",
                signing_key="n9sign1",
                domain="alpha.example.com",
                domain_verified=False,
                agreement_1h=AgreementScore(score=0.95, total=900, missed=45),
                agreement_24h=AgreementScore(score=0.90, total=21000, missed=2100),
                agreement_30d=AgreementScore(score=0.85, total=630000, missed=94500),
                server_version="2.9.0",
                unl=False,
                base_fee=10,
                ip=None,
                asn=None,
                geolocation=None,
            ),
        ]
    return ScoringSnapshot(
        round_number=1,
        network="testnet",
        snapshot_timestamp=datetime(2026, 4, 1, tzinfo=timezone.utc),
        validators=validators,
    )


class TestBuild:
    def test_default_prompt_is_scoring_v5(self):
        assert PROMPT_PATH.name == "scoring_v5.txt"

    def test_returns_messages_and_id_map(self):
        builder = PromptBuilder()
        messages, id_map = builder.build(_make_snapshot())

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert len(id_map) == 2

    def test_sorts_validators_by_master_key(self):
        builder = PromptBuilder()
        messages, id_map = builder.build(_make_snapshot())

        assert id_map["v001"] == {
            "master_key": "nHBval1",
            "signing_key": "n9sign1",
        }
        assert id_map["v002"] == {
            "master_key": "nHBval2",
            "signing_key": "n9sign2",
        }

    def test_deterministic_output(self):
        snapshot = _make_snapshot()
        builder = PromptBuilder()

        messages1, id_map1 = builder.build(snapshot)
        messages2, id_map2 = builder.build(snapshot)

        assert messages1 == messages2
        assert id_map1 == id_map2

    def test_strips_master_key_signing_key_and_ip(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        assert "nHBval1" not in user_content
        assert "nHBval2" not in user_content
        assert "n9sign1" not in user_content
        assert "n9sign2" not in user_content
        assert "144.202.24.188" not in user_content

    def test_includes_anonymous_validator_ids(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        assert "v001" in user_content
        assert "v002" in user_content

    def test_includes_scoring_relevant_fields(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        assert "alpha.example.com" in user_content
        assert "Vultr Holdings" in user_content
        assert "United States" in user_content
        assert "3.0.0" in user_content

    def test_includes_null_fields_explicitly(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        validator_data = user_content.split("VALIDATOR DATA:\n")[1]
        parsed = json.loads(
            validator_data.split("\n\nRespond with ONLY")[0]
        )

        v001 = parsed[0]
        assert v001["validator_id"] == "v001"
        assert v001["asn"] is None
        assert v001["geolocation"] is None

    def test_system_prompt_contains_scoring_dimensions(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        assert "CONSENSUS PERFORMANCE" in system
        assert "OPERATIONAL RELIABILITY" in system
        assert "SOFTWARE DILIGENCE" in system
        assert "GEOGRAPHIC AND INFRASTRUCTURE DIVERSITY" in system
        assert "IDENTITY AND REPUTATION" in system

    def test_system_prompt_contains_null_field_penalties(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        assert "country: null" in system
        assert "asn: null" in system
        assert "domain: null" in system
        assert "identity: null" in system

    def test_system_prompt_frames_diversity_as_observable_endpoint_evidence(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        assert "observable public endpoint evidence" in system
        assert "not definitive proof" in system
        assert "sentry, VPN, proxy, NAT endpoint, or relay" in system
        assert "modest transparency signal" in system

    def test_system_prompt_limits_missing_endpoint_penalty_scope(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        assert "privacy-preserving operation" in system
        assert "firewall or crawl configuration" in system
        assert "topology lag" in system
        assert "not treat unresolved endpoint evidence as proof of poor operation" in system
        assert "Do not penalize consensus, software, identity, or reliability" in system

    def test_system_prompt_limits_unl_membership_as_scoring_shortcut(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        assert "Current UNL membership should not become a scoring shortcut" in system
        assert "separate churn control after scoring" in system

    def test_system_prompt_anchors_identity_null_behavior(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        assert "verified domain with null identity" in system
        assert "no domain with null identity" in system

    def test_system_prompt_handles_newer_minor_versions(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        assert "Do not mark a validator down merely because it is on a newer version" in system

    def test_user_prompt_requests_concrete_reasoning(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        assert "usually 2 sentences, at most 3" in user_content
        assert "strongest positive factor and the main penalty" in user_content
        assert "Avoid generic language" in user_content

    def test_system_prompt_specifies_dimensional_sub_score_fields(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        for field in ["consensus", "reliability", "software", "diversity", "identity"]:
            assert f'"{field}"' in system

    def test_user_prompt_requires_network_report(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        assert "network_report" in user_content
        assert "network_summary" not in user_content

    def test_user_prompt_defines_network_report_shape(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        assert '"headline"' in user_content
        assert '"summary"' in user_content
        assert '"categories"' in user_content
        for field in ["consensus", "reliability", "software", "diversity", "identity"]:
            assert f'"{field}"' in user_content
        for tone in ["positive", "mixed", "warning", "negative", "neutral"]:
            assert f'"{tone}"' in user_content
        assert (
            "Use aggregate group references in network_report text rather than "
            "anonymous validator IDs or public keys."
            in user_content
        )

    def test_user_prompt_includes_selector_context(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        assert "SELECTOR CONTEXT" in user_content
        assert f"Maximum selected UNL validators: {settings.unl_max_size}" in user_content
        assert (
            f"Minimum score cutoff for UNL eligibility: {settings.unl_score_cutoff}"
            in user_content
        )
        assert (
            "Churn-control score gap for replacing close-scoring incumbents: "
            f"{settings.unl_min_score_gap}"
            in user_content
        )
        assert "{unl_max_size}" not in user_content
        assert "{unl_score_cutoff}" not in user_content
        assert "{unl_min_score_gap}" not in user_content

    def test_system_prompt_frames_network_report_as_selection_aware(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        assert "selection-aware" in system
        assert "selected-UNL view" in system
        assert "selected UNL" in system
        assert "lower-ranked alternates or rejected candidates as candidate-pool context" in system
        assert "candidate-pool context" in system
        assert "projected" not in system

    def test_system_prompt_prefers_aggregate_dashboard_language(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        assert "group-level language suitable for a dashboard" in system
        assert "selected validator set" in system
        assert "Write network_report in aggregate terms" in system
        assert "Keep validator IDs and public keys out of network_report" in system
        assert "Prefer qualitative aggregate wording" in system

    def test_system_prompt_prefers_calm_headlines(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        system = messages[0]["content"]
        assert "short, calm, descriptive title" in system
        assert "Diversity Constraints" in system
        assert "Infrastructure Concentration" in system
        assert "dramatic risk language" in system

    def test_user_prompt_uses_final_selected_unl_language(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        assert "primarily assess the selected UNL" in user_content
        assert "projected" not in user_content

    def test_user_prompt_requires_dimensional_sub_scores(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        for field in ["consensus", "reliability", "software", "diversity", "identity"]:
            assert f'"{field}"' in user_content

    def test_empty_validators(self):
        snapshot = _make_snapshot(validators=[])
        builder = PromptBuilder()
        messages, id_map = builder.build(snapshot)

        assert len(messages) == 2
        assert id_map == {}
        assert "[]" in messages[1]["content"]

    def test_no_topology_data_in_prompt(self):
        builder = PromptBuilder()
        messages, _ = builder.build(_make_snapshot())

        user_content = messages[1]["content"]
        assert "topology" not in user_content.lower()

    def test_id_map_covers_all_validators(self):
        validators = [
            ValidatorProfile(master_key=f"nHB{i:03d}", signing_key=f"n9s{i:03d}")
            for i in range(10)
        ]
        snapshot = _make_snapshot(validators=validators)
        builder = PromptBuilder()
        _, id_map = builder.build(snapshot)

        assert len(id_map) == 10
        assert set(id_map.keys()) == {f"v{i:03d}" for i in range(1, 11)}

    def test_prompt_within_token_budget_for_40_validators(self):
        validators = [
            ValidatorProfile(
                master_key=f"nHB{i:03d}",
                signing_key=f"n9s{i:03d}",
                domain=f"validator-{i}.example.com",
                domain_verified=True,
                agreement_1h=AgreementScore(score=0.999, total=900, missed=1),
                agreement_24h=AgreementScore(score=0.998, total=21000, missed=42),
                agreement_30d=AgreementScore(score=0.995, total=630000, missed=3150),
                server_version="3.0.0",
                unl=True,
                base_fee=10,
                asn=ASNInfo(asn=20473, as_name="Vultr Holdings"),
                geolocation=GeoLocation(country="United States"),
            )
            for i in range(40)
        ]
        snapshot = _make_snapshot(validators=validators)
        builder = PromptBuilder()
        messages, _ = builder.build(snapshot)

        token_estimate = sum(len(m["content"]) for m in messages) // 4
        assert token_estimate < 28000


class TestInit:
    def test_raises_on_invalid_template(self, tmp_path):
        bad_template = tmp_path / "bad.txt"
        bad_template.write_text("no markers here")

        with pytest.raises(ValueError, match="USER PROMPT"):
            PromptBuilder(prompt_path=bad_template)

    def test_loads_custom_template(self, tmp_path):
        template = tmp_path / "custom.txt"
        template.write_text(
            "### SYSTEM PROMPT ###\nCustom system.\n"
            "### USER PROMPT ###\nData: {validator_data}"
        )
        builder = PromptBuilder(prompt_path=template)
        messages, _ = builder.build(_make_snapshot())

        assert "Custom system." in messages[0]["content"]
