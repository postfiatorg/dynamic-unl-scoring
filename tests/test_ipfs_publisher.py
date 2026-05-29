"""Tests for the IPFS audit trail publisher service."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scoring_service.config import QWEN_NON_THINKING_EXTRA_BODY
from scoring_service.models import (
    AgreementScore,
    ScoringSnapshot,
    ValidatorProfile,
)
from scoring_service.services import response_parser, unl_selector
from scoring_service.services.ipfs_publisher import (
    IPFSPublisherService,
    _build_bundle,
    _build_execution_manifest,
    _build_input_package_files,
    _build_model_request,
    _build_scores,
    _build_unl,
    _build_verification_hashes,
    _collect_gateway_urls,
    _content_hash,
    _store_audit_trail_files,
    _store_input_package_files,
    get_audit_trail_file,
    get_input_package_file,
    get_selected_unl_file,
)
from scoring_service.services.response_parser import (
    NetworkReport,
    ScoringResult,
    ValidatorScore,
)
from scoring_service.services.unl_selector import UNLSelectionResult


FIXED_TIME = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)

SAMPLE_VALIDATOR = ValidatorProfile(
    master_key="nHUkhbZe9ncdmhn6dbd5x7391ymwCS3YZEMWjysP9fSiDtau9YEe",
    signing_key="n9Kc1swwT6uHYMv5feRTSTwtXtQgBWxDZrWDuHQj7fBTnQaoC9ux",
    domain="postfiat.org",
    domain_verified=True,
    agreement_1h=AgreementScore(score=1.0, total=100, missed=0),
    agreement_24h=AgreementScore(score=0.99, total=2400, missed=24),
    agreement_30d=AgreementScore(score=0.98, total=72000, missed=1440),
    server_version="2024.1.1",
    unl=True,
)


def _make_snapshot(round_number=1):
    return ScoringSnapshot(
        round_number=round_number,
        network="testnet",
        snapshot_timestamp=FIXED_TIME,
        validators=[SAMPLE_VALIDATOR],
    )


def _make_network_report():
    return NetworkReport(
        headline="Consensus strength with concentration risk",
        summary=(
            "Consensus health is strong overall, while concentration and identity "
            "signals create meaningful selection tradeoffs."
        ),
        categories={
            "consensus": {
                "tone": "positive",
                "body": "Most active validators show excellent agreement across the scoring windows.",
            },
            "reliability": {
                "tone": "mixed",
                "body": "Incumbency and stable operation help the top cohort, but weaker operators remain.",
            },
            "software": {
                "tone": "neutral",
                "body": "Current software is common enough that it does not drive most score separation.",
            },
            "diversity": {
                "tone": "warning",
                "body": "Country and provider concentration still limit the network's resilience profile.",
            },
            "identity": {
                "tone": "mixed",
                "body": "Verified domains improve accountability, but many validators still lack that signal.",
            },
        },
    )


def _make_scoring_result(
    network_report: NetworkReport | None = None,
    network_summary: str = "Network is healthy with good geographic distribution.",
):
    return ScoringResult(
        validator_scores=[
            ValidatorScore(
                master_key="nHUkhbZe9ncdmhn6dbd5x7391ymwCS3YZEMWjysP9fSiDtau9YEe",
                score=85,
                consensus=90,
                reliability=88,
                software=80,
                diversity=75,
                identity=70,
                reasoning="Strong consensus participation with high uptime.",
            )
        ],
        network_summary=network_summary,
        network_report=network_report,
        raw_response='{"v001": {"score": 85}}',
        complete=True,
        errors=[],
    )


def _make_unl_result():
    return UNLSelectionResult(
        unl=["nHUkhbZe9ncdmhn6dbd5x7391ymwCS3YZEMWjysP9fSiDtau9YEe"],
        alternates=[],
    )


SAMPLE_RAW_EVIDENCE = {
    "vhs_validators": {"validators": [{"master_key": "nHU..."}]},
    "vhs_topology": {"nodes": [{"ip": "1.2.3.4"}]},
    "crawl_probes": [{"ip": "1.2.3.4", "pubkey_validator": "nHU..."}],
    "asn_lookups": {"1.2.3.4": {"asn": 20473, "as_name": "AS-VULTR"}},
    "geoip_lookups": {"1.2.3.4": {"country": "US"}},
}

SAMPLE_SIGNED_VL = {
    "public_key": "ED3F1E0DA736FCF99BE2880A60DBD470715C0E04DD793FB862236B070571FC09E2",
    "manifest": "JAAAAAFxIe0/Hg2nNvz5m+KICmDb1HBxXA4E3Xk/uGIjawcFcfwJ4g==",
    "blobs_v2": [{"blob": "eyJ...", "signature": "3045..."}],
    "version": 2,
}

SAMPLE_PROMPT_MESSAGES = [
    {"role": "system", "content": "Score validators."},
    {
        "role": "user",
        "content": 'VALIDATOR DATA:\n[{"validator_id":"v001","domain":"postfiat.org"}]',
    },
]

SAMPLE_VALIDATOR_ID_MAP = {
    "v001": {
        "master_key": "nHUkhbZe9ncdmhn6dbd5x7391ymwCS3YZEMWjysP9fSiDtau9YEe",
        "signing_key": "n9Kc1swwT6uHYMv5feRTSTwtXtQgBWxDZrWDuHQj7fBTnQaoC9ux",
    },
}


def _capture_pin_directory(mock_ipfs, cid="QmRootCID") -> dict[str, bytes]:
    captured: dict[str, bytes] = {}

    def capture(files):
        captured.update(files)
        return cid

    mock_ipfs.pin_directory.side_effect = capture
    return captured


def _stored_files(cursor) -> dict[str, dict]:
    files = {}
    for execute_call in cursor.execute.call_args_list:
        params = execute_call.args[1]
        files[params[1]] = json.loads(params[2])
    return files


def _stored_private_files(cursor) -> dict[str, dict]:
    files = {}
    for execute_call in cursor.execute.call_args_list:
        params = execute_call.args[1]
        files[params[1]] = json.loads(params[2])
    return files


def _configure_publisher_settings(mock_settings):
    mock_settings.scoring_model_id = "test-model"
    mock_settings.scoring_model_name = "test"
    mock_settings.scoring_model_revision = "a" * 40
    mock_settings.scoring_service_git_commit = "b" * 40
    mock_settings.scoring_sglang_image_tag = "lmsysorg/sglang:test@sha256:" + "c" * 64
    mock_settings.scoring_gpu_type = "H100"
    mock_settings.scoring_quantization = ""
    mock_settings.scoring_attention_backend = ""
    mock_settings.scoring_tp = 1
    mock_settings.scoring_mem_fraction = "0.75"
    mock_settings.scoring_chunked_prefill = 4096
    mock_settings.scoring_max_reqs = 1
    mock_settings.scoring_reasoning_parser = "qwen3"
    mock_settings.sglang_flashinfer_workspace_size = "2147483648"
    mock_settings.scoring_temperature = 0
    mock_settings.scoring_max_tokens = 16384
    mock_settings.scoring_disable_thinking = True
    mock_settings.modal_request_timeout_seconds = 2100
    mock_settings.unl_score_cutoff = 40
    mock_settings.unl_max_size = 35
    mock_settings.unl_min_score_gap = 5
    mock_settings.pftl_network = "testnet"
    mock_settings.excluded_validator_server_version_set = frozenset({"3.0.0"})
    mock_settings.pinata_enabled = False
    mock_settings.ipfs_gateway_url = ""
    mock_settings.pinata_gateway_url = ""


# ---------------------------------------------------------------------------
# _content_hash
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_deterministic(self):
        data = {"key": "value", "nested": {"a": 1}}
        assert _content_hash(data) == _content_hash(data)

    def test_key_order_independent(self):
        data_a = {"b": 2, "a": 1}
        data_b = {"a": 1, "b": 2}
        assert _content_hash(data_a) == _content_hash(data_b)

    def test_different_data_different_hash(self):
        assert _content_hash({"a": 1}) != _content_hash({"a": 2})


# ---------------------------------------------------------------------------
# _build_verification_hashes
# ---------------------------------------------------------------------------


class TestBuildVerificationHashes:
    def test_hashes_only_verifier_output_targets(self):
        files = {
            "outputs/model_response.json": {"raw_response": "{}"},
            "outputs/validator_scores.json": {"validator_scores": []},
            "outputs/selected_unl.json": {"unl": [], "alternates": []},
            "outputs/signed_validator_list.json": {"version": 2},
            "runtime/execution_manifest.json": {"schema_version": 1},
        }

        hashes = _build_verification_hashes(files)

        assert hashes == {
            "model_response_hash": _content_hash(files["outputs/model_response.json"]),
            "validator_scores_hash": _content_hash(files["outputs/validator_scores.json"]),
            "selected_unl_hash": _content_hash(files["outputs/selected_unl.json"]),
            "signed_validator_list_hash": _content_hash(
                files["outputs/signed_validator_list.json"]
            ),
        }

    def test_omits_missing_targets(self):
        files = {
            "outputs/selected_unl.json": {"unl": ["nHUvalidator"], "alternates": []},
            "outputs/signed_validator_list.json": {"version": 2},
        }

        hashes = _build_verification_hashes(files)

        assert hashes == {
            "selected_unl_hash": _content_hash(files["outputs/selected_unl.json"]),
            "signed_validator_list_hash": _content_hash(
                files["outputs/signed_validator_list.json"]
            ),
        }


# ---------------------------------------------------------------------------
# _build_model_request / _build_execution_manifest
# ---------------------------------------------------------------------------


class TestBuildModelRequest:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_includes_openai_chat_completion_payload(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        request = _build_model_request(SAMPLE_PROMPT_MESSAGES)

        assert request["method"] == "chat.completions.create"
        assert request["model"] == "test-model"
        assert request["messages"] == SAMPLE_PROMPT_MESSAGES
        assert request["temperature"] == 0
        assert request["max_tokens"] == 16384
        assert request["response_format"] == {"type": "json_object"}
        assert request["extra_body"] == QWEN_NON_THINKING_EXTRA_BODY


class TestBuildExecutionManifest:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_normal_round_manifest_includes_execution_contract(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        manifest = _build_execution_manifest(
            round_kind="normal",
            network="testnet",
            published_at=FIXED_TIME,
            round_number=9,
            signed_vl=True,
        )

        assert manifest["schema_version"] == 1
        assert manifest["round"]["kind"] == "normal"
        assert manifest["round"]["inference_performed"] is True
        assert manifest["model"]["provider"] == "huggingface"
        assert manifest["model"]["revision"] == "a" * 40
        assert manifest["runtime"]["kind"] == "modal_sglang"
        assert manifest["runtime"]["image"].endswith("@" + "sha256:" + "c" * 64)
        assert manifest["request"]["file"] == "inputs/model_request.json"
        assert manifest["code"]["commit"] == "b" * 40
        assert manifest["code"]["collector"] == {
            "module": "scoring_service.services.collector",
            "version": "git:" + "b" * 40,
            "parameters": {
                "excluded_validator_server_versions": ["3.0.0"],
            },
        }
        assert manifest["code"]["prompt"]["template_path"] == "prompts/scoring_v5.txt"
        assert manifest["code"]["selector"]["parameters"] == {
            "score_cutoff": 40,
            "max_size": 35,
            "min_score_gap": 5,
        }
        assert manifest["code"]["vl_generator"]["version"] == "git:" + "b" * 40

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_parser_and_selector_publish_source_content_sha256(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        manifest = _build_execution_manifest(
            round_kind="normal",
            network="testnet",
            published_at=FIXED_TIME,
            round_number=11,
            signed_vl=True,
        )

        expected_parser_hash = hashlib.sha256(
            Path(response_parser.__file__).read_bytes()
        ).hexdigest()
        expected_selector_hash = hashlib.sha256(
            Path(unl_selector.__file__).read_bytes()
        ).hexdigest()

        assert manifest["code"]["parser"]["content_sha256"] == expected_parser_hash
        assert manifest["code"]["selector"]["content_sha256"] == expected_selector_hash
        assert manifest["code"]["parser"]["version"] == "git:" + "b" * 40
        assert manifest["code"]["selector"]["version"] == "git:" + "b" * 40
        assert "content_sha256" not in manifest["code"]["collector"]
        assert "content_sha256" not in manifest["code"]["vl_generator"]

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_collector_exclusion_policy_is_sorted_in_manifest(self, mock_settings):
        _configure_publisher_settings(mock_settings)
        mock_settings.excluded_validator_server_version_set = frozenset({
            "3.0.0",
            "2.9.0",
            "1.0.0",
        })

        manifest = _build_execution_manifest(
            round_kind="normal",
            network="testnet",
            published_at=FIXED_TIME,
        )

        assert manifest["code"]["collector"]["parameters"][
            "excluded_validator_server_versions"
        ] == ["1.0.0", "2.9.0", "3.0.0"]

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_dry_run_manifest_includes_collector_exclusion_policy(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        manifest = _build_execution_manifest(
            round_kind="dry_run",
            network="testnet",
            published_at=FIXED_TIME,
            dry_run_id=303,
        )

        assert manifest["round"]["inference_performed"] is True
        assert manifest["code"]["collector"]["parameters"][
            "excluded_validator_server_versions"
        ] == ["3.0.0"]

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_runtime_manifest_includes_optional_modal_launch_args(self, mock_settings):
        _configure_publisher_settings(mock_settings)
        mock_settings.scoring_quantization = "fp8"
        mock_settings.scoring_attention_backend = "flashinfer"

        manifest = _build_execution_manifest(
            round_kind="normal",
            network="testnet",
            published_at=FIXED_TIME,
        )

        launch_args = manifest["runtime"]["launch_args"]
        assert launch_args[launch_args.index("--quantization") + 1] == "fp8"
        assert launch_args[launch_args.index("--attention-backend") + 1] == "flashinfer"

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_override_manifest_excludes_inference_sections(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        manifest = _build_execution_manifest(
            round_kind="override",
            network="testnet",
            published_at=FIXED_TIME,
            round_number=10,
            override={"type": "custom", "reason": "operator selected UNL"},
            signed_vl=True,
        )

        assert manifest["round"]["inference_performed"] is False
        assert manifest["override"]["type"] == "custom"
        assert "model" not in manifest
        assert "runtime" not in manifest
        assert "request" not in manifest
        assert set(manifest["code"].keys()) == {
            "repository",
            "commit",
            "vl_generator",
        }
        assert "collector" not in manifest["code"]


# ---------------------------------------------------------------------------
# _build_input_package_files
# ---------------------------------------------------------------------------


class TestBuildInputPackageFiles:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_contains_only_pre_inference_package_files(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        files = _build_input_package_files(
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            input_frozen_at=FIXED_TIME,
            round_number=1,
            prompt_messages=SAMPLE_PROMPT_MESSAGES,
            validator_id_map=SAMPLE_VALIDATOR_ID_MAP,
        )

        expected_paths = {
            "bundle.json",
            "inputs/validator_evidence.json",
            "inputs/model_request.json",
            "inputs/validator_map.json",
            "runtime/execution_manifest.json",
            "raw/vhs_validators.json",
            "raw/vhs_topology.json",
            "raw/crawl_probes.json",
            "raw/asn_lookups.json",
            "raw/geolocation_lookups.json",
        }
        assert set(files) == expected_paths
        assert all(not path.startswith("outputs/") for path in files)
        assert files["inputs/model_request.json"]["messages"] == SAMPLE_PROMPT_MESSAGES
        assert files["inputs/validator_map.json"] == SAMPLE_VALIDATOR_ID_MAP

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_bundle_indexes_only_input_package_files(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        files = _build_input_package_files(
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            input_frozen_at=FIXED_TIME,
            round_number=7,
            prompt_messages=SAMPLE_PROMPT_MESSAGES,
            validator_id_map=SAMPLE_VALIDATOR_ID_MAP,
        )

        bundle = files["bundle.json"]
        assert bundle["package_kind"] == "input"
        assert bundle["round_kind"] == "normal"
        assert bundle["round_number"] == 7
        assert bundle["input_frozen_at"] == FIXED_TIME.isoformat()
        assert "bundle.json" not in bundle["file_hashes"]
        assert set(bundle["file_hashes"]) == set(files) - {"bundle.json"}
        assert set(bundle["entrypoints"]) == {
            "validator_evidence",
            "model_request",
            "validator_map",
            "execution_manifest",
        }

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_includes_expected_raw_files_when_sources_are_empty(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        files = _build_input_package_files(
            snapshot=_make_snapshot(),
            raw_evidence={},
            input_frozen_at=FIXED_TIME,
            round_number=1,
            prompt_messages=SAMPLE_PROMPT_MESSAGES,
            validator_id_map=SAMPLE_VALIDATOR_ID_MAP,
        )

        assert files["raw/vhs_validators.json"] == {"validators": []}
        assert files["raw/vhs_topology.json"] == {"nodes": []}
        assert files["raw/crawl_probes.json"] == []
        assert files["raw/asn_lookups.json"] == {}
        assert files["raw/geolocation_lookups.json"] == {}


# ---------------------------------------------------------------------------
# _build_scores
# ---------------------------------------------------------------------------


class TestBuildScores:
    def test_includes_all_validator_fields(self):
        result = _make_scoring_result()
        scores = _build_scores(result)

        assert len(scores["validator_scores"]) == 1
        v = scores["validator_scores"][0]
        assert v["master_key"] == "nHUkhbZe9ncdmhn6dbd5x7391ymwCS3YZEMWjysP9fSiDtau9YEe"
        assert v["score"] == 85
        assert v["consensus"] == 90
        assert v["reliability"] == 88
        assert v["software"] == 80
        assert v["diversity"] == 75
        assert v["identity"] == 70
        assert v["reasoning"] == "Strong consensus participation with high uptime."

    def test_includes_network_summary(self):
        result = _make_scoring_result()
        scores = _build_scores(result)

        assert scores["network_summary"] == "Network is healthy with good geographic distribution."

    def test_includes_network_report_when_present(self):
        report = _make_network_report()
        result = _make_scoring_result(network_report=report)
        scores = _build_scores(result)

        assert scores["network_report"] == report.model_dump(mode="json")

    def test_includes_network_summary_and_report_when_both_present(self):
        report = _make_network_report()
        result = _make_scoring_result(network_report=report)
        scores = _build_scores(result)

        assert scores["network_summary"] == "Network is healthy with good geographic distribution."
        assert scores["network_report"] == report.model_dump(mode="json")

    def test_omits_empty_network_summary_for_report_only_result(self):
        report = _make_network_report()
        result = _make_scoring_result(network_report=report, network_summary="")
        scores = _build_scores(result)

        assert "network_summary" not in scores
        assert scores["network_report"] == report.model_dump(mode="json")


# ---------------------------------------------------------------------------
# _build_unl
# ---------------------------------------------------------------------------


class TestBuildUNL:
    def test_includes_unl_and_alternates(self):
        unl_result = UNLSelectionResult(
            unl=["key_a", "key_b"],
            alternates=["key_c"],
        )
        unl = _build_unl(unl_result)

        assert unl["unl"] == ["key_a", "key_b"]
        assert unl["alternates"] == ["key_c"]

    def test_empty_lists(self):
        unl_result = UNLSelectionResult(unl=[], alternates=[])
        unl = _build_unl(unl_result)

        assert unl["unl"] == []
        assert unl["alternates"] == []


# ---------------------------------------------------------------------------
# _build_bundle
# ---------------------------------------------------------------------------


class TestBuildBundle:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_indexes_staged_files(self, mock_settings):
        _configure_publisher_settings(mock_settings)
        files = {
            "inputs/validator_evidence.json": {"round": 1},
            "runtime/execution_manifest.json": {"schema_version": 1},
            "outputs/selected_unl.json": {"unl": []},
        }

        bundle = _build_bundle(
            files,
            round_kind="normal",
            network="testnet",
            published_at=FIXED_TIME,
            round_number=42,
        )

        assert bundle["bundle_version"] == 2
        assert bundle["round_kind"] == "normal"
        assert bundle["round_number"] == 42
        assert bundle["geolocation_attribution"] == "IP geolocation by DB-IP.com"
        assert bundle["entrypoints"] == {
            "validator_evidence": "inputs/validator_evidence.json",
            "execution_manifest": "runtime/execution_manifest.json",
            "selected_unl": "outputs/selected_unl.json",
        }
        assert "bundle.json" not in bundle["file_hashes"]
        assert set(bundle["file_hashes"]) == set(files)

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_dry_run_bundle_uses_private_identifier(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        bundle = _build_bundle(
            {"outputs/selected_unl.json": {"unl": []}},
            round_kind="dry_run",
            network="testnet",
            published_at=FIXED_TIME,
            dry_run_id=303,
        )

        assert bundle["dry_run"] is True
        assert bundle["dry_run_id"] == 303
        assert "round_number" not in bundle


class TestCollectGatewayUrls:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_returns_empty_when_neither_configured(self, mock_settings):
        mock_settings.ipfs_gateway_url = ""
        mock_settings.pinata_gateway_url = ""
        assert _collect_gateway_urls() == []

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_includes_primary_only(self, mock_settings):
        mock_settings.ipfs_gateway_url = "https://ipfs.example.com"
        mock_settings.pinata_gateway_url = ""
        assert _collect_gateway_urls() == ["https://ipfs.example.com"]

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_includes_both_providers(self, mock_settings):
        mock_settings.ipfs_gateway_url = "https://ipfs.example.com"
        mock_settings.pinata_gateway_url = "https://pinata.example.com"
        result = _collect_gateway_urls()
        assert result == ["https://ipfs.example.com", "https://pinata.example.com"]

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_strips_trailing_slashes(self, mock_settings):
        mock_settings.ipfs_gateway_url = "https://ipfs.example.com/"
        mock_settings.pinata_gateway_url = "https://pinata.example.com/"
        result = _collect_gateway_urls()
        assert result == ["https://ipfs.example.com", "https://pinata.example.com"]


# ---------------------------------------------------------------------------
# _store_audit_trail_files / get_audit_trail_file
# ---------------------------------------------------------------------------


class TestStoreAndGetAuditTrailFiles:
    def test_inserts_all_files(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        files = {
            "bundle.json": {"round_number": 1},
            "inputs/validator_evidence.json": {"round": 1},
        }
        _store_audit_trail_files(conn, 1, files)

        assert cursor.execute.call_count == 2

    def test_uses_correct_round_and_path(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        _store_audit_trail_files(
            conn,
            5,
            {"outputs/validator_scores.json": {"data": True}},
        )

        call_args = cursor.execute.call_args[0]
        params = call_args[1]
        assert params[0] == 5
        assert params[1] == "outputs/validator_scores.json"

    def test_get_returns_content_when_present(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = ({"round": 1},)

        result = get_audit_trail_file(conn, 1, "inputs/validator_evidence.json")
        assert result == {"round": 1}

    def test_get_returns_none_when_missing(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        result = get_audit_trail_file(conn, 1, "nonexistent.json")
        assert result is None

    def test_get_selected_unl_prefers_staged_path(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = ({"unl": ["nHUstaged"], "alternates": []},)

        result = get_selected_unl_file(conn, 1)

        assert result == {"unl": ["nHUstaged"], "alternates": []}
        params = cursor.execute.call_args.args[1]
        assert "outputs/selected_unl.json" in params[1]
        assert "unl.json" in params[1]


# ---------------------------------------------------------------------------
# _store_input_package_files / get_input_package_file
# ---------------------------------------------------------------------------


class TestStoreAndGetInputPackageFiles:
    def test_inserts_into_dedicated_input_package_table(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        _store_input_package_files(
            conn,
            5,
            {"bundle.json": {"package_kind": "input"}},
        )

        sql = cursor.execute.call_args.args[0]
        params = cursor.execute.call_args.args[1]
        assert "input_package_files" in sql
        assert "audit_trail_files" not in sql
        assert "ON CONFLICT" not in sql
        assert params[0] == 5
        assert params[1] == "bundle.json"

    def test_get_returns_content_when_present(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = ({"package_kind": "input"},)

        result = get_input_package_file(conn, 1, "bundle.json")

        assert result == {"package_kind": "input"}
        sql = cursor.execute.call_args.args[0]
        assert "input_package_files" in sql

    def test_get_returns_none_when_missing(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        result = get_input_package_file(conn, 1, "bundle.json")

        assert result is None


# ---------------------------------------------------------------------------
# IPFSPublisherService.publish_input_package
# ---------------------------------------------------------------------------


class TestPublishInputPackage:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_pins_and_stores_input_only_package(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        pinned_files = _capture_pin_directory(mock_ipfs, cid="QmInputCID")
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        publication = service.publish_input_package(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            conn=conn,
            prompt_messages=SAMPLE_PROMPT_MESSAGES,
            validator_id_map=SAMPLE_VALIDATOR_ID_MAP,
        )

        assert publication is not None
        assert publication.cid == "QmInputCID"
        assert publication.model_request["messages"] == SAMPLE_PROMPT_MESSAGES
        assert publication.validator_id_map == SAMPLE_VALIDATOR_ID_MAP
        assert set(publication.files) == set(pinned_files)
        assert all(not path.startswith("outputs/") for path in pinned_files)

        bundle = json.loads(pinned_files["bundle.json"])
        assert publication.package_hash == _content_hash(bundle)
        assert bundle["package_kind"] == "input"
        assert "final_bundle_cid" not in bundle

        stored_files = _stored_files(cursor)
        assert set(stored_files) == set(pinned_files)
        insert_sql = cursor.execute.call_args_list[0].args[0]
        assert "input_package_files" in insert_sql
        assert "audit_trail_files" not in insert_sql
        conn.commit.assert_not_called()

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_returns_none_when_input_package_pin_fails(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = None
        conn = MagicMock()

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        publication = service.publish_input_package(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            conn=conn,
            prompt_messages=SAMPLE_PROMPT_MESSAGES,
            validator_id_map=SAMPLE_VALIDATOR_ID_MAP,
        )

        assert publication is None
        conn.commit.assert_not_called()

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_rolls_back_when_input_package_storage_fails(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmInputCID"
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("DB write failed")
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        with pytest.raises(Exception, match="DB write failed"):
            service.publish_input_package(
                round_number=1,
                snapshot=_make_snapshot(),
                raw_evidence=SAMPLE_RAW_EVIDENCE,
                conn=conn,
                prompt_messages=SAMPLE_PROMPT_MESSAGES,
                validator_id_map=SAMPLE_VALIDATOR_ID_MAP,
            )

        conn.rollback.assert_called_once()

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_replicates_input_package_to_pinata_with_distinct_name(self, mock_settings):
        _configure_publisher_settings(mock_settings)
        mock_settings.pinata_enabled = True

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmInputCID"
        mock_pinata = MagicMock()
        mock_pinata.pin_by_cid.return_value = True
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(
            ipfs_client=mock_ipfs,
            pinata_client=mock_pinata,
        )
        publication = service.publish_input_package(
            round_number=7,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            conn=conn,
            prompt_messages=SAMPLE_PROMPT_MESSAGES,
            validator_id_map=SAMPLE_VALIDATOR_ID_MAP,
        )

        assert publication is not None
        mock_pinata.pin_by_cid.assert_called_once_with(
            "QmInputCID",
            name="dynamic-unl-scoring-input-round-7",
        )


# ---------------------------------------------------------------------------
# IPFSPublisherService.publish
# ---------------------------------------------------------------------------


class TestPublish:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_returns_cid_on_success(self, mock_settings):
        mock_settings.scoring_model_id = "Qwen/Qwen3.6-27B-FP8"
        mock_settings.scoring_model_name = "qwen36-27b-fp8"
        mock_settings.scoring_disable_thinking = True
        mock_settings.pinata_enabled = False
        mock_settings.ipfs_gateway_url = ""
        mock_settings.pinata_gateway_url = ""

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        cid = service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        assert cid == "QmRootCID"
        mock_ipfs.pin_directory.assert_called_once()
        conn.commit.assert_called_once()

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_returns_none_when_ipfs_fails(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"
        mock_settings.pinata_enabled = False
        mock_settings.ipfs_gateway_url = ""
        mock_settings.pinata_gateway_url = ""

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = None
        conn = MagicMock()

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        cid = service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        assert cid is None
        conn.commit.assert_not_called()

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_rolls_back_on_db_error(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"
        mock_settings.pinata_enabled = False
        mock_settings.ipfs_gateway_url = ""
        mock_settings.pinata_gateway_url = ""

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("DB write failed")
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        with pytest.raises(Exception, match="DB write failed"):
            service.publish(
                round_number=1,
                snapshot=_make_snapshot(),
                raw_evidence=SAMPLE_RAW_EVIDENCE,
                scoring_result=_make_scoring_result(),
                unl_result=_make_unl_result(),
                signed_vl=SAMPLE_SIGNED_VL,
                conn=conn,
            )

        conn.rollback.assert_called_once()

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_assembles_correct_file_set(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        pinned_files = _capture_pin_directory(mock_ipfs)
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        expected_paths = {
            "bundle.json",
            "inputs/validator_evidence.json",
            "inputs/model_request.json",
            "inputs/validator_map.json",
            "runtime/execution_manifest.json",
            "outputs/model_response.json",
            "outputs/validator_scores.json",
            "outputs/selected_unl.json",
            "outputs/signed_validator_list.json",
            "outputs/verification_hashes.json",
            "raw/vhs_validators.json",
            "raw/vhs_topology.json",
            "raw/crawl_probes.json",
            "raw/asn_lookups.json",
            "raw/geolocation_lookups.json",
        }
        assert set(pinned_files.keys()) == expected_paths

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_includes_llm_reproducibility_artifacts(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        pinned_files = _capture_pin_directory(mock_ipfs)
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        scoring_result = _make_scoring_result()

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=scoring_result,
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
            prompt_messages=SAMPLE_PROMPT_MESSAGES,
            validator_id_map=SAMPLE_VALIDATOR_ID_MAP,
        )

        model_request = json.loads(pinned_files["inputs/model_request.json"])
        validator_id_map = json.loads(pinned_files["inputs/validator_map.json"])
        raw_response = json.loads(pinned_files["outputs/model_response.json"])

        assert model_request["messages"] == SAMPLE_PROMPT_MESSAGES
        assert validator_id_map == SAMPLE_VALIDATOR_ID_MAP
        assert raw_response["raw_response"] == scoring_result.raw_response
        assert SAMPLE_VALIDATOR_ID_MAP["v001"]["master_key"] not in model_request["messages"][1]["content"]
        assert SAMPLE_VALIDATOR_ID_MAP["v001"]["signing_key"] not in model_request["messages"][1]["content"]

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_final_bundle_references_and_reuses_frozen_input_package(
        self,
        mock_settings,
    ):
        _configure_publisher_settings(mock_settings)

        pinned_directories = []

        def capture(files):
            pinned_directories.append(files.copy())
            return "QmInputCID" if len(pinned_directories) == 1 else "QmRootCID"

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.side_effect = capture
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        input_package = service.publish_input_package(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            conn=conn,
            prompt_messages=SAMPLE_PROMPT_MESSAGES,
            validator_id_map=SAMPLE_VALIDATOR_ID_MAP,
        )
        assert input_package is not None
        cid = service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence={},
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
            input_package=input_package,
        )

        assert cid == "QmRootCID"
        input_bundle = json.loads(pinned_directories[0]["bundle.json"])
        final_files = pinned_directories[1]
        final_bundle = json.loads(final_files["bundle.json"])
        assert final_bundle["package_kind"] == "final"
        assert final_bundle["input_package"] == {
            "cid": "QmInputCID",
            "bundle_hash": _content_hash(input_bundle),
            "frozen_at": input_package.frozen_at.isoformat(),
        }

        for shared_path, expected_hash in input_bundle["file_hashes"].items():
            assert shared_path in final_files
            assert _content_hash(json.loads(final_files[shared_path])) == expected_hash

        assert "outputs/model_response.json" in final_bundle["file_hashes"]
        assert "outputs/signed_validator_list.json" in final_bundle["file_hashes"]

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_scores_json_serializes_network_report(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        report = _make_network_report()

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(
                network_report=report,
                network_summary="",
            ),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        pinned_files = mock_ipfs.pin_directory.call_args[0][0]
        scores = json.loads(pinned_files["outputs/validator_scores.json"])
        assert "network_summary" not in scores
        assert scores["network_report"] == report.model_dump(mode="json")

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_pinned_files_are_bytes(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"
        mock_settings.pinata_enabled = False
        mock_settings.ipfs_gateway_url = ""
        mock_settings.pinata_gateway_url = ""

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        pinned_files = mock_ipfs.pin_directory.call_args[0][0]
        for path, content in pinned_files.items():
            assert isinstance(content, bytes), f"{path} content should be bytes"
            json.loads(content)  # must be valid JSON

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_bundle_includes_attribution(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        pinned_files = mock_ipfs.pin_directory.call_args[0][0]
        bundle = json.loads(pinned_files["bundle.json"])
        assert bundle["geolocation_attribution"] == "IP geolocation by DB-IP.com"
        assert "final_bundle_cid" not in bundle

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_bundle_includes_file_hashes(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        pinned_files = mock_ipfs.pin_directory.call_args[0][0]
        bundle = json.loads(pinned_files["bundle.json"])
        file_hashes = bundle["file_hashes"]
        assert "inputs/validator_evidence.json" in file_hashes
        assert "inputs/model_request.json" in file_hashes
        assert "inputs/validator_map.json" in file_hashes
        assert "outputs/model_response.json" in file_hashes
        assert "outputs/validator_scores.json" in file_hashes
        assert "outputs/verification_hashes.json" in file_hashes
        assert "raw/vhs_validators.json" in file_hashes
        assert "bundle.json" not in file_hashes
        assert all(len(h) == 64 for h in file_hashes.values())

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_verification_hashes_cover_normal_round_outputs(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        pinned_files = mock_ipfs.pin_directory.call_args[0][0]
        verification_hashes = json.loads(pinned_files["outputs/verification_hashes.json"])
        bundle = json.loads(pinned_files["bundle.json"])

        assert verification_hashes == {
            "model_response_hash": _content_hash(
                json.loads(pinned_files["outputs/model_response.json"])
            ),
            "validator_scores_hash": _content_hash(
                json.loads(pinned_files["outputs/validator_scores.json"])
            ),
            "selected_unl_hash": _content_hash(
                json.loads(pinned_files["outputs/selected_unl.json"])
            ),
            "signed_validator_list_hash": _content_hash(
                json.loads(pinned_files["outputs/signed_validator_list.json"])
            ),
        }
        assert "outputs/verification_hashes.json" in bundle["file_hashes"]
        assert "bundle.json" not in verification_hashes

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_stores_all_files_in_db(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        assert cursor.execute.call_count == 15

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_includes_signed_vl(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        pinned_files = mock_ipfs.pin_directory.call_args[0][0]
        vl = json.loads(pinned_files["outputs/signed_validator_list.json"])
        assert vl["version"] == 2
        assert vl["public_key"] == SAMPLE_SIGNED_VL["public_key"]


# ---------------------------------------------------------------------------
# IPFSPublisherService.publish_dry_run
# ---------------------------------------------------------------------------


class TestPublishDryRun:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_stores_review_files_without_ipfs_pinning(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        scoring_result = _make_scoring_result()

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish_dry_run(
            dry_run_id=101,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=scoring_result,
            unl_result=_make_unl_result(),
            conn=conn,
            prompt_messages=SAMPLE_PROMPT_MESSAGES,
            validator_id_map=SAMPLE_VALIDATOR_ID_MAP,
        )

        mock_ipfs.pin_directory.assert_not_called()
        conn.commit.assert_called_once()

        stored_files = _stored_private_files(cursor)
        expected_paths = {
            "bundle.json",
            "inputs/validator_evidence.json",
            "inputs/model_request.json",
            "inputs/validator_map.json",
            "runtime/execution_manifest.json",
            "outputs/model_response.json",
            "outputs/validator_scores.json",
            "outputs/selected_unl.json",
            "outputs/verification_hashes.json",
            "raw/vhs_validators.json",
            "raw/vhs_topology.json",
            "raw/crawl_probes.json",
            "raw/asn_lookups.json",
            "raw/geolocation_lookups.json",
        }
        assert set(stored_files.keys()) == expected_paths
        assert "outputs/signed_validator_list.json" not in stored_files
        assert stored_files["inputs/validator_evidence.json"]["dry_run_id"] == 101
        assert "round_number" not in stored_files["inputs/validator_evidence.json"]
        assert stored_files["inputs/model_request.json"]["messages"] == SAMPLE_PROMPT_MESSAGES
        assert stored_files["inputs/validator_map.json"] == SAMPLE_VALIDATOR_ID_MAP
        assert stored_files["outputs/model_response.json"]["raw_response"] == scoring_result.raw_response
        assert set(stored_files["outputs/verification_hashes.json"]) == {
            "model_response_hash",
            "validator_scores_hash",
            "selected_unl_hash",
        }

        insert_sql = cursor.execute.call_args_list[0].args[0]
        assert "dry_run_artifacts" in insert_sql
        assert "audit_trail_files" not in insert_sql

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_bundle_uses_dry_run_id_without_cid(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        service.publish_dry_run(
            dry_run_id=303,
            snapshot=_make_snapshot(round_number=303),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            conn=conn,
        )

        bundle = _stored_private_files(cursor)["bundle.json"]
        manifest = _stored_private_files(cursor)["runtime/execution_manifest.json"]
        assert bundle["dry_run_id"] == 303
        assert "round_number" not in bundle
        assert bundle["dry_run"] is True
        assert "final_bundle_cid" not in bundle
        assert "outputs/signed_validator_list.json" not in bundle["file_hashes"]
        assert "outputs/verification_hashes.json" in bundle["file_hashes"]
        assert "signed_validator_list_hash" not in _stored_private_files(cursor)[
            "outputs/verification_hashes.json"
        ]
        assert manifest["round"]["kind"] == "dry_run"
        assert manifest["round"]["dry_run_id"] == 303

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_rolls_back_on_db_error(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("DB write failed")
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        with pytest.raises(Exception, match="DB write failed"):
            service.publish_dry_run(
                dry_run_id=101,
                snapshot=_make_snapshot(),
                raw_evidence=SAMPLE_RAW_EVIDENCE,
                scoring_result=_make_scoring_result(),
                unl_result=_make_unl_result(),
                conn=conn,
            )

        mock_ipfs.pin_directory.assert_not_called()
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# IPFSPublisherService Pinata integration
# ---------------------------------------------------------------------------


class TestPublishWithPinata:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_replicates_to_pinata_after_primary_pin(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"
        mock_settings.pinata_enabled = True
        mock_settings.ipfs_gateway_url = ""
        mock_settings.pinata_gateway_url = ""

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        mock_pinata = MagicMock()
        mock_pinata.pin_by_cid.return_value = True
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs, pinata_client=mock_pinata)
        cid = service.publish(
            round_number=7,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        assert cid == "QmRootCID"
        mock_pinata.pin_by_cid.assert_called_once_with(
            "QmRootCID", name="dynamic-unl-scoring-round-7"
        )
        conn.commit.assert_called_once()

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_pinata_failure_does_not_fail_round(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"
        mock_settings.pinata_enabled = True
        mock_settings.ipfs_gateway_url = ""
        mock_settings.pinata_gateway_url = ""

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        mock_pinata = MagicMock()
        mock_pinata.pin_by_cid.return_value = False  # Pinata fails
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs, pinata_client=mock_pinata)
        cid = service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        # Primary CID is still returned — secondary failure is non-blocking
        assert cid == "QmRootCID"
        mock_pinata.pin_by_cid.assert_called_once()
        conn.commit.assert_called_once()

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_pinata_not_called_when_primary_pin_fails(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"
        mock_settings.pinata_enabled = True
        mock_settings.ipfs_gateway_url = ""
        mock_settings.pinata_gateway_url = ""

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = None  # primary fails
        mock_pinata = MagicMock()
        conn = MagicMock()

        service = IPFSPublisherService(ipfs_client=mock_ipfs, pinata_client=mock_pinata)
        cid = service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        assert cid is None
        mock_pinata.pin_by_cid.assert_not_called()

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_skips_pinata_when_not_configured(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"
        mock_settings.pinata_enabled = False
        mock_settings.ipfs_gateway_url = ""
        mock_settings.pinata_gateway_url = ""

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        # No pinata_client passed — publisher constructs default based on settings
        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        cid = service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        assert cid == "QmRootCID"
        assert service._pinata is None

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_bundle_includes_both_gateway_urls(self, mock_settings):
        _configure_publisher_settings(mock_settings)
        mock_settings.pinata_enabled = True
        mock_settings.ipfs_gateway_url = "https://ipfs.example.com"
        mock_settings.pinata_gateway_url = "https://gateway.pinata.cloud/ipfs/"

        mock_ipfs = MagicMock()
        mock_ipfs.pin_directory.return_value = "QmRootCID"
        mock_pinata = MagicMock()
        mock_pinata.pin_by_cid.return_value = True
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs, pinata_client=mock_pinata)
        service.publish(
            round_number=1,
            snapshot=_make_snapshot(),
            raw_evidence=SAMPLE_RAW_EVIDENCE,
            scoring_result=_make_scoring_result(),
            unl_result=_make_unl_result(),
            signed_vl=SAMPLE_SIGNED_VL,
            conn=conn,
        )

        pinned_files = mock_ipfs.pin_directory.call_args[0][0]
        bundle = json.loads(pinned_files["bundle.json"])
        assert bundle["gateway_urls"] == [
            "https://ipfs.example.com",
            "https://gateway.pinata.cloud/ipfs",
        ]


# ---------------------------------------------------------------------------
# IPFSPublisherService.publish_override
# ---------------------------------------------------------------------------


class TestPublishOverride:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_override_bundle_is_pinned_with_override_details(self, mock_settings):
        _configure_publisher_settings(mock_settings)

        mock_ipfs = MagicMock()
        pinned_files = _capture_pin_directory(mock_ipfs, cid="QmOverrideCID")
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        service = IPFSPublisherService(ipfs_client=mock_ipfs)
        cid = service.publish_override(
            round_number=12,
            master_keys=["nHUvalidator"],
            signed_vl=SAMPLE_SIGNED_VL,
            override_type="custom",
            override_reason="operator selected UNL",
            conn=conn,
        )

        assert cid == "QmOverrideCID"
        assert set(pinned_files.keys()) == {
            "bundle.json",
            "runtime/execution_manifest.json",
            "outputs/selected_unl.json",
            "outputs/signed_validator_list.json",
            "outputs/verification_hashes.json",
        }

        bundle = json.loads(pinned_files["bundle.json"])
        manifest = json.loads(pinned_files["runtime/execution_manifest.json"])
        verification_hashes = json.loads(pinned_files["outputs/verification_hashes.json"])
        assert "final_bundle_cid" not in bundle
        assert bundle["override"] == {
            "type": "custom",
            "reason": "operator selected UNL",
        }
        assert set(bundle["file_hashes"].keys()) == {
            "runtime/execution_manifest.json",
            "outputs/selected_unl.json",
            "outputs/signed_validator_list.json",
            "outputs/verification_hashes.json",
        }
        assert verification_hashes == {
            "selected_unl_hash": _content_hash(
                json.loads(pinned_files["outputs/selected_unl.json"])
            ),
            "signed_validator_list_hash": _content_hash(
                json.loads(pinned_files["outputs/signed_validator_list.json"])
            ),
        }
        assert manifest["round"]["inference_performed"] is False
        assert "model" not in manifest
        assert "request" not in manifest
