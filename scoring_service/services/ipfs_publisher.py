"""IPFS audit trail assembly and publication service.

Assembles the complete evidence chain from a scoring round into a
structured directory, pins it to IPFS, and stores the files in
PostgreSQL for HTTPS fallback serving.
"""

import hashlib
import json
import logging
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai.types.chat import ChatCompletionMessageParam

from scoring_service.clients.ipfs import IPFSClient
from scoring_service.clients.pinata import PinataClient
from scoring_service.config import QWEN_NON_THINKING_EXTRA_BODY, REPO_ROOT, settings
from scoring_service.models import ScoringSnapshot
from scoring_service.services.dry_runs import store_dry_run_artifacts
from scoring_service.services.prompt_builder import PROMPT_PATH, ValidatorIdentityMap
from scoring_service.services.response_parser import ScoringResult
from scoring_service.services.unl_selector import UNLSelectionResult

logger = logging.getLogger(__name__)

BUNDLE_VERSION = 2
EXECUTION_MANIFEST_SCHEMA_VERSION = 1
GEOLOCATION_ATTRIBUTION = "IP geolocation by DB-IP.com"
PROMPT_VERSION = "v5"
REPOSITORY_NAME = "postfiatorg/dynamic-unl-scoring"
MODEL_PROVIDER = "huggingface"
RUNTIME_KIND = "modal_sglang"
MODEL_REQUEST_METHOD = "chat.completions.create"
MODEL_REQUEST_TYPE = "openai_chat_completions"
MODEL_RESPONSE_FORMAT = {"type": "json_object"}

BUNDLE_FILE_PATH = "bundle.json"
VALIDATOR_EVIDENCE_FILE_PATH = "inputs/validator_evidence.json"
MODEL_REQUEST_FILE_PATH = "inputs/model_request.json"
VALIDATOR_MAP_FILE_PATH = "inputs/validator_map.json"
EXECUTION_MANIFEST_FILE_PATH = "runtime/execution_manifest.json"
MODEL_RESPONSE_FILE_PATH = "outputs/model_response.json"
VALIDATOR_SCORES_FILE_PATH = "outputs/validator_scores.json"
SELECTED_UNL_FILE_PATH = "outputs/selected_unl.json"
SIGNED_VALIDATOR_LIST_FILE_PATH = "outputs/signed_validator_list.json"
VERIFICATION_HASHES_FILE_PATH = "outputs/verification_hashes.json"
LEGACY_SELECTED_UNL_FILE_PATH = "unl.json"
RAW_SOURCE_PATH_OVERRIDES = {
    "geoip_lookups": "geolocation_lookups",
}
VERIFICATION_HASH_TARGETS = (
    ("model_response_hash", MODEL_RESPONSE_FILE_PATH),
    ("validator_scores_hash", VALIDATOR_SCORES_FILE_PATH),
    ("selected_unl_hash", SELECTED_UNL_FILE_PATH),
    ("signed_validator_list_hash", SIGNED_VALIDATOR_LIST_FILE_PATH),
)

ENTRYPOINT_PATHS = {
    "validator_evidence": VALIDATOR_EVIDENCE_FILE_PATH,
    "model_request": MODEL_REQUEST_FILE_PATH,
    "validator_map": VALIDATOR_MAP_FILE_PATH,
    "execution_manifest": EXECUTION_MANIFEST_FILE_PATH,
    "model_response": MODEL_RESPONSE_FILE_PATH,
    "validator_scores": VALIDATOR_SCORES_FILE_PATH,
    "selected_unl": SELECTED_UNL_FILE_PATH,
    "signed_validator_list": SIGNED_VALIDATOR_LIST_FILE_PATH,
    "verification_hashes": VERIFICATION_HASHES_FILE_PATH,
}


def _content_hash(data: object) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _serialize(data: object) -> bytes:
    return json.dumps(data, indent=2, sort_keys=True, default=str).encode()


def _build_scores(scoring_result: ScoringResult) -> dict:
    scores: dict[str, Any] = {
        "validator_scores": [
            {
                "master_key": v.master_key,
                "score": v.score,
                "consensus": v.consensus,
                "reliability": v.reliability,
                "software": v.software,
                "diversity": v.diversity,
                "identity": v.identity,
                "reasoning": v.reasoning,
            }
            for v in scoring_result.validator_scores
        ],
    }

    if scoring_result.network_summary:
        scores["network_summary"] = scoring_result.network_summary
    if scoring_result.network_report is not None:
        scores["network_report"] = scoring_result.network_report.model_dump(mode="json")

    return scores


def _build_raw_response(scoring_result: ScoringResult) -> dict:
    return {"raw_response": scoring_result.raw_response}


def _build_unl(unl_result: UNLSelectionResult) -> dict:
    return {
        "unl": unl_result.unl,
        "alternates": unl_result.alternates,
    }


def _build_override_unl(master_keys: list[str]) -> dict:
    return {
        "unl": master_keys,
        "alternates": [],
    }


def _collect_gateway_urls() -> list[str]:
    gateways = []
    ipfs_gateway_url = _str_setting("ipfs_gateway_url")
    pinata_gateway_url = _str_setting("pinata_gateway_url")
    if ipfs_gateway_url:
        gateways.append(ipfs_gateway_url.rstrip("/"))
    if pinata_gateway_url:
        gateways.append(pinata_gateway_url.rstrip("/"))
    return gateways


def _build_file_hashes(files: dict[str, Any]) -> dict[str, str]:
    return {
        path: _content_hash(content)
        for path, content in sorted(files.items())
    }


def _build_verification_hashes(files: dict[str, Any]) -> dict[str, str]:
    return {
        hash_name: _content_hash(files[file_path])
        for hash_name, file_path in VERIFICATION_HASH_TARGETS
        if file_path in files
    }


def _str_setting(name: str, default: str = "") -> str:
    value = getattr(settings, name, default)
    if not isinstance(value, str):
        return default
    return value.strip()


def _int_setting(name: str, default: int) -> int:
    value = getattr(settings, name, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _bool_setting(name: str, default: bool = False) -> bool:
    value = getattr(settings, name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _git_commit_from_repo() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    commit = result.stdout.strip()
    return commit or None


def _resolve_code_commit() -> str | None:
    return _str_setting("scoring_service_git_commit") or _git_commit_from_repo()


def _resolve_model_revision() -> str | None:
    return _str_setting("scoring_model_revision") or None


def _prompt_template_hash() -> str:
    return hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()


def _repo_relative_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _git_version(commit: str | None) -> str | None:
    return f"git:{commit}" if commit else None


def _with_git_version(module: str, commit: str | None) -> dict[str, Any]:
    identity = {"module": module}
    version = _git_version(commit)
    if version is not None:
        identity["version"] = version
    return identity


def _model_request_extra_body() -> dict[str, Any]:
    return QWEN_NON_THINKING_EXTRA_BODY if _bool_setting("scoring_disable_thinking") else {}


def _build_model_request(
    messages: Sequence[ChatCompletionMessageParam],
) -> dict[str, Any]:
    model_id = _str_setting("scoring_model_id", "Qwen/Qwen3.6-27B-FP8")
    request: dict[str, Any] = {
        "method": MODEL_REQUEST_METHOD,
        "model": model_id,
        "messages": list(messages),
        "temperature": _int_setting("scoring_temperature", 0),
        "max_tokens": _int_setting("scoring_max_tokens", 16384),
        "response_format": MODEL_RESPONSE_FORMAT,
    }
    extra_body = _model_request_extra_body()
    if extra_body:
        request["extra_body"] = extra_body
    return request


def _build_model_manifest() -> dict[str, Any]:
    model_id = _str_setting("scoring_model_id", "Qwen/Qwen3.6-27B-FP8")
    model = {
        "provider": MODEL_PROVIDER,
        "repo_id": model_id,
        "served_name": model_id,
    }
    revision = _resolve_model_revision()
    if revision is not None:
        model["revision"] = revision
    return model


def _build_runtime_manifest() -> dict[str, Any]:
    model_id = _str_setting("scoring_model_id", "Qwen/Qwen3.6-27B-FP8")
    tensor_parallelism = _int_setting("scoring_tp", 1)
    launch_args = [
        "--model-path",
        model_id,
        "--served-model-name",
        model_id,
        "--tp",
        str(tensor_parallelism),
        "--mem-fraction-static",
        _str_setting("scoring_mem_fraction", "0.75"),
        "--chunked-prefill-size",
        str(_int_setting("scoring_chunked_prefill", 4096)),
        "--max-running-requests",
        str(_int_setting("scoring_max_reqs", 1)),
        "--enable-deterministic-inference",
        "--enable-metrics",
        "--trust-remote-code",
    ]
    quantization = _str_setting("scoring_quantization")
    if quantization:
        launch_args.extend(["--quantization", quantization])
    attention_backend = _str_setting("scoring_attention_backend")
    if attention_backend:
        launch_args.extend(["--attention-backend", attention_backend])
    reasoning_parser = _str_setting("scoring_reasoning_parser", "qwen3")
    if reasoning_parser:
        launch_args.extend(["--reasoning-parser", reasoning_parser])

    return {
        "kind": RUNTIME_KIND,
        "image": _str_setting(
            "scoring_sglang_image_tag",
            (
                "lmsysorg/sglang:nightly-dev-cu13-20260430-e60c60ef"
                "@sha256:5d9ec71597ade6b8237d61ae6f01b976cb3d5ad2c1e3cf4e0acaf27a9ff49a65"
            ),
        ),
        "gpu": _str_setting("scoring_gpu_type", "H100"),
        "tensor_parallelism": tensor_parallelism,
        "launch_command": ["python", "-m", "sglang.launch_server"],
        "launch_args": launch_args,
        "environment": {
            "SGLANG_FLASHINFER_WORKSPACE_SIZE": _str_setting(
                "sglang_flashinfer_workspace_size",
                "2147483648",
            ),
        },
    }


def _build_request_manifest() -> dict[str, Any]:
    model_id = _str_setting("scoring_model_id", "Qwen/Qwen3.6-27B-FP8")
    request = {
        "type": MODEL_REQUEST_TYPE,
        "file": MODEL_REQUEST_FILE_PATH,
        "method": MODEL_REQUEST_METHOD,
        "model": model_id,
        "temperature": _int_setting("scoring_temperature", 0),
        "max_tokens": _int_setting("scoring_max_tokens", 16384),
        "response_format": MODEL_RESPONSE_FORMAT,
        "timeout_seconds": _int_setting("modal_request_timeout_seconds", 2100),
    }
    extra_body = _model_request_extra_body()
    if extra_body:
        request["extra_body"] = extra_body
    return request


def _build_code_manifest(
    *,
    include_collector: bool,
    include_prompt: bool,
    include_parser: bool,
    include_selector: bool,
    include_vl_generator: bool,
) -> dict[str, Any]:
    commit = _resolve_code_commit()
    code: dict[str, Any] = {"repository": REPOSITORY_NAME}
    if commit is not None:
        code["commit"] = commit

    if include_collector:
        collector = _with_git_version(
            "scoring_service.services.collector",
            commit,
        )
        collector["parameters"] = {
            "excluded_validator_server_versions": sorted(
                settings.excluded_validator_server_version_set
            ),
        }
        code["collector"] = collector
    if include_prompt:
        code["prompt"] = {
            "version": PROMPT_VERSION,
            "template_path": _repo_relative_path(PROMPT_PATH),
            "template_sha256": _prompt_template_hash(),
        }
    if include_parser:
        code["parser"] = _with_git_version(
            "scoring_service.services.response_parser",
            commit,
        )
    if include_selector:
        selector = _with_git_version(
            "scoring_service.services.unl_selector",
            commit,
        )
        selector["parameters"] = {
            "score_cutoff": _int_setting("unl_score_cutoff", 40),
            "max_size": _int_setting("unl_max_size", 35),
            "min_score_gap": _int_setting("unl_min_score_gap", 5),
        }
        code["selector"] = selector
    if include_vl_generator:
        code["vl_generator"] = _with_git_version(
            "scoring_service.services.vl_generator",
            commit,
        )
    return code


def _build_canonicalization_manifest() -> dict[str, Any]:
    return {
        "hash_algorithm": "sha256",
        "text_encoding": "utf-8",
        "json_encoding": {
            "sort_keys": True,
            "separators": [",", ":"],
            "default": "str",
        },
    }


def _build_execution_manifest(
    *,
    round_kind: str,
    network: str,
    published_at: datetime,
    round_number: int | None = None,
    dry_run_id: int | None = None,
    override: dict[str, str] | None = None,
    signed_vl: bool = False,
) -> dict[str, Any]:
    inference_performed = round_kind != "override"
    round_data: dict[str, Any] = {
        "kind": round_kind,
        "network": network,
        "published_at": published_at.isoformat(),
        "inference_performed": inference_performed,
    }
    if round_number is not None:
        round_data["round_number"] = round_number
    if dry_run_id is not None:
        round_data["dry_run_id"] = dry_run_id

    manifest: dict[str, Any] = {
        "schema_version": EXECUTION_MANIFEST_SCHEMA_VERSION,
        "round": round_data,
        "code": _build_code_manifest(
            include_collector=inference_performed,
            include_prompt=inference_performed,
            include_parser=inference_performed,
            include_selector=inference_performed,
            include_vl_generator=signed_vl,
        ),
        "canonicalization": _build_canonicalization_manifest(),
    }

    if inference_performed:
        manifest["model"] = _build_model_manifest()
        manifest["runtime"] = _build_runtime_manifest()
        manifest["request"] = _build_request_manifest()
    if override is not None:
        manifest["override"] = override

    return manifest


def _entrypoints_for_files(files: dict[str, Any]) -> dict[str, str]:
    return {
        name: path
        for name, path in ENTRYPOINT_PATHS.items()
        if path in files
    }


def _build_bundle(
    files: dict[str, Any],
    *,
    round_kind: str,
    network: str,
    published_at: datetime,
    round_number: int | None = None,
    dry_run_id: int | None = None,
    override: dict[str, str] | None = None,
) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "bundle_version": BUNDLE_VERSION,
        "round_kind": round_kind,
        "network": network,
        "published_at": published_at.isoformat(),
        "geolocation_attribution": GEOLOCATION_ATTRIBUTION,
        "gateway_urls": [] if round_kind == "dry_run" else _collect_gateway_urls(),
        "entrypoints": _entrypoints_for_files(files),
        "file_hashes": _build_file_hashes(files),
    }
    if round_number is not None:
        bundle["round_number"] = round_number
    if dry_run_id is not None:
        bundle["dry_run_id"] = dry_run_id
        bundle["dry_run"] = True
    if override is not None:
        bundle["override"] = override
    return bundle


def _add_bundle_file(
    files: dict[str, Any],
    *,
    round_kind: str,
    network: str,
    published_at: datetime,
    round_number: int | None = None,
    dry_run_id: int | None = None,
    override: dict[str, str] | None = None,
) -> None:
    files[BUNDLE_FILE_PATH] = _build_bundle(
        files,
        round_kind=round_kind,
        network=network,
        published_at=published_at,
        round_number=round_number,
        dry_run_id=dry_run_id,
        override=override,
    )


def _add_verification_hashes_file(files: dict[str, Any]) -> None:
    files[VERIFICATION_HASHES_FILE_PATH] = _build_verification_hashes(files)


def _raw_evidence_path(source_name: str) -> str:
    normalized_source = RAW_SOURCE_PATH_OVERRIDES.get(source_name, source_name)
    return f"raw/{normalized_source}.json"


def _build_scoring_files(
    snapshot: ScoringSnapshot,
    raw_evidence: dict[str, Any],
    scoring_result: ScoringResult,
    unl_result: UNLSelectionResult,
    *,
    published_at: datetime,
    round_kind: str,
    round_number: int | None = None,
    dry_run_id: int | None = None,
    prompt_messages: Sequence[ChatCompletionMessageParam] | None = None,
    validator_id_map: ValidatorIdentityMap | None = None,
    signed_vl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot_data = json.loads(snapshot.model_dump_json())
    if dry_run_id is not None:
        snapshot_data.pop("round_number", None)
        snapshot_data["dry_run_id"] = dry_run_id
    scores = _build_scores(scoring_result)
    model_request = _build_model_request(prompt_messages or [])
    validator_mapping = validator_id_map or {}
    raw_response = _build_raw_response(scoring_result)
    unl = _build_unl(unl_result)

    assembled: dict[str, Any] = {
        VALIDATOR_EVIDENCE_FILE_PATH: snapshot_data,
        MODEL_REQUEST_FILE_PATH: model_request,
        VALIDATOR_MAP_FILE_PATH: validator_mapping,
        MODEL_RESPONSE_FILE_PATH: raw_response,
        VALIDATOR_SCORES_FILE_PATH: scores,
        SELECTED_UNL_FILE_PATH: unl,
    }

    if signed_vl is not None:
        assembled[SIGNED_VALIDATOR_LIST_FILE_PATH] = signed_vl

    for source_name, raw_data in raw_evidence.items():
        assembled[_raw_evidence_path(source_name)] = raw_data

    assembled[EXECUTION_MANIFEST_FILE_PATH] = _build_execution_manifest(
        round_kind=round_kind,
        network=snapshot.network,
        published_at=published_at,
        round_number=round_number,
        dry_run_id=dry_run_id,
        signed_vl=signed_vl is not None,
    )
    _add_verification_hashes_file(assembled)
    _add_bundle_file(
        assembled,
        round_kind=round_kind,
        network=snapshot.network,
        published_at=published_at,
        round_number=round_number,
        dry_run_id=dry_run_id,
    )

    return assembled


def _build_override_files(
    *,
    round_number: int,
    master_keys: list[str],
    signed_vl: dict[str, Any],
    override_type: str,
    override_reason: str,
    published_at: datetime,
) -> dict[str, Any]:
    network = _str_setting("pftl_network", "devnet")
    override = {
        "type": override_type,
        "reason": override_reason,
    }
    assembled: dict[str, Any] = {
        SELECTED_UNL_FILE_PATH: _build_override_unl(master_keys),
        SIGNED_VALIDATOR_LIST_FILE_PATH: signed_vl,
        EXECUTION_MANIFEST_FILE_PATH: _build_execution_manifest(
            round_kind="override",
            network=network,
            published_at=published_at,
            round_number=round_number,
            override=override,
            signed_vl=True,
        ),
    }
    _add_verification_hashes_file(assembled)
    _add_bundle_file(
        assembled,
        round_kind="override",
        network=network,
        published_at=published_at,
        round_number=round_number,
        override=override,
    )
    return assembled


def _store_audit_trail_files(
    conn,
    round_number: int,
    files: dict[str, Any],
) -> None:
    cursor = conn.cursor()
    for file_path, content in files.items():
        cursor.execute(
            """
            INSERT INTO audit_trail_files (round_number, file_path, content)
            VALUES (%s, %s, %s)
            ON CONFLICT (round_number, file_path) DO UPDATE SET
                content = EXCLUDED.content,
                created_at = now()
            """,
            (round_number, file_path, json.dumps(content, sort_keys=True, default=str)),
        )
    cursor.close()


def get_audit_trail_file(conn, round_number: int, file_path: str) -> dict | None:
    """Retrieve a single audit trail file from the database."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT content FROM audit_trail_files WHERE round_number = %s AND file_path = %s",
        (round_number, file_path),
    )
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else None


def get_selected_unl_file(conn, round_number: int) -> dict | None:
    """Retrieve selected UNL output across new and historical bundle layouts."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT content
        FROM audit_trail_files
        WHERE round_number = %s
        AND file_path IN %s
        ORDER BY CASE WHEN file_path = %s THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (
            round_number,
            (SELECTED_UNL_FILE_PATH, LEGACY_SELECTED_UNL_FILE_PATH),
            SELECTED_UNL_FILE_PATH,
        ),
    )
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else None


class IPFSPublisherService:
    """Assembles and publishes the scoring round audit trail."""

    def __init__(
        self,
        ipfs_client: IPFSClient | None = None,
        pinata_client: PinataClient | None = None,
    ):
        self._ipfs = ipfs_client or IPFSClient()
        if pinata_client is not None:
            self._pinata = pinata_client
        elif settings.pinata_enabled:
            self._pinata = PinataClient()
        else:
            self._pinata = None
            logger.info("Pinata secondary pinning disabled — credentials not configured")

    def _pin_directory_with_fallback(
        self, ipfs_files: dict[str, bytes], pin_name: str
    ) -> str | None:
        """Pin a directory to the primary IPFS node, with a Pinata write fallback.

        The self-hosted node stays primary: it is pinned first and, on success,
        replicated to Pinata by CID exactly as before — so the healthy-node path
        is unchanged. Only when the primary returns no CID does this upload the
        same content directly to Pinata and use the CID Pinata returns. Returns
        whichever CID actually holds the content, or None if both providers fail.
        Integrity is anchored by the artifact content hash, not the CID.
        """
        root_cid = self._ipfs.pin_directory(ipfs_files)
        if root_cid is not None:
            if self._pinata is not None and not self._pinata.pin_by_cid(
                root_cid, name=pin_name
            ):
                logger.warning(
                    "Pinata secondary pin failed for %s (cid=%s) — primary pin is "
                    "source of truth",
                    pin_name,
                    root_cid,
                )
            return root_cid

        if self._pinata is None:
            return None

        logger.warning(
            "Primary IPFS pin returned no CID for %s — falling back to direct "
            "Pinata upload",
            pin_name,
        )
        fallback_cid = self._pinata.pin_directory(ipfs_files, name=pin_name)
        if fallback_cid is None:
            logger.error("Pinata fallback upload also failed for %s", pin_name)
        return fallback_cid

    def publish(
        self,
        round_number: int,
        snapshot: ScoringSnapshot,
        raw_evidence: dict[str, Any],
        scoring_result: ScoringResult,
        unl_result: UNLSelectionResult,
        signed_vl: dict[str, Any],
        conn,
        prompt_messages: Sequence[ChatCompletionMessageParam] | None = None,
        validator_id_map: ValidatorIdentityMap | None = None,
    ) -> str | None:
        """Assemble the audit trail, pin to IPFS, and store for HTTPS fallback.

        Args:
            round_number: Scoring round number.
            snapshot: Assembled validator data snapshot.
            raw_evidence: Mapping of source names to raw data dicts
                (vhs_validators, vhs_topology, crawl_probes, asn_lookups, geoip_lookups).
            scoring_result: Parsed LLM scoring output.
            unl_result: UNL selection result (selected + alternates).
            signed_vl: The signed Validator List JSON (v2 format).
            conn: Database connection for atomic CID and file storage.
            prompt_messages: Exact OpenAI-compatible messages sent to the LLM.
            validator_id_map: Anonymous validator IDs mapped to validator identity fields.

        Returns:
            Root CID of the pinned directory, or None if IPFS pinning failed.
        """
        published_at = datetime.now(timezone.utc)
        assembled = _build_scoring_files(
            snapshot=snapshot,
            raw_evidence=raw_evidence,
            scoring_result=scoring_result,
            unl_result=unl_result,
            published_at=published_at,
            round_kind="normal",
            round_number=round_number,
            prompt_messages=prompt_messages,
            validator_id_map=validator_id_map,
            signed_vl=signed_vl,
        )

        ipfs_files = {
            path: _serialize(content)
            for path, content in assembled.items()
        }

        pin_name = f"dynamic-unl-scoring-round-{round_number}"
        root_cid = self._pin_directory_with_fallback(ipfs_files, pin_name)

        if root_cid is None:
            logger.error("IPFS pinning failed for round %d", round_number)
            return None

        try:
            _store_audit_trail_files(conn, round_number, assembled)
            conn.commit()
            logger.info(
                "Audit trail published: round=%d, cid=%s, files=%d",
                round_number,
                root_cid,
                len(assembled),
            )
        except Exception:
            conn.rollback()
            logger.exception("Failed to store audit trail files for round %d", round_number)
            raise

        return root_cid

    def publish_dry_run(
        self,
        dry_run_id: int,
        snapshot: ScoringSnapshot,
        raw_evidence: dict[str, Any],
        scoring_result: ScoringResult,
        unl_result: UNLSelectionResult,
        conn,
        prompt_messages: Sequence[ChatCompletionMessageParam] | None = None,
        validator_id_map: ValidatorIdentityMap | None = None,
    ) -> None:
        """Store dry-run audit trail files for review without external publishing."""
        published_at = datetime.now(timezone.utc)
        assembled = _build_scoring_files(
            snapshot=snapshot,
            raw_evidence=raw_evidence,
            scoring_result=scoring_result,
            unl_result=unl_result,
            published_at=published_at,
            round_kind="dry_run",
            dry_run_id=dry_run_id,
            prompt_messages=prompt_messages,
            validator_id_map=validator_id_map,
        )

        try:
            store_dry_run_artifacts(conn, dry_run_id, assembled)
            conn.commit()
            logger.info(
                "Dry-run audit trail stored: dry_run_id=%d, files=%d",
                dry_run_id,
                len(assembled),
            )
        except Exception:
            conn.rollback()
            logger.exception(
                "Failed to store dry-run audit trail files for dry_run_id %d",
                dry_run_id,
            )
            raise

    def publish_override(
        self,
        round_number: int,
        master_keys: list[str],
        signed_vl: dict[str, Any],
        override_type: str,
        override_reason: str,
        conn,
    ) -> str | None:
        """Assemble and pin the audit trail for an admin override round.

        Override rounds have no collected snapshot, no LLM scores, and no
        selector evidence — the UNL was supplied by an operator. The bundle
        contains only the staged no-inference contract and override-relevant
        outputs.
        """
        published_at = datetime.now(timezone.utc)
        assembled = _build_override_files(
            round_number=round_number,
            master_keys=master_keys,
            signed_vl=signed_vl,
            override_type=override_type,
            override_reason=override_reason,
            published_at=published_at,
        )

        ipfs_files = {
            path: _serialize(content)
            for path, content in assembled.items()
        }

        pin_name = f"dynamic-unl-scoring-override-round-{round_number}"
        root_cid = self._pin_directory_with_fallback(ipfs_files, pin_name)

        if root_cid is None:
            logger.error("IPFS pinning failed for override round %d", round_number)
            return None

        try:
            _store_audit_trail_files(conn, round_number, assembled)
            conn.commit()
            logger.info(
                "Override audit trail published: round=%d, cid=%s, type=%s",
                round_number,
                root_cid,
                override_type,
            )
        except Exception:
            conn.rollback()
            logger.exception(
                "Failed to store override audit trail files for round %d", round_number
            )
            raise

        return root_cid
