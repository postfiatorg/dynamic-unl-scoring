"""Tests for the Validator List generator — signing, encoding, and assembly."""

import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from ecdsa import SECP256k1, SigningKey, VerifyingKey, util as ecdsa_util

from scoring_service.services.vl_generator import (
    RIPPLE_EPOCH,
    clean_token,
    decode_token,
    from_ripple_epoch,
    generate_vl,
    parse_manifest,
    sha512_half,
    sign_blob,
    to_ripple_epoch,
)


# ---------------------------------------------------------------------------
# Test fixtures — self-consistent publisher key pair
# ---------------------------------------------------------------------------

PUBLISHER_TOKEN = (
    "eyJtYW5pZmVzdCI6ICJKQUFBQUFGeEllMjBhZGEvWDhKUmNYazdIRm5rT2h2S2pSekxp"
    "MzJKNzJRbUk1ejV2TXBHY25NaEE0TFdKaDBlRWR3YW8zREN4NDJCLys0YWt6TlhNaCto"
    "L2ZCaVhuSElBaEMzIiwgInZhbGlkYXRpb25fc2VjcmV0X2tleSI6ICI2OWRmYjBmZDli"
    "YjM2MWU2OTMxNmUyYjEwMTA1NTc3NmMxNDg2NzgzYmY0MDdmMjhiODhlODE3MjhiYTBk"
    "MTU5In0="
)
PUBLISHER_MASTER_HEX = "EDB469D6BF5FC25171793B1C59E43A1BCA8D1CCB8B7D89EF6426239CF9BCCA4672"
PUBLISHER_SIGNING_HEX = "0382D6261D1E11DC1AA370C2C78D81FFEE1A933357321FA1FDF0625E71C80210B7"
PUBLISHER_SECRET_HEX = "69dfb0fd9bb361e69316e2b101055776c1486783bf407f28b88e81728ba0d159"
PUBLISHER_MANIFEST_B64 = (
    "JAAAAAFxIe20ada/X8JRcXk7HFnkOhvKjRzLi32J72QmI5z5vMpGcnMh"
    "A4LWJh0eEdwao3DCx42B/+4akzNXMh+h/fBiXnHIAhC3"
)


def _build_validator_manifest(master_hex: str, signing_hex: str) -> str:
    """Build a minimal manifest blob for testing."""
    master_bytes = bytes.fromhex(master_hex)
    signing_bytes = bytes.fromhex(signing_hex)
    seq_field = bytes([0x24]) + (1).to_bytes(4, "big")
    master_field = bytes([0x71]) + bytes([len(master_bytes)]) + master_bytes
    signing_field = bytes([0x73]) + bytes([len(signing_bytes)]) + signing_bytes
    return base64.b64encode(seq_field + master_field + signing_field).decode()


VALIDATOR_MASTER_HEX = "ED" + "AA" * 32
VALIDATOR_SIGNING_HEX = "02" + "BB" * 32
VALIDATOR_MANIFEST_B64 = _build_validator_manifest(VALIDATOR_MASTER_HEX, VALIDATOR_SIGNING_HEX)

VALIDATOR2_MASTER_HEX = "ED" + "CC" * 32
VALIDATOR2_SIGNING_HEX = "03" + "DD" * 32
VALIDATOR2_MANIFEST_B64 = _build_validator_manifest(VALIDATOR2_MASTER_HEX, VALIDATOR2_SIGNING_HEX)


# ---------------------------------------------------------------------------
# SHA-512-Half
# ---------------------------------------------------------------------------


class TestSha512Half:
    def test_returns_32_bytes(self):
        result = sha512_half(b"test data")
        assert len(result) == 32

    def test_deterministic(self):
        assert sha512_half(b"hello") == sha512_half(b"hello")

    def test_different_input_different_output(self):
        assert sha512_half(b"a") != sha512_half(b"b")


# ---------------------------------------------------------------------------
# Ripple epoch conversions
# ---------------------------------------------------------------------------


class TestRippleEpoch:
    def test_to_ripple_epoch(self):
        dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
        result = to_ripple_epoch(dt)
        expected = int(dt.timestamp()) - RIPPLE_EPOCH
        assert result == expected

    def test_from_ripple_epoch_roundtrip(self):
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        ripple_ts = to_ripple_epoch(dt)
        roundtripped = from_ripple_epoch(ripple_ts)
        assert roundtripped == dt

    def test_ripple_epoch_is_jan_2000(self):
        dt = datetime(2000, 1, 1, tzinfo=timezone.utc)
        assert to_ripple_epoch(dt) == 0


# ---------------------------------------------------------------------------
# Token decoding
# ---------------------------------------------------------------------------


class TestCleanToken:
    def test_strips_header_and_whitespace(self):
        raw = "[validator_token]\n  ABC123\n  DEF456\n"
        assert clean_token(raw) == "ABC123DEF456"

    def test_handles_plain_base64(self):
        assert clean_token("  ABC123  ") == "ABC123"


class TestDecodeToken:
    def test_decodes_valid_token(self):
        result = decode_token(PUBLISHER_TOKEN)
        assert "manifest" in result
        assert "validation_secret_key" in result

    def test_raises_on_invalid_base64(self):
        with pytest.raises(ValueError, match="Failed to decode"):
            decode_token("not-valid-base64!!!")

    def test_extracts_correct_secret_key(self):
        result = decode_token(PUBLISHER_TOKEN)
        assert result["validation_secret_key"] == PUBLISHER_SECRET_HEX


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


class TestParseManifest:
    def test_extracts_master_public_key(self):
        result = parse_manifest(PUBLISHER_MANIFEST_B64)
        assert result["master_public_key"] == PUBLISHER_MASTER_HEX

    def test_extracts_signing_public_key(self):
        result = parse_manifest(PUBLISHER_MANIFEST_B64)
        assert result["signing_public_key"] == PUBLISHER_SIGNING_HEX

    def test_detects_secp256k1_key_type(self):
        result = parse_manifest(PUBLISHER_MANIFEST_B64)
        assert result["signing_key_type"] == "secp256k1"

    def test_detects_ed25519_key_type(self):
        # Build a manifest with an Ed25519 signing key (0xED prefix)
        ed_signing = "ED" + "FF" * 32
        manifest = _build_validator_manifest(PUBLISHER_MASTER_HEX, ed_signing)
        result = parse_manifest(manifest)
        assert result["signing_key_type"] == "ed25519"

    def test_raises_on_missing_master_key(self):
        # Empty manifest — no fields
        empty = base64.b64encode(b"").decode()
        with pytest.raises(ValueError, match="Could not extract master public key"):
            parse_manifest(empty)

    def test_parses_validator_manifest(self):
        result = parse_manifest(VALIDATOR_MANIFEST_B64)
        assert result["master_public_key"] == VALIDATOR_MASTER_HEX


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


def _verify_signature(data: bytes, sig_hex: str) -> bool:
    """Verify a secp256k1 signature against the test publisher key."""
    sig_bytes = bytes.fromhex(sig_hex)
    digest = sha512_half(data)
    vk = VerifyingKey.from_der(
        SigningKey.from_string(
            bytes.fromhex(PUBLISHER_SECRET_HEX), curve=SECP256k1
        ).get_verifying_key().to_der()
    )
    return vk.verify_digest(sig_bytes, digest, sigdecode=ecdsa_util.sigdecode_der)


class TestSignBlob:
    def test_produces_valid_signature(self):
        data = b'{"sequence":1,"expiration":867715200,"validators":[]}'
        sig_hex = sign_blob(data, PUBLISHER_SECRET_HEX, "secp256k1")
        assert _verify_signature(data, sig_hex)

    def test_both_signatures_verify_for_same_input(self):
        data = b"test payload"
        sig1 = sign_blob(data, PUBLISHER_SECRET_HEX, "secp256k1")
        sig2 = sign_blob(data, PUBLISHER_SECRET_HEX, "secp256k1")
        assert _verify_signature(data, sig1)
        assert _verify_signature(data, sig2)

    def test_different_data_different_signature(self):
        sig1 = sign_blob(b"data_a", PUBLISHER_SECRET_HEX, "secp256k1")
        sig2 = sign_blob(b"data_b", PUBLISHER_SECRET_HEX, "secp256k1")
        assert sig1 != sig2

    def test_raises_on_unsupported_key_type(self):
        with pytest.raises(ValueError, match="Unsupported signing key type"):
            sign_blob(b"test", PUBLISHER_SECRET_HEX, "ed25519")


# ---------------------------------------------------------------------------
# VL generation (end-to-end)
# ---------------------------------------------------------------------------


class TestGenerateVL:
    def test_produces_valid_v2_structure(self):
        vl = generate_vl(
            validator_keys=["key_a"],
            manifests={"key_a": VALIDATOR_MANIFEST_B64},
            sequence=1,
            publisher_token=PUBLISHER_TOKEN,
            expiration_days=500,
        )
        assert vl["version"] == 2
        assert "public_key" in vl
        assert "manifest" in vl
        assert "blobs_v2" in vl
        assert len(vl["blobs_v2"]) == 1
        assert "blob" in vl["blobs_v2"][0]
        assert "signature" in vl["blobs_v2"][0]

    def test_blob_contains_correct_sequence(self):
        vl = generate_vl(
            validator_keys=["key_a"],
            manifests={"key_a": VALIDATOR_MANIFEST_B64},
            sequence=42,
            publisher_token=PUBLISHER_TOKEN,
        )
        blob = json.loads(base64.b64decode(vl["blobs_v2"][0]["blob"]))
        assert blob["sequence"] == 42

    def test_blob_contains_validators(self):
        vl = generate_vl(
            validator_keys=["key_a", "key_b"],
            manifests={
                "key_a": VALIDATOR_MANIFEST_B64,
                "key_b": VALIDATOR2_MANIFEST_B64,
            },
            sequence=1,
            publisher_token=PUBLISHER_TOKEN,
        )
        blob = json.loads(base64.b64decode(vl["blobs_v2"][0]["blob"]))
        assert len(blob["validators"]) == 2
        assert blob["validators"][0]["validation_public_key"] == VALIDATOR_MASTER_HEX
        assert blob["validators"][1]["validation_public_key"] == VALIDATOR2_MASTER_HEX

    def test_validator_entries_include_manifest(self):
        vl = generate_vl(
            validator_keys=["key_a"],
            manifests={"key_a": VALIDATOR_MANIFEST_B64},
            sequence=1,
            publisher_token=PUBLISHER_TOKEN,
        )
        blob = json.loads(base64.b64decode(vl["blobs_v2"][0]["blob"]))
        assert blob["validators"][0]["manifest"] == VALIDATOR_MANIFEST_B64

    def test_signature_verifies(self):
        vl = generate_vl(
            validator_keys=["key_a"],
            manifests={"key_a": VALIDATOR_MANIFEST_B64},
            sequence=1,
            publisher_token=PUBLISHER_TOKEN,
        )
        blob_b64 = vl["blobs_v2"][0]["blob"]
        sig_hex = vl["blobs_v2"][0]["signature"]
        assert _verify_signature(base64.b64decode(blob_b64), sig_hex)

    def test_publisher_key_matches_manifest(self):
        vl = generate_vl(
            validator_keys=["key_a"],
            manifests={"key_a": VALIDATOR_MANIFEST_B64},
            sequence=1,
            publisher_token=PUBLISHER_TOKEN,
        )
        assert vl["public_key"] == PUBLISHER_MASTER_HEX
        assert vl["manifest"] == PUBLISHER_MANIFEST_B64

    def test_expiration_in_future(self):
        vl = generate_vl(
            validator_keys=["key_a"],
            manifests={"key_a": VALIDATOR_MANIFEST_B64},
            sequence=1,
            publisher_token=PUBLISHER_TOKEN,
            expiration_days=500,
        )
        blob = json.loads(base64.b64decode(vl["blobs_v2"][0]["blob"]))
        expiration_dt = from_ripple_epoch(blob["expiration"])
        now = datetime.now(timezone.utc)
        assert expiration_dt > now + timedelta(days=499)
        assert expiration_dt < now + timedelta(days=501)

    def test_blob_is_compact_json(self):
        vl = generate_vl(
            validator_keys=["key_a"],
            manifests={"key_a": VALIDATOR_MANIFEST_B64},
            sequence=1,
            publisher_token=PUBLISHER_TOKEN,
        )
        blob_json = base64.b64decode(vl["blobs_v2"][0]["blob"]).decode("utf-8")
        assert " " not in blob_json
        assert "\n" not in blob_json

    def test_raises_on_missing_publisher_token(self):
        with patch("scoring_service.services.vl_generator.settings") as mock:
            mock.vl_publisher_token = ""
            mock.vl_expiration_days = 500
            with pytest.raises(ValueError, match="VL_PUBLISHER_TOKEN is required"):
                generate_vl(
                    validator_keys=["key_a"],
                    manifests={"key_a": VALIDATOR_MANIFEST_B64},
                    sequence=1,
                )

    def test_raises_on_missing_validator_manifest(self):
        with pytest.raises(ValueError, match="Missing manifest for validator"):
            generate_vl(
                validator_keys=["key_a", "key_missing"],
                manifests={"key_a": VALIDATOR_MANIFEST_B64},
                sequence=1,
                publisher_token=PUBLISHER_TOKEN,
            )

    def test_empty_validator_list(self):
        vl = generate_vl(
            validator_keys=[],
            manifests={},
            sequence=1,
            publisher_token=PUBLISHER_TOKEN,
        )
        blob = json.loads(base64.b64decode(vl["blobs_v2"][0]["blob"]))
        assert blob["validators"] == []
        assert blob["sequence"] == 1
