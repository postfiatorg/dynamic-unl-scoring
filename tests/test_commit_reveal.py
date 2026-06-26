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
    build_round_announcement,
    canonical_json_bytes,
    canonical_sha256,
    commit_matches_announcement,
    commit_signing_bytes,
    commit_signing_payload,
    compute_commitment_hash,
    compute_reveal_commitment_hash,
    compute_round_windows,
    first_by_ledger_order,
    is_commit_within_window,
    is_reveal_within_window,
    reveal_matches_announcement,
    reveal_matches_commit,
    reveal_signing_bytes,
    reveal_signing_payload,
    round_announcement_payload,
    validate_commit_payload,
    validate_output_hashes,
    validate_reveal_payload,
    validate_round_announcement,
    verify_commit_signature,
    verify_reveal_signature,
    verify_validator_master_signature,
)


INPUT_PACKAGE_HASH = "d" * 64
MODEL_RESPONSE_HASH = "a" * 64
VALIDATOR_SCORES_HASH = "b" * 64
SELECTED_UNL_HASH = "c" * 64
SALT = "1" * 64
SIGNATURE = "BADC0FFE"
VALIDATOR_MASTER_KEY = "nHU" + "A" * 30
OTHER_VALIDATOR_MASTER_KEY = "nHU" + "B" * 30
VALIDATOR_KEYS_FIXTURE_MESSAGE = b"data to sign"
VALIDATOR_KEYS_FIXTURE_MASTER_KEY = (
    "nHBiD11VatsZ233gQ4QR2gJVZ1sP6q45AMXuXzsdTRqSDVispdcC"
)
VALIDATOR_KEYS_FIXTURE_SIGNATURE = (
    "2EE541D6825791BF5454C571D2B363EAB3F01C73159B1F"
    "237AC6D38663A82B9D5EAD262D5F776B916E68247A1F082090F3BAE7ABC939"
    "C8F29B0DC759FD712300"
)
VALIDATOR_KEYS_FIXTURE_COMMIT_SIGNATURE = (
    "D4544496F2A26E82C7DC67A62232DEF69E1E6EBFB31DA0B2D313EEF87F31FD4C"
    "8ABCF7D818F51047FB2933C429B1DB8E5F75011D9594B8F7C947E07306677C05"
)
VALIDATOR_KEYS_FIXTURE_REVEAL_SIGNATURE = (
    "DF3B64AE67FB8285888544D2B1FD097C2AB6FAD8ADF148288AEFC62945E017DA"
    "1C6A295192EF718649028E0BE9870DC79135D6D2BC4EC7DF7FD3CF390AD32505"
)
OTHER_VALIDATOR_KEYS_FIXTURE_MASTER_KEY = (
    "nHU8uswopn4UZc5JwMY5eeZRrSuREMx4eKaRfgFcLpEmJJt9aPmT"
)
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
        "protocol_version": PROTOCOL_VERSION,
        "network": NETWORK,
        "round_number": ROUND_NUMBER,
        "input_package_cid": INPUT_PACKAGE_CID,
        "input_package_hash": INPUT_PACKAGE_HASH,
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


def _signed_commit_payload(**overrides) -> dict:
    values = {
        "protocol_version": PROTOCOL_VERSION,
        "network": NETWORK,
        "round_number": ROUND_NUMBER,
        "validator_master_key": VALIDATOR_KEYS_FIXTURE_MASTER_KEY,
        "input_package_hash": INPUT_PACKAGE_HASH,
        "commitment_hash": compute_commitment_hash(
            protocol_version=PROTOCOL_VERSION,
            network=NETWORK,
            round_number=ROUND_NUMBER,
            validator_master_key=VALIDATOR_KEYS_FIXTURE_MASTER_KEY,
            input_package_hash=INPUT_PACKAGE_HASH,
            output_hashes=_output_hashes(),
            salt=SALT,
        ),
    }
    values.update(overrides)
    return build_commit_payload(
        **values,
        signature=VALIDATOR_KEYS_FIXTURE_COMMIT_SIGNATURE,
    )


def _signed_reveal_payload(**overrides) -> dict:
    values = {
        "protocol_version": PROTOCOL_VERSION,
        "network": NETWORK,
        "round_number": ROUND_NUMBER,
        "validator_master_key": VALIDATOR_KEYS_FIXTURE_MASTER_KEY,
        "input_package_hash": INPUT_PACKAGE_HASH,
        "output_hashes": _output_hashes(),
        "salt": SALT,
    }
    values.update(overrides)
    return build_reveal_payload(
        **values,
        signature=VALIDATOR_KEYS_FIXTURE_REVEAL_SIGNATURE,
    )


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


class TestSignatureVerification:
    def test_known_validator_keys_tool_fixture_verifies(self):
        assert verify_validator_master_signature(
            validator_master_key=VALIDATOR_KEYS_FIXTURE_MASTER_KEY,
            message=VALIDATOR_KEYS_FIXTURE_MESSAGE,
            signature=VALIDATOR_KEYS_FIXTURE_SIGNATURE,
        )

    def test_known_validator_keys_tool_fixture_rejects_tampered_message(self):
        assert not verify_validator_master_signature(
            validator_master_key=VALIDATOR_KEYS_FIXTURE_MASTER_KEY,
            message=b"data to sign!",
            signature=VALIDATOR_KEYS_FIXTURE_SIGNATURE,
        )

    def test_commit_signature_verifies_against_canonical_payload_bytes(self):
        commit = validate_commit_payload(_signed_commit_payload())

        assert verify_commit_signature(commit)

    def test_reveal_signature_verifies_against_canonical_payload_bytes(self):
        reveal = validate_reveal_payload(_signed_reveal_payload())

        assert verify_reveal_signature(reveal)

    def test_commit_signature_rejects_wrong_validator_master_key(self):
        payload = _signed_commit_payload()
        payload["validator_master_key"] = OTHER_VALIDATOR_KEYS_FIXTURE_MASTER_KEY

        assert not verify_commit_signature(payload)

    def test_reveal_signature_rejects_tampered_payload(self):
        payload = _signed_reveal_payload()
        payload["network"] = "devnet"

        assert not verify_reveal_signature(payload)

    def test_malformed_signature_rejected_before_verification(self):
        payload = _signed_commit_payload()
        payload["signature"] = "not-hex"

        with pytest.raises(CommitRevealValidationError, match="signature"):
            verify_commit_signature(payload)

    def test_malformed_signature_bytes_do_not_verify(self):
        assert not verify_validator_master_signature(
            validator_master_key=VALIDATOR_KEYS_FIXTURE_MASTER_KEY,
            message=VALIDATOR_KEYS_FIXTURE_MESSAGE,
            signature="DEADBEEF",
        )

    def test_malformed_validator_master_key_rejected_before_verification(self):
        with pytest.raises(
            CommitRevealValidationError,
            match="valid XRPL node public key",
        ):
            verify_validator_master_signature(
                validator_master_key=VALIDATOR_MASTER_KEY,
                message=VALIDATOR_KEYS_FIXTURE_MESSAGE,
                signature=VALIDATOR_KEYS_FIXTURE_SIGNATURE,
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


class TestRoundAnnouncementBuilder:
    def test_payload_has_exact_nine_fields_without_type(self):
        announcement = validate_round_announcement(_announcement_payload())
        payload = round_announcement_payload(announcement)

        assert set(payload.keys()) == {
            "protocol_version",
            "network",
            "round_number",
            "input_package_hash",
            "input_package_cid",
            "commit_opens_at",
            "commit_closes_at",
            "reveal_opens_at",
            "reveal_closes_at",
        }
        assert "type" not in payload
        assert "round_kind" not in payload
        assert "input_frozen_at" not in payload

    def test_payload_round_trips_through_validation(self):
        announcement = validate_round_announcement(_announcement_payload())
        payload = round_announcement_payload(announcement)

        assert validate_round_announcement(payload) == announcement

    def test_canonical_bytes_are_stable_and_field_order_independent(self):
        announcement = validate_round_announcement(_announcement_payload())
        payload = round_announcement_payload(announcement)
        reordered = dict(reversed(list(payload.items())))

        assert canonical_json_bytes(payload) == canonical_json_bytes(reordered)

    def test_validate_rejects_dropped_and_extra_fields(self):
        for field, value in (
            ("type", ROUND_ANNOUNCEMENT_TYPE),
            ("round_kind", "normal"),
            ("input_frozen_at", INPUT_FROZEN_AT.isoformat()),
        ):
            with pytest.raises(CommitRevealValidationError, match="unknown fields"):
                validate_round_announcement(_announcement_payload(**{field: value}))

    def test_build_round_announcement_enforces_window_ordering(self):
        with pytest.raises(CommitRevealValidationError, match="reveal_opens_at"):
            build_round_announcement(
                network=NETWORK,
                round_number=ROUND_NUMBER,
                input_package_cid=INPUT_PACKAGE_CID,
                input_package_hash=INPUT_PACKAGE_HASH,
                commit_opens_at=COMMIT_OPENS_AT,
                commit_closes_at=COMMIT_CLOSES_AT,
                reveal_opens_at=COMMIT_CLOSES_AT - timedelta(minutes=1),
                reveal_closes_at=REVEAL_CLOSES_AT,
            )


class TestComputeRoundWindows:
    def test_anchors_at_emission_and_orders_windows(self):
        anchor = INPUT_FROZEN_AT + timedelta(minutes=10)

        commit_opens, commit_closes, reveal_opens, reveal_closes = compute_round_windows(
            input_frozen_at=INPUT_FROZEN_AT,
            anchor=anchor,
            commit_window=timedelta(minutes=30),
            reveal_window=timedelta(minutes=30),
            reveal_gap=timedelta(minutes=5),
        )

        assert commit_opens == anchor
        assert commit_closes == anchor + timedelta(minutes=30)
        assert reveal_opens == commit_closes + timedelta(minutes=5)
        assert reveal_closes == reveal_opens + timedelta(minutes=30)

    def test_commit_window_never_opens_before_input_frozen_at(self):
        anchor = INPUT_FROZEN_AT - timedelta(minutes=10)

        commit_opens, *_ = compute_round_windows(
            input_frozen_at=INPUT_FROZEN_AT,
            anchor=anchor,
            commit_window=timedelta(minutes=30),
            reveal_window=timedelta(minutes=30),
        )

        assert commit_opens == INPUT_FROZEN_AT

    def test_rejects_non_positive_window(self):
        with pytest.raises(CommitRevealValidationError, match="commit_window"):
            compute_round_windows(
                input_frozen_at=INPUT_FROZEN_AT,
                anchor=INPUT_FROZEN_AT,
                commit_window=timedelta(0),
                reveal_window=timedelta(minutes=30),
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
