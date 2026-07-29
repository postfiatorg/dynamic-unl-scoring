"""Tests for the prompt-variant replay harness template derivation."""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from replay_prompt_variants import (  # noqa: E402
    V8_TEMPLATE,
    VARIANT_BUILDERS,
    VARIANTS_DIR,
    build_concentration_template,
    build_no_unl_template,
    build_reliability_template,
)


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
