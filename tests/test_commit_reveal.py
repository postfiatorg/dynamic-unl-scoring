"""Tests for Dynamic UNL commit-reveal protocol helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from scoring_service.services.commit_reveal import (
    COMMITMENT_PREIMAGE_TYPE,
    PROTOCOL_VERSION,
    ROUND_ANNOUNCEMENT_TYPE,
    VALIDATOR_COMMIT_TYPE,
    VALIDATOR_REVEAL_TYPE,
    CommitRevealValidationError,
    LedgerPosition,
    build_commit_payload,
    build_commit_signing_bytes,
    build_commit_signing_payload,
    build_commitment_preimage,
    build_reveal_payload,
    build_reveal_signing_bytes,
    build_reveal_signing_payload,
    canonical_json_bytes,
    canonical_sha256,
    commit_matches_announcement,
    commit_signing_bytes,
    commit_signing_payload,
    compute_commitment_hash,
    compute_reveal_commitment_hash,
    first_by_ledger_order,
    is_commit_within_window,
    is_reveal_within_window,
    reveal_matches_announcement,
    reveal_matches_commit,
    reveal_signing_bytes,
    reveal_signing_payload,
    validate_commit_payload,
    validate_output_hashes,
    validate_reveal_payload,
    validate_round_announcement,
)


INPUT_PACKAGE_HASH = "d" * 64
MODEL_RESPONSE_HASH = "a" * 64
VALIDATOR_SCORES_HASH = "b" * 64
SELECTED_UNL_HASH = "c" * 64
SALT = "1" * 64
SIGNATURE = "BADC0FFE"
VALIDATOR_MASTER_KEY = "nHU" + "A" * 30
OTHER_VALIDATOR_MASTER_KEY = "nHU" + "B" * 30
INPUT_PACKAGE_CID = "Qm" + "A" * 44
NETWORK = "testnet"
ROUND_NUMBER = 123
KNOWN_COMMITMENT_HASH = "e76759106d1ad1ca07e73c5051535158af60304fe70b6a9f6dd2b05c3420d922"

INPUT_FROZEN_AT = datetime(2026, 5, 25, 0, 0, tzinfo=timezone.utc)
COMMIT_OPENS_AT = datetime(2026, 5, 25, 0, 5, tzinfo=timezone.utc)
COMMIT_CLOSES_AT = datetime(2026, 5, 25, 0, 30, tzinfo=timezone.utc)
REVEAL_OPENS_AT = datetime(2026, 5, 25, 0, 30, tzinfo=timezone.utc)
REVEAL_CLOSES_AT = datetime(2026, 5, 25, 1, 0, tzinfo=timezone.utc)


def _output_hashes() -> dict[str, str]:
    return {
        "model_response_hash": MODEL_RESPONSE_HASH,
        "validator_scores_hash": VALIDATOR_SCORES_HASH,
        "selected_unl_hash": SELECTED_UNL_HASH,
    }


def _commitment_kwargs(**overrides) -> dict:
    values = {
        "protocol_version": PROTOCOL_VERSION,
        "network": NETWORK,
        "round_number": ROUND_NUMBER,
        "validator_master_key": VALIDATOR_MASTER_KEY,
        "input_package_hash": INPUT_PACKAGE_HASH,
        "output_hashes": _output_hashes(),
        "salt": SALT,
    }
    values.update(overrides)
    return values


def _announcement_payload(**overrides) -> dict:
    values = {
        "type": ROUND_ANNOUNCEMENT_TYPE,
        "protocol_version": PROTOCOL_VERSION,
        "network": NETWORK,
        "round_number": ROUND_NUMBER,
        "round_kind": "normal",
        "input_package_cid": INPUT_PACKAGE_CID,
        "input_package_hash": INPUT_PACKAGE_HASH,
        "input_frozen_at": INPUT_FROZEN_AT.isoformat(),
        "commit_opens_at": COMMIT_OPENS_AT.isoformat(),
        "commit_closes_at": COMMIT_CLOSES_AT.isoformat(),
        "reveal_opens_at": REVEAL_OPENS_AT.isoformat(),
        "reveal_closes_at": REVEAL_CLOSES_AT.isoformat(),
    }
    values.update(overrides)
    return values


def _reveal_payload(**overrides) -> dict:
    values = {
        "protocol_version": PROTOCOL_VERSION,
        "network": NETWORK,
        "round_number": ROUND_NUMBER,
        "validator_master_key": VALIDATOR_MASTER_KEY,
        "input_package_hash": INPUT_PACKAGE_HASH,
        "output_hashes": _output_hashes(),
        "salt": SALT,
        "signature": SIGNATURE,
    }
    values.update(overrides)
    return build_reveal_payload(**values)


def _commit_payload(**overrides) -> dict:
    values = {
        "protocol_version": PROTOCOL_VERSION,
        "network": NETWORK,
        "round_number": ROUND_NUMBER,
        "validator_master_key": VALIDATOR_MASTER_KEY,
        "input_package_hash": INPUT_PACKAGE_HASH,
        "commitment_hash": KNOWN_COMMITMENT_HASH,
        "signature": SIGNATURE,
    }
    values.update(overrides)
    return build_commit_payload(**values)


class TestCanonicalCommitment:
    def test_commitment_hash_is_stable_for_known_preimage(self):
        assert compute_commitment_hash(**_commitment_kwargs()) == KNOWN_COMMITMENT_HASH

    def test_commitment_preimage_is_domain_separated(self):
        preimage = build_commitment_preimage(**_commitment_kwargs())
        assert preimage["type"] == COMMITMENT_PREIMAGE_TYPE
        assert preimage["input_package_hash"] == INPUT_PACKAGE_HASH
        assert "signature" not in preimage
        assert "input_package_cid" not in preimage

    def test_canonical_json_is_field_order_independent(self):
        first = {
            "network": NETWORK,
            "round_number": ROUND_NUMBER,
            "output_hashes": {
                "selected_unl_hash": SELECTED_UNL_HASH,
                "validator_scores_hash": VALIDATOR_SCORES_HASH,
                "model_response_hash": MODEL_RESPONSE_HASH,
            },
        }
        second = {
            "round_number": ROUND_NUMBER,
            "output_hashes": {
                "model_response_hash": MODEL_RESPONSE_HASH,
                "validator_scores_hash": VALIDATOR_SCORES_HASH,
                "selected_unl_hash": SELECTED_UNL_HASH,
            },
            "network": NETWORK,
        }

        assert canonical_json_bytes(first) == canonical_json_bytes(second)
        assert canonical_sha256(first) == canonical_sha256(second)


class TestRevealMatching:
    def test_reveal_matches_commit_for_same_frozen_input_context(self):
        reveal = validate_reveal_payload(_reveal_payload())
        commit = validate_commit_payload(
            _commit_payload(commitment_hash=compute_reveal_commitment_hash(reveal))
        )

        assert reveal_matches_commit(reveal, commit)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("network", "devnet"),
            ("round_number", ROUND_NUMBER + 1),
            ("validator_master_key", OTHER_VALIDATOR_MASTER_KEY),
            ("input_package_hash", "e" * 64),
        ],
    )
    def test_reveal_does_not_match_commit_when_binding_field_changes(self, field, value):
        original_reveal = validate_reveal_payload(_reveal_payload())
        commit = validate_commit_payload(
            _commit_payload(commitment_hash=compute_reveal_commitment_hash(original_reveal))
        )
        mutated_payload = _reveal_payload(**{field: value})
        mutated_reveal = validate_reveal_payload(mutated_payload)

        assert not reveal_matches_commit(mutated_reveal, commit)

    @pytest.mark.parametrize(
        "output_hashes,salt",
        [
            (
                {
                    "model_response_hash": "f" * 64,
                    "validator_scores_hash": VALIDATOR_SCORES_HASH,
                    "selected_unl_hash": SELECTED_UNL_HASH,
                },
                SALT,
            ),
            (_output_hashes(), "2" * 64),
        ],
    )
    def test_reveal_does_not_match_commit_when_output_hash_or_salt_changes(
        self,
        output_hashes,
        salt,
    ):
        original_reveal = validate_reveal_payload(_reveal_payload())
        commit = validate_commit_payload(
            _commit_payload(commitment_hash=compute_reveal_commitment_hash(original_reveal))
        )
        mutated_reveal = validate_reveal_payload(
            _reveal_payload(output_hashes=output_hashes, salt=salt)
        )

        assert not reveal_matches_commit(mutated_reveal, commit)

    def test_payloads_match_same_round_announcement(self):
        announcement = validate_round_announcement(_announcement_payload())
        commit = validate_commit_payload(_commit_payload())
        reveal = validate_reveal_payload(_reveal_payload())

        assert commit_matches_announcement(commit, announcement)
        assert reveal_matches_announcement(reveal, announcement)


class TestPayloadValidation:
    def test_hash_fields_must_be_lowercase_sha256_hex(self):
        with pytest.raises(CommitRevealValidationError, match="lowercase hex"):
            validate_commit_payload(_commit_payload(input_package_hash="A" * 64))

    def test_salt_must_be_64_lowercase_hex_characters(self):
        with pytest.raises(CommitRevealValidationError, match="salt"):
            validate_reveal_payload(_reveal_payload(salt="g" * 64))

    def test_output_hashes_reject_unknown_fields(self):
        payload = _output_hashes()
        payload["signed_validator_list_hash"] = "e" * 64

        with pytest.raises(CommitRevealValidationError, match="unknown fields"):
            validate_output_hashes(payload)

    def test_commit_payload_rejects_missing_fields(self):
        payload = _commit_payload()
        del payload["signature"]

        with pytest.raises(CommitRevealValidationError, match="missing fields"):
            validate_commit_payload(payload)

    def test_signature_field_is_validated_as_hex_but_not_cryptographically_verified(self):
        commit = validate_commit_payload(_commit_payload(signature="DEADBEEF"))
        reveal = validate_reveal_payload(_reveal_payload(signature="DEADBEEF"))

        assert commit.signature == "DEADBEEF"
        assert reveal.signature == "DEADBEEF"

    def test_network_rejects_whitespace_only_values(self):
        with pytest.raises(CommitRevealValidationError, match="network"):
            validate_commit_payload(_commit_payload(network=" "))

    def test_round_number_must_be_positive(self):
        with pytest.raises(CommitRevealValidationError, match="round_number"):
            validate_reveal_payload(_reveal_payload(round_number=0))

    def test_validator_master_key_must_have_expected_shape(self):
        with pytest.raises(CommitRevealValidationError, match="validator master key"):
            validate_commit_payload(_commit_payload(validator_master_key="not-a-key"))

    def test_input_package_cid_must_have_expected_shape(self):
        with pytest.raises(CommitRevealValidationError, match="CID"):
            validate_round_announcement(_announcement_payload(input_package_cid="not-a-cid"))


class TestSigningPayloads:
    def test_build_commit_signing_payload_does_not_require_signature(self):
        payload = build_commit_signing_payload(
            protocol_version=PROTOCOL_VERSION,
            network=NETWORK,
            round_number=ROUND_NUMBER,
            validator_master_key=VALIDATOR_MASTER_KEY,
            input_package_hash=INPUT_PACKAGE_HASH,
            commitment_hash=KNOWN_COMMITMENT_HASH,
        )

        assert payload["type"] == VALIDATOR_COMMIT_TYPE
        assert payload["commitment_hash"] == KNOWN_COMMITMENT_HASH
        assert "signature" not in payload

    def test_build_commit_signing_bytes_does_not_require_signature(self):
        payload = build_commit_signing_payload(
            protocol_version=PROTOCOL_VERSION,
            network=NETWORK,
            round_number=ROUND_NUMBER,
            validator_master_key=VALIDATOR_MASTER_KEY,
            input_package_hash=INPUT_PACKAGE_HASH,
            commitment_hash=KNOWN_COMMITMENT_HASH,
        )

        assert build_commit_signing_bytes(
            protocol_version=PROTOCOL_VERSION,
            network=NETWORK,
            round_number=ROUND_NUMBER,
            validator_master_key=VALIDATOR_MASTER_KEY,
            input_package_hash=INPUT_PACKAGE_HASH,
            commitment_hash=KNOWN_COMMITMENT_HASH,
        ) == canonical_json_bytes(payload)

    def test_build_reveal_signing_payload_does_not_require_signature(self):
        payload = build_reveal_signing_payload(
            protocol_version=PROTOCOL_VERSION,
            network=NETWORK,
            round_number=ROUND_NUMBER,
            validator_master_key=VALIDATOR_MASTER_KEY,
            input_package_hash=INPUT_PACKAGE_HASH,
            output_hashes=_output_hashes(),
            salt=SALT,
        )

        assert payload["type"] == VALIDATOR_REVEAL_TYPE
        assert payload["salt"] == SALT
        assert "signature" not in payload

    def test_build_reveal_signing_bytes_does_not_require_signature(self):
        payload = build_reveal_signing_payload(
            protocol_version=PROTOCOL_VERSION,
            network=NETWORK,
            round_number=ROUND_NUMBER,
            validator_master_key=VALIDATOR_MASTER_KEY,
            input_package_hash=INPUT_PACKAGE_HASH,
            output_hashes=_output_hashes(),
            salt=SALT,
        )

        assert build_reveal_signing_bytes(
            protocol_version=PROTOCOL_VERSION,
            network=NETWORK,
            round_number=ROUND_NUMBER,
            validator_master_key=VALIDATOR_MASTER_KEY,
            input_package_hash=INPUT_PACKAGE_HASH,
            output_hashes=_output_hashes(),
            salt=SALT,
        ) == canonical_json_bytes(payload)

    def test_commit_signing_payload_omits_signature(self):
        commit = validate_commit_payload(_commit_payload())

        payload = commit_signing_payload(commit)

        assert payload["type"] == VALIDATOR_COMMIT_TYPE
        assert payload["commitment_hash"] == KNOWN_COMMITMENT_HASH
        assert "signature" not in payload

    def test_commit_signing_bytes_are_canonical(self):
        commit = validate_commit_payload(_commit_payload())

        assert commit_signing_bytes(commit) == canonical_json_bytes(
            commit_signing_payload(commit)
        )

    def test_reveal_signing_payload_omits_signature(self):
        reveal = validate_reveal_payload(_reveal_payload())

        payload = reveal_signing_payload(reveal)

        assert payload["type"] == VALIDATOR_REVEAL_TYPE
        assert payload["salt"] == SALT
        assert "signature" not in payload

    def test_reveal_signing_bytes_are_canonical(self):
        reveal = validate_reveal_payload(_reveal_payload())

        assert reveal_signing_bytes(reveal) == canonical_json_bytes(
            reveal_signing_payload(reveal)
        )


class TestTiming:
    def test_commit_window_is_half_open(self):
        announcement = validate_round_announcement(_announcement_payload())

        assert not is_commit_within_window(
            announcement,
            COMMIT_OPENS_AT - timedelta(microseconds=1),
        )
        assert is_commit_within_window(announcement, COMMIT_OPENS_AT)
        assert is_commit_within_window(
            announcement,
            COMMIT_CLOSES_AT - timedelta(microseconds=1),
        )
        assert not is_commit_within_window(announcement, COMMIT_CLOSES_AT)

    def test_reveal_window_is_half_open(self):
        announcement = validate_round_announcement(_announcement_payload())

        assert not is_reveal_within_window(
            announcement,
            REVEAL_OPENS_AT - timedelta(microseconds=1),
        )
        assert is_reveal_within_window(announcement, REVEAL_OPENS_AT)
        assert is_reveal_within_window(
            announcement,
            REVEAL_CLOSES_AT - timedelta(microseconds=1),
        )
        assert not is_reveal_within_window(announcement, REVEAL_CLOSES_AT)

    def test_round_announcement_rejects_unordered_windows(self):
        with pytest.raises(CommitRevealValidationError, match="reveal_opens_at"):
            validate_round_announcement(
                _announcement_payload(
                    reveal_opens_at=(COMMIT_CLOSES_AT - timedelta(minutes=1)).isoformat()
                )
            )

    def test_naive_datetimes_are_rejected(self):
        with pytest.raises(CommitRevealValidationError, match="timezone"):
            validate_round_announcement(
                _announcement_payload(commit_opens_at="2026-05-25T00:05:00")
            )


class TestLedgerOrder:
    @dataclass(frozen=True)
    class Submission:
        label: str
        position: LedgerPosition

    def test_first_by_ledger_order_uses_ledger_then_transaction_index(self):
        submissions = [
            self.Submission("later_ledger", LedgerPosition(11, 0)),
            self.Submission("same_ledger_later_tx", LedgerPosition(10, 2)),
            self.Submission("first", LedgerPosition(10, 1)),
        ]

        first = first_by_ledger_order(submissions, lambda item: item.position)

        assert first is not None
        assert first.label == "first"

    def test_first_by_ledger_order_returns_none_for_empty_input(self):
        assert first_by_ledger_order([], lambda item: item.position) is None

    def test_ledger_position_rejects_negative_values(self):
        with pytest.raises(CommitRevealValidationError, match="ledger_index"):
            LedgerPosition(-1, 0)
