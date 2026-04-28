"""Tests for the response parser and scoring result validation."""

import json

from scoring_service.services.response_parser import (
    ScoringResult,
    ValidatorScore,
    _extract_json,
    parse_response,
)


VALID_ENTRY = {
    "score": 85,
    "consensus": 95,
    "reliability": 80,
    "software": 90,
    "diversity": 60,
    "identity": 70,
    "reasoning": "Strong consensus performance across all windows.",
}

ID_MAP = {
    "v001": {
        "master_key": "nHBmaster1",
        "signing_key": "n9sign1",
    },
    "v002": {
        "master_key": "nHBmaster2",
        "signing_key": "n9sign2",
    },
}


def _build_response(entries=None, summary="Network looks healthy."):
    if entries is None:
        entries = {
            "v001": VALID_ENTRY,
            "v002": {**VALID_ENTRY, "score": 72, "diversity": 45},
        }
    data = {**entries, "network_summary": summary}
    return json.dumps(data)


class TestExtractJson:
    def test_extracts_plain_json(self):
        text = '{"v001": {"score": 85}}'
        result = _extract_json(text)
        assert result == {"v001": {"score": 85}}

    def test_strips_markdown_code_fences(self):
        text = '```json\n{"v001": {"score": 85}}\n```'
        result = _extract_json(text)
        assert result == {"v001": {"score": 85}}

    def test_strips_leading_commentary(self):
        text = 'Here are the scores:\n{"v001": {"score": 85}}'
        result = _extract_json(text)
        assert result == {"v001": {"score": 85}}

    def test_strips_trailing_commentary(self):
        text = '{"v001": {"score": 85}}\nI hope this helps!'
        result = _extract_json(text)
        assert result == {"v001": {"score": 85}}

    def test_returns_none_for_empty_text(self):
        assert _extract_json("") is None
        assert _extract_json("   ") is None

    def test_returns_none_for_unparseable_text(self):
        assert _extract_json("not json at all") is None

    def test_returns_none_for_json_array(self):
        assert _extract_json('[1, 2, 3]') is None

    def test_handles_nested_braces(self):
        text = '{"v001": {"score": 85, "reasoning": "good {performance}"}}'
        result = _extract_json(text)
        assert result is not None
        assert result["v001"]["score"] == 85


class TestParseResponse:
    def test_complete_valid_response(self):
        result = parse_response(_build_response(), ID_MAP)

        assert result.complete is True
        assert len(result.errors) == 0
        assert len(result.validator_scores) == 2
        assert result.network_summary == "Network looks healthy."
        assert result.raw_response == _build_response()

    def test_remaps_anonymous_ids_to_master_keys(self):
        result = parse_response(_build_response(), ID_MAP)

        keys = {vs.master_key for vs in result.validator_scores}
        assert keys == {"nHBmaster1", "nHBmaster2"}

    def test_preserves_all_score_fields(self):
        result = parse_response(_build_response(), ID_MAP)

        v1 = next(vs for vs in result.validator_scores if vs.master_key == "nHBmaster1")
        assert v1.score == 85
        assert v1.consensus == 95
        assert v1.reliability == 80
        assert v1.software == 90
        assert v1.diversity == 60
        assert v1.identity == 70
        assert v1.reasoning == "Strong consensus performance across all windows."

    def test_incomplete_when_json_unparseable(self):
        result = parse_response("not json", ID_MAP)

        assert result.complete is False
        assert len(result.validator_scores) == 0
        assert "Failed to extract valid JSON" in result.errors[0]
        assert result.raw_response == "not json"

    def test_incomplete_when_validator_missing(self):
        entries = {"v001": VALID_ENTRY}
        result = parse_response(_build_response(entries=entries), ID_MAP)

        assert result.complete is False
        assert any("Missing validators" in e for e in result.errors)
        assert len(result.validator_scores) == 1

    def test_reports_unexpected_extra_entries(self):
        entries = {
            "v001": VALID_ENTRY,
            "v002": VALID_ENTRY,
            "v099": VALID_ENTRY,
        }
        result = parse_response(_build_response(entries=entries), ID_MAP)

        assert any("Unexpected entries" in e for e in result.errors)
        assert len(result.validator_scores) == 2

    def test_incomplete_when_score_out_of_range(self):
        entries = {
            "v001": {**VALID_ENTRY, "score": 150},
            "v002": VALID_ENTRY,
        }
        result = parse_response(_build_response(entries=entries), ID_MAP)

        assert result.complete is False
        assert any("invalid or missing score" in e for e in result.errors)
        assert len(result.validator_scores) == 1

    def test_incomplete_when_sub_score_missing(self):
        bad_entry = {k: v for k, v in VALID_ENTRY.items() if k != "diversity"}
        entries = {
            "v001": bad_entry,
            "v002": VALID_ENTRY,
        }
        result = parse_response(_build_response(entries=entries), ID_MAP)

        assert result.complete is False
        assert any("diversity sub-score" in e for e in result.errors)

    def test_incomplete_when_sub_score_out_of_range(self):
        entries = {
            "v001": {**VALID_ENTRY, "consensus": -5},
            "v002": VALID_ENTRY,
        }
        result = parse_response(_build_response(entries=entries), ID_MAP)

        assert result.complete is False
        assert any("consensus sub-score" in e for e in result.errors)

    def test_incomplete_when_reasoning_empty(self):
        entries = {
            "v001": {**VALID_ENTRY, "reasoning": ""},
            "v002": VALID_ENTRY,
        }
        result = parse_response(_build_response(entries=entries), ID_MAP)

        assert result.complete is False
        assert any("reasoning" in e for e in result.errors)

    def test_incomplete_when_network_summary_missing(self):
        data = {"v001": VALID_ENTRY, "v002": VALID_ENTRY}
        result = parse_response(json.dumps(data), ID_MAP)

        assert result.complete is False
        assert any("network_summary" in e for e in result.errors)

    def test_incomplete_when_network_summary_empty(self):
        result = parse_response(_build_response(summary=""), ID_MAP)

        assert result.complete is False
        assert any("network_summary" in e for e in result.errors)

    def test_handles_float_scores(self):
        entries = {
            "v001": {**VALID_ENTRY, "score": 85.0, "consensus": 95.0},
            "v002": VALID_ENTRY,
        }
        result = parse_response(_build_response(entries=entries), ID_MAP)

        v1 = next(vs for vs in result.validator_scores if vs.master_key == "nHBmaster1")
        assert v1.score == 85
        assert v1.consensus == 95

    def test_rejects_boolean_scores(self):
        entries = {
            "v001": {**VALID_ENTRY, "score": True},
            "v002": VALID_ENTRY,
        }
        result = parse_response(_build_response(entries=entries), ID_MAP)

        assert result.complete is False
        assert any("invalid or missing score" in e for e in result.errors)

    def test_handles_code_fenced_response(self):
        raw = "```json\n" + _build_response() + "\n```"
        result = parse_response(raw, ID_MAP)

        assert result.complete is True
        assert len(result.validator_scores) == 2

    def test_handles_commentary_wrapped_response(self):
        raw = "Here are the scores:\n" + _build_response() + "\nDone."
        result = parse_response(raw, ID_MAP)

        assert result.complete is True
        assert len(result.validator_scores) == 2

    def test_preserves_raw_response(self):
        raw = _build_response()
        result = parse_response(raw, ID_MAP)

        assert result.raw_response == raw

    def test_entry_not_dict_reported(self):
        entries = {
            "v001": "not a dict",
            "v002": VALID_ENTRY,
        }
        result = parse_response(_build_response(entries=entries), ID_MAP)

        assert result.complete is False
        assert any("not a dict" in e for e in result.errors)

    def test_empty_id_map(self):
        result = parse_response(_build_response(), {})

        assert result.complete is False
        assert any("Unexpected entries" in e for e in result.errors)
        assert len(result.validator_scores) == 0

    def test_validators_sorted_by_master_key(self):
        result = parse_response(_build_response(), ID_MAP)

        keys = [vs.master_key for vs in result.validator_scores]
        assert keys == sorted(keys)
