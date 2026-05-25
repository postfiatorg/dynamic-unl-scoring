"""Dynamic UNL commit-reveal protocol helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, TypeVar


PROTOCOL_VERSION = 1
PROTOCOL_VERSION_SUFFIX = f"v{PROTOCOL_VERSION}"

ROUND_ANNOUNCEMENT_TYPE = f"pf_dynamic_unl_round_announcement_{PROTOCOL_VERSION_SUFFIX}"
VALIDATOR_COMMIT_TYPE = f"pf_dynamic_unl_validator_commit_{PROTOCOL_VERSION_SUFFIX}"
VALIDATOR_REVEAL_TYPE = f"pf_dynamic_unl_validator_reveal_{PROTOCOL_VERSION_SUFFIX}"
COMMITMENT_PREIMAGE_TYPE = f"pf_dynamic_unl_commitment_preimage_{PROTOCOL_VERSION_SUFFIX}"

ROUND_KIND_NORMAL = "normal"

MODEL_RESPONSE_HASH = "model_response_hash"
VALIDATOR_SCORES_HASH = "validator_scores_hash"
SELECTED_UNL_HASH = "selected_unl_hash"
OUTPUT_HASH_FIELDS = (
    MODEL_RESPONSE_HASH,
    VALIDATOR_SCORES_HASH,
    SELECTED_UNL_HASH,
)

SHA256_HEX_LENGTH = 64
SALT_HEX_LENGTH = 64

_LOWER_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_CID_RE = re.compile(r"^(Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{20,})$")
_VALIDATOR_MASTER_KEY_RE = re.compile(r"^nHU[1-9A-HJ-NP-Za-km-z]{20,}$")

T = TypeVar("T")


class CommitRevealValidationError(ValueError):
    """Raised when a commit-reveal protocol payload is malformed."""


@dataclass(frozen=True)
class OutputHashes:
    model_response_hash: str
    validator_scores_hash: str
    selected_unl_hash: str

    def as_dict(self) -> dict[str, str]:
        return {
            MODEL_RESPONSE_HASH: self.model_response_hash,
            VALIDATOR_SCORES_HASH: self.validator_scores_hash,
            SELECTED_UNL_HASH: self.selected_unl_hash,
        }


@dataclass(frozen=True)
class RoundAnnouncement:
    protocol_version: int
    network: str
    round_number: int
    round_kind: str
    input_package_cid: str
    input_package_hash: str
    input_frozen_at: datetime
    commit_opens_at: datetime
    commit_closes_at: datetime
    reveal_opens_at: datetime
    reveal_closes_at: datetime


@dataclass(frozen=True)
class CommitPayload:
    protocol_version: int
    network: str
    round_number: int
    validator_master_key: str
    input_package_hash: str
    commitment_hash: str
    signature: str

    @property
    def binding_key(self) -> tuple[int, str, int, str, str]:
        return (
            self.protocol_version,
            self.network,
            self.round_number,
            self.input_package_hash,
            self.validator_master_key,
        )

    def as_dict(self) -> dict[str, Any]:
        payload = self.signing_payload()
        payload["signature"] = self.signature
        return payload

    def signing_payload(self) -> dict[str, Any]:
        return {
            "type": VALIDATOR_COMMIT_TYPE,
            "protocol_version": self.protocol_version,
            "network": self.network,
            "round_number": self.round_number,
            "validator_master_key": self.validator_master_key,
            "input_package_hash": self.input_package_hash,
            "commitment_hash": self.commitment_hash,
        }

    def signing_bytes(self) -> bytes:
        return canonical_json_bytes(self.signing_payload())


@dataclass(frozen=True)
class RevealPayload:
    protocol_version: int
    network: str
    round_number: int
    validator_master_key: str
    input_package_hash: str
    output_hashes: OutputHashes
    salt: str
    signature: str

    @property
    def binding_key(self) -> tuple[int, str, int, str, str]:
        return (
            self.protocol_version,
            self.network,
            self.round_number,
            self.input_package_hash,
            self.validator_master_key,
        )

    def as_dict(self) -> dict[str, Any]:
        payload = self.signing_payload()
        payload["signature"] = self.signature
        return payload

    def signing_payload(self) -> dict[str, Any]:
        return {
            "type": VALIDATOR_REVEAL_TYPE,
            "protocol_version": self.protocol_version,
            "network": self.network,
            "round_number": self.round_number,
            "validator_master_key": self.validator_master_key,
            "input_package_hash": self.input_package_hash,
            "output_hashes": self.output_hashes.as_dict(),
            "salt": self.salt,
        }

    def signing_bytes(self) -> bytes:
        return canonical_json_bytes(self.signing_payload())


@dataclass(frozen=True, order=True)
class LedgerPosition:
    ledger_index: int
    transaction_index: int

    def __post_init__(self) -> None:
        _require_int("ledger_index", self.ledger_index, min_value=0)
        _require_int("transaction_index", self.transaction_index, min_value=0)


def canonical_json_bytes(data: Mapping[str, Any]) -> bytes:
    """Return protocol canonical JSON bytes for one JSON object."""
    if not isinstance(data, Mapping):
        raise CommitRevealValidationError("canonical payload must be a JSON object")
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return canonical.encode("utf-8")


def canonical_sha256(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()


def is_sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and bool(_LOWER_SHA256_RE.fullmatch(value))


def is_salt_hex(value: Any) -> bool:
    return isinstance(value, str) and bool(_LOWER_SHA256_RE.fullmatch(value))


def build_commitment_preimage(
    *,
    protocol_version: int,
    network: str,
    round_number: int,
    validator_master_key: str,
    input_package_hash: str,
    output_hashes: OutputHashes | Mapping[str, Any],
    salt: str,
) -> dict[str, Any]:
    """Build the exact hash preimage used for `commitment_hash`."""
    output_hashes_obj = _coerce_output_hashes(output_hashes)
    _require_protocol_version(protocol_version)
    network = _require_network(network)
    round_number = _require_round_number(round_number)
    validator_master_key = _require_validator_master_key(
        "validator_master_key",
        validator_master_key,
    )
    input_package_hash = _require_sha256("input_package_hash", input_package_hash)
    salt = _require_salt("salt", salt)

    return {
        "type": COMMITMENT_PREIMAGE_TYPE,
        "protocol_version": protocol_version,
        "network": network,
        "round_number": round_number,
        "validator_master_key": validator_master_key,
        "input_package_hash": input_package_hash,
        "output_hashes": output_hashes_obj.as_dict(),
        "salt": salt,
    }


def compute_commitment_hash(
    *,
    protocol_version: int,
    network: str,
    round_number: int,
    validator_master_key: str,
    input_package_hash: str,
    output_hashes: OutputHashes | Mapping[str, Any],
    salt: str,
) -> str:
    return canonical_sha256(
        build_commitment_preimage(
            protocol_version=protocol_version,
            network=network,
            round_number=round_number,
            validator_master_key=validator_master_key,
            input_package_hash=input_package_hash,
            output_hashes=output_hashes,
            salt=salt,
        )
    )


def compute_reveal_commitment_hash(reveal: RevealPayload) -> str:
    return compute_commitment_hash(
        protocol_version=reveal.protocol_version,
        network=reveal.network,
        round_number=reveal.round_number,
        validator_master_key=reveal.validator_master_key,
        input_package_hash=reveal.input_package_hash,
        output_hashes=reveal.output_hashes,
        salt=reveal.salt,
    )


def reveal_matches_commit(reveal: RevealPayload, commit: CommitPayload) -> bool:
    if reveal.binding_key != commit.binding_key:
        return False
    return compute_reveal_commitment_hash(reveal) == commit.commitment_hash


def build_commit_signing_payload(
    *,
    protocol_version: int,
    network: str,
    round_number: int,
    validator_master_key: str,
    input_package_hash: str,
    commitment_hash: str,
) -> dict[str, Any]:
    return {
        "type": VALIDATOR_COMMIT_TYPE,
        "protocol_version": _require_protocol_version(protocol_version),
        "network": _require_network(network),
        "round_number": _require_round_number(round_number),
        "validator_master_key": _require_validator_master_key(
            "validator_master_key",
            validator_master_key,
        ),
        "input_package_hash": _require_sha256(
            "input_package_hash",
            input_package_hash,
        ),
        "commitment_hash": _require_sha256("commitment_hash", commitment_hash),
    }


def build_commit_signing_bytes(
    *,
    protocol_version: int,
    network: str,
    round_number: int,
    validator_master_key: str,
    input_package_hash: str,
    commitment_hash: str,
) -> bytes:
    return canonical_json_bytes(
        build_commit_signing_payload(
            protocol_version=protocol_version,
            network=network,
            round_number=round_number,
            validator_master_key=validator_master_key,
            input_package_hash=input_package_hash,
            commitment_hash=commitment_hash,
        )
    )


def build_reveal_signing_payload(
    *,
    protocol_version: int,
    network: str,
    round_number: int,
    validator_master_key: str,
    input_package_hash: str,
    output_hashes: OutputHashes | Mapping[str, Any],
    salt: str,
) -> dict[str, Any]:
    output_hashes_obj = _coerce_output_hashes(output_hashes)
    return {
        "type": VALIDATOR_REVEAL_TYPE,
        "protocol_version": _require_protocol_version(protocol_version),
        "network": _require_network(network),
        "round_number": _require_round_number(round_number),
        "validator_master_key": _require_validator_master_key(
            "validator_master_key",
            validator_master_key,
        ),
        "input_package_hash": _require_sha256(
            "input_package_hash",
            input_package_hash,
        ),
        "output_hashes": output_hashes_obj.as_dict(),
        "salt": _require_salt("salt", salt),
    }


def build_reveal_signing_bytes(
    *,
    protocol_version: int,
    network: str,
    round_number: int,
    validator_master_key: str,
    input_package_hash: str,
    output_hashes: OutputHashes | Mapping[str, Any],
    salt: str,
) -> bytes:
    return canonical_json_bytes(
        build_reveal_signing_payload(
            protocol_version=protocol_version,
            network=network,
            round_number=round_number,
            validator_master_key=validator_master_key,
            input_package_hash=input_package_hash,
            output_hashes=output_hashes,
            salt=salt,
        )
    )


def commit_signing_payload(commit: CommitPayload | Mapping[str, Any]) -> dict[str, Any]:
    commit_obj = _coerce_commit_payload(commit)
    return commit_obj.signing_payload()


def commit_signing_bytes(commit: CommitPayload | Mapping[str, Any]) -> bytes:
    commit_obj = _coerce_commit_payload(commit)
    return commit_obj.signing_bytes()


def reveal_signing_payload(reveal: RevealPayload | Mapping[str, Any]) -> dict[str, Any]:
    reveal_obj = _coerce_reveal_payload(reveal)
    return reveal_obj.signing_payload()


def reveal_signing_bytes(reveal: RevealPayload | Mapping[str, Any]) -> bytes:
    reveal_obj = _coerce_reveal_payload(reveal)
    return reveal_obj.signing_bytes()


def build_commit_payload(
    *,
    protocol_version: int,
    network: str,
    round_number: int,
    validator_master_key: str,
    input_package_hash: str,
    commitment_hash: str,
    signature: str,
) -> dict[str, Any]:
    payload = build_commit_signing_payload(
        protocol_version=protocol_version,
        network=network,
        round_number=round_number,
        validator_master_key=validator_master_key,
        input_package_hash=input_package_hash,
        commitment_hash=commitment_hash,
    )
    payload["signature"] = signature
    validate_commit_payload(payload)
    return payload


def build_reveal_payload(
    *,
    protocol_version: int,
    network: str,
    round_number: int,
    validator_master_key: str,
    input_package_hash: str,
    output_hashes: OutputHashes | Mapping[str, Any],
    salt: str,
    signature: str,
) -> dict[str, Any]:
    payload = build_reveal_signing_payload(
        protocol_version=protocol_version,
        network=network,
        round_number=round_number,
        validator_master_key=validator_master_key,
        input_package_hash=input_package_hash,
        output_hashes=output_hashes,
        salt=salt,
    )
    payload["signature"] = signature
    validate_reveal_payload(payload)
    return payload


def validate_round_announcement(payload: Mapping[str, Any]) -> RoundAnnouncement:
    _require_exact_fields(
        "round announcement",
        payload,
        {
            "type",
            "protocol_version",
            "network",
            "round_number",
            "round_kind",
            "input_package_cid",
            "input_package_hash",
            "input_frozen_at",
            "commit_opens_at",
            "commit_closes_at",
            "reveal_opens_at",
            "reveal_closes_at",
        },
    )
    _require_type(payload["type"], ROUND_ANNOUNCEMENT_TYPE)
    protocol_version = _require_protocol_version(payload["protocol_version"])
    network = _require_network(payload["network"])
    round_number = _require_round_number(payload["round_number"])
    round_kind = _require_stripped_str("round_kind", payload["round_kind"])
    if round_kind != ROUND_KIND_NORMAL:
        raise CommitRevealValidationError(
            f"round_kind must be {ROUND_KIND_NORMAL!r}",
        )
    input_package_cid = _require_cid(
        "input_package_cid",
        payload["input_package_cid"],
    )
    input_package_hash = _require_sha256(
        "input_package_hash",
        payload["input_package_hash"],
    )
    input_frozen_at = _parse_aware_datetime("input_frozen_at", payload["input_frozen_at"])
    commit_opens_at = _parse_aware_datetime(
        "commit_opens_at",
        payload["commit_opens_at"],
    )
    commit_closes_at = _parse_aware_datetime(
        "commit_closes_at",
        payload["commit_closes_at"],
    )
    reveal_opens_at = _parse_aware_datetime(
        "reveal_opens_at",
        payload["reveal_opens_at"],
    )
    reveal_closes_at = _parse_aware_datetime(
        "reveal_closes_at",
        payload["reveal_closes_at"],
    )
    _validate_windows(
        commit_opens_at=commit_opens_at,
        commit_closes_at=commit_closes_at,
        reveal_opens_at=reveal_opens_at,
        reveal_closes_at=reveal_closes_at,
    )
    return RoundAnnouncement(
        protocol_version=protocol_version,
        network=network,
        round_number=round_number,
        round_kind=round_kind,
        input_package_cid=input_package_cid,
        input_package_hash=input_package_hash,
        input_frozen_at=input_frozen_at,
        commit_opens_at=commit_opens_at,
        commit_closes_at=commit_closes_at,
        reveal_opens_at=reveal_opens_at,
        reveal_closes_at=reveal_closes_at,
    )


def validate_commit_payload(payload: Mapping[str, Any]) -> CommitPayload:
    _require_exact_fields(
        "commit payload",
        payload,
        {
            "type",
            "protocol_version",
            "network",
            "round_number",
            "validator_master_key",
            "input_package_hash",
            "commitment_hash",
            "signature",
        },
    )
    _require_type(payload["type"], VALIDATOR_COMMIT_TYPE)
    return CommitPayload(
        protocol_version=_require_protocol_version(payload["protocol_version"]),
        network=_require_network(payload["network"]),
        round_number=_require_round_number(payload["round_number"]),
        validator_master_key=_require_validator_master_key(
            "validator_master_key",
            payload["validator_master_key"],
        ),
        input_package_hash=_require_sha256(
            "input_package_hash",
            payload["input_package_hash"],
        ),
        commitment_hash=_require_sha256(
            "commitment_hash",
            payload["commitment_hash"],
        ),
        signature=_require_signature("signature", payload["signature"]),
    )


def validate_reveal_payload(payload: Mapping[str, Any]) -> RevealPayload:
    _require_exact_fields(
        "reveal payload",
        payload,
        {
            "type",
            "protocol_version",
            "network",
            "round_number",
            "validator_master_key",
            "input_package_hash",
            "output_hashes",
            "salt",
            "signature",
        },
    )
    _require_type(payload["type"], VALIDATOR_REVEAL_TYPE)
    return RevealPayload(
        protocol_version=_require_protocol_version(payload["protocol_version"]),
        network=_require_network(payload["network"]),
        round_number=_require_round_number(payload["round_number"]),
        validator_master_key=_require_validator_master_key(
            "validator_master_key",
            payload["validator_master_key"],
        ),
        input_package_hash=_require_sha256(
            "input_package_hash",
            payload["input_package_hash"],
        ),
        output_hashes=validate_output_hashes(payload["output_hashes"]),
        salt=_require_salt("salt", payload["salt"]),
        signature=_require_signature("signature", payload["signature"]),
    )


def validate_output_hashes(payload: Mapping[str, Any]) -> OutputHashes:
    _require_exact_fields("output_hashes", payload, set(OUTPUT_HASH_FIELDS))
    return OutputHashes(
        model_response_hash=_require_sha256(
            MODEL_RESPONSE_HASH,
            payload[MODEL_RESPONSE_HASH],
        ),
        validator_scores_hash=_require_sha256(
            VALIDATOR_SCORES_HASH,
            payload[VALIDATOR_SCORES_HASH],
        ),
        selected_unl_hash=_require_sha256(
            SELECTED_UNL_HASH,
            payload[SELECTED_UNL_HASH],
        ),
    )


def commit_matches_announcement(
    commit: CommitPayload,
    announcement: RoundAnnouncement,
) -> bool:
    return (
        commit.protocol_version == announcement.protocol_version
        and commit.network == announcement.network
        and commit.round_number == announcement.round_number
        and commit.input_package_hash == announcement.input_package_hash
    )


def reveal_matches_announcement(
    reveal: RevealPayload,
    announcement: RoundAnnouncement,
) -> bool:
    return (
        reveal.protocol_version == announcement.protocol_version
        and reveal.network == announcement.network
        and reveal.round_number == announcement.round_number
        and reveal.input_package_hash == announcement.input_package_hash
    )


def is_commit_within_window(
    announcement: RoundAnnouncement,
    validated_ledger_close_time: datetime | str,
) -> bool:
    close_time = _parse_aware_datetime(
        "validated_ledger_close_time",
        validated_ledger_close_time,
    )
    return announcement.commit_opens_at <= close_time < announcement.commit_closes_at


def is_reveal_within_window(
    announcement: RoundAnnouncement,
    validated_ledger_close_time: datetime | str,
) -> bool:
    close_time = _parse_aware_datetime(
        "validated_ledger_close_time",
        validated_ledger_close_time,
    )
    return announcement.reveal_opens_at <= close_time < announcement.reveal_closes_at


def first_by_ledger_order(
    items: Iterable[T],
    position_getter: Callable[[T], LedgerPosition],
) -> T | None:
    ordered_items = list(items)
    if not ordered_items:
        return None
    return min(ordered_items, key=position_getter)


def _coerce_output_hashes(
    output_hashes: OutputHashes | Mapping[str, Any],
) -> OutputHashes:
    if isinstance(output_hashes, OutputHashes):
        return output_hashes
    return validate_output_hashes(output_hashes)


def _coerce_commit_payload(commit: CommitPayload | Mapping[str, Any]) -> CommitPayload:
    if isinstance(commit, CommitPayload):
        return commit
    return validate_commit_payload(commit)


def _coerce_reveal_payload(reveal: RevealPayload | Mapping[str, Any]) -> RevealPayload:
    if isinstance(reveal, RevealPayload):
        return reveal
    return validate_reveal_payload(reveal)


def _require_exact_fields(
    label: str,
    payload: Mapping[str, Any],
    expected_fields: set[str],
) -> None:
    if not isinstance(payload, Mapping):
        raise CommitRevealValidationError(f"{label} must be a JSON object")
    actual_fields = set(payload.keys())
    missing = sorted(expected_fields - actual_fields)
    unknown = sorted(actual_fields - expected_fields)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        raise CommitRevealValidationError(f"{label} has invalid fields ({'; '.join(details)})")


def _require_type(value: Any, expected: str) -> str:
    if value != expected:
        raise CommitRevealValidationError(f"type must be {expected!r}")
    return expected


def _require_protocol_version(value: Any) -> int:
    version = _require_int("protocol_version", value, min_value=1)
    if version != PROTOCOL_VERSION:
        raise CommitRevealValidationError(
            f"protocol_version must be {PROTOCOL_VERSION}",
        )
    return version


def _require_int(name: str, value: Any, *, min_value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommitRevealValidationError(f"{name} must be an integer")
    if value < min_value:
        raise CommitRevealValidationError(f"{name} must be >= {min_value}")
    return value


def _require_stripped_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CommitRevealValidationError(f"{name} must be a non-empty string")
    return value


def _require_network(value: Any) -> str:
    network = _require_stripped_str("network", value)
    if network != network.strip():
        raise CommitRevealValidationError("network must not contain surrounding whitespace")
    return network


def _require_round_number(value: Any) -> int:
    return _require_int("round_number", value, min_value=1)


def _require_cid(name: str, value: Any) -> str:
    cid = _require_stripped_str(name, value)
    if not _CID_RE.fullmatch(cid):
        raise CommitRevealValidationError(f"{name} must be a CIDv0 or CIDv1 string")
    return cid


def _require_validator_master_key(name: str, value: Any) -> str:
    master_key = _require_stripped_str(name, value)
    if not _VALIDATOR_MASTER_KEY_RE.fullmatch(master_key):
        raise CommitRevealValidationError(
            f"{name} must look like a validator master key",
        )
    return master_key


def _require_sha256(name: str, value: Any) -> str:
    if not is_sha256_hex(value):
        raise CommitRevealValidationError(
            f"{name} must be {SHA256_HEX_LENGTH} lowercase hex characters",
        )
    return value


def _require_salt(name: str, value: Any) -> str:
    if not is_salt_hex(value):
        raise CommitRevealValidationError(
            f"{name} must be {SALT_HEX_LENGTH} lowercase hex characters",
        )
    return value


def _require_signature(name: str, value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) % 2 != 0
        or not _HEX_RE.fullmatch(value)
    ):
        raise CommitRevealValidationError(f"{name} must be a non-empty hex string")
    return value


def _parse_aware_datetime(name: str, value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CommitRevealValidationError(f"{name} must be an ISO datetime") from exc
    else:
        raise CommitRevealValidationError(f"{name} must be an ISO datetime")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CommitRevealValidationError(f"{name} must include timezone information")
    return parsed.astimezone(timezone.utc)


def _validate_windows(
    *,
    commit_opens_at: datetime,
    commit_closes_at: datetime,
    reveal_opens_at: datetime,
    reveal_closes_at: datetime,
) -> None:
    if commit_opens_at >= commit_closes_at:
        raise CommitRevealValidationError(
            "commit_opens_at must be before commit_closes_at",
        )
    if reveal_opens_at >= reveal_closes_at:
        raise CommitRevealValidationError(
            "reveal_opens_at must be before reveal_closes_at",
        )
    if reveal_opens_at < commit_closes_at:
        raise CommitRevealValidationError(
            "reveal_opens_at must not be before commit_closes_at",
        )
