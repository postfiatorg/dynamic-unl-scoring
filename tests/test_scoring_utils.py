"""Tests for standalone scoring prompt utility support."""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scoring_utils import (  # noqa: E402
    PROMPT_VERSION_CHOICES,
    build_prompt_layer,
    validate_scoring_contract,
)


VALID_NETWORK_REPORT = {
    "headline": "Strong Consensus, Concentrated Infrastructure",
    "summary": "Consensus health is strong while infrastructure concentration limits diversity.",
    "categories": {
        "consensus": {
            "tone": "positive",
            "body": "Most validators show strong agreement across the observed windows.",
        },
        "reliability": {
            "tone": "mixed",
            "body": "Reliable operators are present, but public accountability varies.",
        },
        "software": {
            "tone": "neutral",
            "body": "Software versions are generally current with limited score separation.",
        },
        "diversity": {
            "tone": "warning",
            "body": "Provider and country concentration remain the main network-level limits.",
        },
        "identity": {
            "tone": "mixed",
            "body": "Verified domains improve trust while missing domains cap identity scores.",
        },
    },
}


def _result_with_report(report=None):
    network_report = report or VALID_NETWORK_REPORT
    return {
        "validator_id_map": {"v001": "nHBmaster1"},
        "scores_by_validator_id": {
            "v001": {
                "score": 85,
                "consensus": 95,
                "reliability": 80,
                "software": 90,
                "diversity": 60,
                "identity": 70,
                "reasoning": "Strong consensus and current software. Diversity is limited.",
            },
            "network_report": network_report,
        },
    }


def test_v8_layer_still_renders_unl_membership():
    layer = build_prompt_layer("v8")
    assert '"unl":' in layer["messages"][1]["content"]


def test_v9_layer_hides_unl_and_renders_concentration():
    layer = build_prompt_layer("v9")
    user_content = layer["messages"][1]["content"]
    assert '"unl":' not in user_content
    assert "NETWORK CONCENTRATION:" in user_content
    assert '"provider_family":' in user_content
    assert layer["name"] == "scoring_v9"
    assert layer["prompt"].endswith("prompts/scoring_v9.txt")


def test_v10_layer_renders_incomplete_flags():
    layer = build_prompt_layer("v10")
    user_content = layer["messages"][1]["content"]
    assert '"unl":' not in user_content
    assert '"incomplete":' in user_content
    assert "AGREEMENT DATA QUALITY FLAGS:" in layer["messages"][0]["content"]
    assert layer["name"] == "scoring_v10"
    assert layer["prompt"].endswith("prompts/scoring_v10.txt")


def test_prompt_version_choices_include_active_v10():
    assert PROMPT_VERSION_CHOICES == ("v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10")


def test_every_prompt_version_choice_builds_a_layer():
    for version in PROMPT_VERSION_CHOICES:
        layer = build_prompt_layer(version)
        assert layer["messages"], f"prompt layer for {version} rendered no messages"


def test_build_prompt_layer_supports_v8_contract():
    layer = build_prompt_layer("v8")
    user_content = layer["messages"][1]["content"]

    assert layer["name"] == "scoring_v8"
    assert layer["prompt"].endswith("prompts/scoring_v8.txt")
    assert layer["allowed_extra_keys"] == ["network_report"]
    assert "network_report" in user_content
    assert "network_summary" not in user_content
    assert "SELECTOR CONTEXT" in user_content


def test_build_prompt_layer_supports_v7_contract():
    layer = build_prompt_layer("v7")
    user_content = layer["messages"][1]["content"]

    assert layer["name"] == "scoring_v7"
    assert layer["prompt"].endswith("prompts/scoring_v7.txt")
    assert layer["allowed_extra_keys"] == ["network_report"]
    assert "network_report" in user_content
    assert "network_summary" not in user_content
    assert "SELECTOR CONTEXT" in user_content


def test_build_prompt_layer_supports_v6_contract():
    layer = build_prompt_layer("v6")
    user_content = layer["messages"][1]["content"]

    assert layer["name"] == "scoring_v6"
    assert layer["prompt"].endswith("prompts/scoring_v6.txt")
    assert layer["allowed_extra_keys"] == ["network_report"]
    assert "network_report" in user_content
    assert "network_summary" not in user_content
    assert "SELECTOR CONTEXT" in user_content


def test_build_prompt_layer_preserves_v3_summary_contract():
    layer = build_prompt_layer("v3")

    assert layer["name"] == "scoring_v3"
    assert layer["prompt"].endswith("prompts/scoring_v3.txt")
    assert layer["allowed_extra_keys"] == ["network_summary"]


def test_validate_scoring_contract_accepts_network_report_shape():
    contract = validate_scoring_contract(_result_with_report())

    assert contract["network_report_present"] is True
    assert contract["network_summary_present"] is False
    assert contract["invalid_network_report_fields"] == []
    assert contract["invalid_dimension_fields"] == []


def test_validate_scoring_contract_rejects_invalid_network_report_tone():
    report = {
        **VALID_NETWORK_REPORT,
        "categories": {
            **VALID_NETWORK_REPORT["categories"],
            "diversity": {
                **VALID_NETWORK_REPORT["categories"]["diversity"],
                "tone": "severe",
            },
        },
    }

    contract = validate_scoring_contract(_result_with_report(report))

    assert contract["network_report_present"] is False
    assert contract["invalid_network_report_fields"] == ["categories.diversity.tone"]
