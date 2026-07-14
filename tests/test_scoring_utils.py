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


def test_prompt_version_choices_include_active_v6():
    assert PROMPT_VERSION_CHOICES == ("v1", "v2", "v3", "v4", "v5", "v6")


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
