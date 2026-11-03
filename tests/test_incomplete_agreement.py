"""Exercise agreement exclusion with the repository's real VHS snapshot.

The March snapshot predates per-window incomplete flags. Keep its measured
score/total/missed values intact and vary only the flags under test.
"""

import json
from datetime import datetime
from itertools import product

import pytest

from scoring_service.clients.vhs import _parse_validator
from scoring_service.config import REPO_ROOT
from scoring_service.models import ScoringSnapshot
from scoring_service.services.prompt_builder import PromptBuilder
from scripts.replay_prompt_variants import render_variant
from scripts.scoring_utils import legacy_validator_to_profile

WINDOWS = ("agreement_1h", "agreement_24h", "agreement_30d")


@pytest.fixture
def real_snapshot():
    raw = json.loads((REPO_ROOT / "data" / "testnet_snapshot.json").read_text())
    return ScoringSnapshot(
        round_number=1,
        network=raw["network"],
        snapshot_timestamp=datetime.fromisoformat(raw["fetched_at"]),
        validators=[legacy_validator_to_profile(v) for v in raw["validators"]],
    )


def _entries(messages):
    data = messages[1]["content"].split("VALIDATOR DATA:\n", 1)[1]
    return json.loads(data.split("\n\nRespond with ONLY", 1)[0])


@pytest.mark.parametrize("flags", list(product((True, False, None), repeat=3)))
def test_real_agreement_windows_exclude_only_explicitly_incomplete(real_snapshot, flags):
    for validator in real_snapshot.validators:
        for window, flag in zip(WINDOWS, flags):
            getattr(validator, window).incomplete = flag

    before = real_snapshot.model_dump(mode="json")
    before_hash = real_snapshot.content_hash()
    builder = PromptBuilder()
    messages, identities = builder.build(real_snapshot)
    entries = _entries(messages)

    assert len(entries) == len(real_snapshot.validators) == 42
    for entry, validator in zip(
        entries, sorted(real_snapshot.validators, key=lambda v: v.master_key)
    ):
        assert identities[entry["validator_id"]] == {
            "master_key": validator.master_key,
            "signing_key": validator.signing_key,
        }
        for window, flag in zip(WINDOWS, flags):
            if flag is True:
                # No score, total or missed count can influence the model.
                assert entry[window] == {"incomplete": True}
            else:
                assert entry[window] == getattr(validator, window).model_dump(mode="json")

    # The fixture includes real near-zero outage evidence in every window.
    for window, flag in zip(WINDOWS, flags):
        if flag is not True:
            assert any(entry[window]["score"] < 0.01 for entry in entries)

    assert real_snapshot.model_dump(mode="json") == before
    assert real_snapshot.content_hash() == before_hash
    assert builder.build(real_snapshot) == (messages, identities)


def test_captured_vhs_flags_exclude_partial_and_preserve_complete_windows():
    raw = json.loads(
        (REPO_ROOT / "data" / "vhs_agreement_sample_20261029.json").read_text()
    )
    snapshot = ScoringSnapshot(
        round_number=1,
        network=raw["network"],
        snapshot_timestamp=datetime.fromisoformat(raw["fetched_at"]),
        validators=[_parse_validator(v) for v in raw["validators"]],
    )
    before = snapshot.model_dump(mode="json")
    messages, identities = PromptBuilder().build(snapshot)
    raw_by_key = {v["master_key"]: v for v in raw["validators"]}
    excluded_count = complete_count = 0
    for entry in _entries(messages):
        source = raw_by_key[identities[entry["validator_id"]]["master_key"]]
        for window in WINDOWS:
            raw_window = source["agreement_30day" if window == "agreement_30d" else window]
            if raw_window["incomplete"]:
                excluded_count += 1
                assert entry[window] == {"incomplete": True}
            else:
                complete_count += 1
                assert entry[window] == {
                    **raw_window,
                    "score": float(raw_window["score"]),
                }
    assert (excluded_count, complete_count) == (1, 5)
    assert snapshot.model_dump(mode="json") == before


def test_historical_v12_replay_keeps_partial_measurements(real_snapshot, tmp_path):
    real_snapshot.validators[0].agreement_24h.incomplete = True
    messages, identities = PromptBuilder(
        prompt_path=REPO_ROOT / "prompts" / "scoring_v12.txt",
        exclude_incomplete_agreement=False,
    ).build(real_snapshot)
    (tmp_path / "validator_evidence.json").write_text(real_snapshot.model_dump_json())
    (tmp_path / "model_request.json").write_text(json.dumps({"messages": messages}))

    replayed, replay_ids, _ = render_variant(tmp_path, "v12")

    assert replayed == messages
    assert replay_ids == identities
    partial = next(
        entry["agreement_24h"]
        for entry in _entries(replayed)
        if entry["agreement_24h"]["incomplete"] is True
    )
    assert partial == real_snapshot.validators[0].agreement_24h.model_dump(mode="json")


def test_mixed_validator_flags_preserve_other_prompt_data(real_snapshot):
    builder = PromptBuilder()
    baseline_messages, baseline_ids = builder.build(real_snapshot)
    baseline_entries = _entries(baseline_messages)
    flagged_windows = {}
    for index, validator in enumerate(real_snapshot.validators):
        window = WINDOWS[index % len(WINDOWS)]
        getattr(validator, window).incomplete = True
        flagged_windows[validator.master_key] = window

    messages, identities = builder.build(real_snapshot)
    assert identities == baseline_ids
    for actual, expected in zip(_entries(messages), baseline_entries):
        master_key = identities[actual["validator_id"]]["master_key"]
        expected[flagged_windows[master_key]] = {"incomplete": True}
        assert actual == expected
    assert messages[0] == baseline_messages[0]
    # Provider/country counts and selector context are unaffected.
    assert messages[1]["content"].split("VALIDATOR DATA:", 1)[0] == (
        baseline_messages[1]["content"].split("VALIDATOR DATA:", 1)[0]
    )
