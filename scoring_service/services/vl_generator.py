"""Validator List generator — signs and assembles VL JSON documents.

Ports the signing logic from postfiatd/scripts/generate_vl.py into the
scoring service. The VL is the cryptographically signed document that
postfiatd nodes fetch to determine which validators to trust.

VL format (v2):
    {
        "public_key": "<publisher master key hex>",
        "manifest": "<publisher manifest base64>",
        "blobs_v2": [{"blob": "<inner JSON base64>", "signature": "<DER hex>"}],
        "version": 2
    }

Inner blob fields:
    sequence    — monotonically increasing; postfiatd rejects any blob whose
                  sequence is not strictly greater than the currently applied one
    effective   — XRPL ripple-epoch seconds at which this blob becomes active.
                  postfiatd holds the blob in 'remaining' until closeTime >= effective,
                  then promotes it to 'current' on the next consensus tick. Publishing
                  with a future 'effective' lets all validators cache the pending blob
                  and transition in unison instead of at independent poll intervals.
    expiration  — XRPL ripple-epoch seconds at which this blob stops being trusted
    validators  — ordered list of {validation_public_key, manifest} entries

Signing process (must match postfiatd's C++ verifier):
    1. Build inner blob as compact JSON (no whitespace)
    2. Sign the raw JSON bytes with SHA-512-Half + secp256k1/Ed25519
    3. Base64-encode the same raw bytes for the blob field
    4. Hex-encode the DER signature
"""

import base64
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from ecdsa import SECP256k1, SigningKey, util as ecdsa_util

from scoring_service.config import settings

logger = logging.getLogger(__name__)

RIPPLE_EPOCH = 946684800  # Jan 1, 2000 00:00:00 UTC


def sha512_half(data: bytes) -> bytes:
    """XRPL SHA-512-Half: first 32 bytes of SHA-512."""
    return hashlib.sha512(data).digest()[:32]


def to_ripple_epoch(dt: datetime) -> int:
    """Convert a datetime to XRPL epoch (seconds since Jan 1, 2000 UTC)."""
    unix_ts = int(dt.timestamp())
    return unix_ts - RIPPLE_EPOCH


def from_ripple_epoch(ripple_ts: int) -> datetime:
    """Convert XRPL epoch timestamp to a UTC datetime."""
    unix_ts = ripple_ts + RIPPLE_EPOCH
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc)


def clean_token(token_str: str) -> str:
    """Strip [validator_token] header, whitespace, and newlines."""
    lines = token_str.strip().splitlines()
    return "".join(
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("[")
    )


def decode_token(token_str: str) -> dict:
    """Decode a publisher token (base64 JSON with manifest + signing key).

    Returns:
        Dict with keys: 'manifest' (base64 str), 'validation_secret_key' (hex str).

    Raises:
        ValueError: If the token cannot be decoded.
    """
    cleaned = clean_token(token_str)
    try:
        return json.loads(base64.b64decode(cleaned))
    except Exception as exc:
        raise ValueError(f"Failed to decode publisher token: {exc}") from exc


def parse_manifest(manifest_b64: str) -> dict:
    """Parse an XRPL manifest (STObject binary) to extract key fields.

    Returns:
        Dict with:
            - master_public_key: hex 33-byte key (sfPublicKey)
            - signing_public_key: hex 33-byte ephemeral key (sfSigningPubKey)
            - signing_key_type: 'ed25519' or 'secp256k1'

    Raises:
        ValueError: If required fields cannot be extracted.
    """
    data = base64.b64decode(manifest_b64)
    result = {}
    i = 0

    while i < len(data):
        byte = data[i]
        i += 1

        type_code = (byte >> 4) & 0x0F
        field_code = byte & 0x0F

        if type_code == 0:
            if i >= len(data):
                break
            type_code = data[i]
            i += 1
        if field_code == 0:
            if i >= len(data):
                break
            field_code = data[i]
            i += 1

        if type_code == 1:  # uint16
            i += 2
        elif type_code == 2:  # uint32
            i += 4
        elif type_code == 7:  # blob (variable length)
            if i >= len(data):
                break
            length = data[i]
            i += 1
            if length > 192:
                if i >= len(data):
                    break
                length = 193 + ((length - 193) * 256) + data[i]
                i += 1

            blob = data[i : i + length]

            if field_code == 1:  # sfPublicKey (master public key)
                result["master_public_key"] = blob.hex().upper()
            elif field_code == 3:  # sfSigningPubKey (ephemeral signing key)
                result["signing_public_key"] = blob.hex().upper()
                if blob[0] == 0xED:
                    result["signing_key_type"] = "ed25519"
                elif blob[0] in (0x02, 0x03):
                    result["signing_key_type"] = "secp256k1"
                else:
                    raise ValueError(f"Unknown signing key type prefix: 0x{blob[0]:02X}")

            i += length
        else:
            break

    if "master_public_key" not in result:
        raise ValueError("Could not extract master public key from manifest")

    return result


def sign_blob(data: bytes, secret_key_hex: str, key_type: str) -> str:
    """Sign raw blob bytes with secp256k1 ECDSA using SHA-512-Half digest.

    Returns hex-encoded DER signature with canonical low-S value.

    Raises:
        ValueError: If the key type is not secp256k1.
    """
    if key_type != "secp256k1":
        raise ValueError(f"Unsupported signing key type: '{key_type}'")

    digest = sha512_half(data)
    sk = SigningKey.from_string(bytes.fromhex(secret_key_hex), curve=SECP256k1)
    sig = sk.sign_digest(digest, sigencode=ecdsa_util.sigencode_der_canonize)
    return sig.hex().upper()


def generate_vl(
    validator_keys: list[str],
    manifests: dict[str, str],
    sequence: int,
    publisher_token: str | None = None,
    expiration_days: int | None = None,
    effective_lookahead_hours: float | None = None,
) -> dict:
    """Generate a signed Validator List (v2 format).

    Args:
        validator_keys: Ordered list of validator master keys (base58) for the UNL.
        manifests: Dict mapping master_key → base64 manifest blob.
        sequence: VL sequence number (must always increment).
        publisher_token: Base64 publisher token. Defaults to settings.vl_publisher_token.
        expiration_days: Days until expiration. Defaults to settings.vl_expiration_days.
        effective_lookahead_hours: Hours between signing time and blob activation.
            The inner blob's 'effective' field is set to `now + lookahead`. 0 means
            the blob activates immediately on fetch (current ripple-epoch second).
            Defaults to settings.vl_effective_lookahead_hours.

    Returns:
        Complete VL JSON document (dict) ready for serialization.

    Raises:
        ValueError: If publisher token is missing/invalid, or a validator
            has no manifest.
    """
    publisher_token = publisher_token or settings.vl_publisher_token
    expiration_days = expiration_days if expiration_days is not None else settings.vl_expiration_days
    effective_lookahead_hours = (
        effective_lookahead_hours
        if effective_lookahead_hours is not None
        else settings.vl_effective_lookahead_hours
    )

    if not publisher_token:
        raise ValueError("VL_PUBLISHER_TOKEN is required for VL generation")

    token_data = decode_token(publisher_token)
    publisher_manifest_b64 = token_data["manifest"]
    publisher_secret = token_data["validation_secret_key"]
    publisher_fields = parse_manifest(publisher_manifest_b64)
    key_type = publisher_fields.get("signing_key_type")

    if not key_type:
        raise ValueError("Could not determine signing key type from publisher manifest")

    validators = []
    for key in validator_keys:
        manifest = manifests.get(key)
        if not manifest:
            raise ValueError(f"Missing manifest for validator {key}")

        manifest_fields = parse_manifest(manifest)
        validators.append({
            "validation_public_key": manifest_fields["master_public_key"],
            "manifest": manifest,
        })

    now = datetime.now(timezone.utc)
    effective = to_ripple_epoch(now + timedelta(hours=effective_lookahead_hours))
    expiration = to_ripple_epoch(now + timedelta(days=expiration_days))

    blob_obj = {
        "sequence": sequence,
        "effective": effective,
        "expiration": expiration,
        "validators": validators,
    }

    blob_json = json.dumps(blob_obj, separators=(",", ":"))
    blob_bytes = blob_json.encode("utf-8")

    signature = sign_blob(blob_bytes, publisher_secret, key_type)
    blob_b64 = base64.b64encode(blob_bytes).decode("ascii")

    vl = {
        "public_key": publisher_fields["master_public_key"],
        "manifest": publisher_manifest_b64,
        "blobs_v2": [{"signature": signature, "blob": blob_b64}],
        "version": 2,
    }

    logger.info(
        "VL generated: sequence=%d, validators=%d, effective=%s, expires=%s, key_type=%s",
        sequence,
        len(validators),
        from_ripple_epoch(effective).strftime("%Y-%m-%d %H:%M:%SZ"),
        from_ripple_epoch(expiration).strftime("%Y-%m-%d"),
        key_type,
    )

    return vl
