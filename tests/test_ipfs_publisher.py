"""Tests for the IPFS audit trail publisher service."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from scoring_service.models import (
    AgreementScore,
    ScoringSnapshot,
    ValidatorProfile,
)
from scoring_service.services.ipfs_publisher import (
    IPFSPublisherService,
    _build_metadata,
    _build_scores,
    _build_scoring_config,
    _build_unl,
    _content_hash,
    _store_audit_trail_files,
    get_audit_trail_file,
)
from scoring_service.services.response_parser import ScoringResult, ValidatorScore
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


def _make_scoring_result():
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
        network_summary="Network is healthy with good geographic distribution.",
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
# _build_scoring_config
# ---------------------------------------------------------------------------


class TestBuildScoringConfig:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_includes_model_source(self, mock_settings):
        mock_settings.scoring_model_id = "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
        mock_settings.scoring_model_name = "qwen3-next-80b-instruct"

        config = _build_scoring_config(FIXED_TIME)

        assert config["model_source"] == "https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
        assert config["model_id"] == "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
        assert config["model_name"] == "qwen3-next-80b-instruct"

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_includes_inference_params(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"
        mock_settings.scoring_temperature = 0
        mock_settings.scoring_max_tokens = 16384

        config = _build_scoring_config(FIXED_TIME)

        assert config["temperature"] == 0
        assert config["max_tokens"] == 16384
        assert config["prompt_version"] == "v2"

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_includes_timestamp(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"

        config = _build_scoring_config(FIXED_TIME)

        assert config["scored_at"] == "2026-04-06T12:00:00+00:00"


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
# _build_metadata
# ---------------------------------------------------------------------------


class TestBuildMetadata:
    def test_includes_attribution(self):
        metadata = _build_metadata(1, {}, "QmTestCID", FIXED_TIME)

        assert metadata["geolocation_attribution"] == "IP geolocation by DB-IP.com"

    def test_includes_round_and_cid(self):
        metadata = _build_metadata(42, {}, "QmRootCID", FIXED_TIME)

        assert metadata["round_number"] == 42
        assert metadata["ipfs_cid"] == "QmRootCID"

    def test_includes_file_hashes(self):
        hashes = {"snapshot.json": "abc123", "scores.json": "def456"}
        metadata = _build_metadata(1, hashes, "QmCID", FIXED_TIME)

        assert metadata["file_hashes"] == hashes

    def test_includes_timestamp(self):
        metadata = _build_metadata(1, {}, "QmCID", FIXED_TIME)

        assert metadata["published_at"] == "2026-04-06T12:00:00+00:00"


# ---------------------------------------------------------------------------
# _store_audit_trail_files / get_audit_trail_file
# ---------------------------------------------------------------------------


class TestStoreAndGetAuditTrailFiles:
    def test_inserts_all_files(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        files = {
            "snapshot.json": {"round": 1},
            "metadata.json": {"round_number": 1},
        }
        _store_audit_trail_files(conn, 1, files)

        assert cursor.execute.call_count == 2

    def test_uses_correct_round_and_path(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        _store_audit_trail_files(conn, 5, {"scores.json": {"data": True}})

        call_args = cursor.execute.call_args[0]
        params = call_args[1]
        assert params[0] == 5
        assert params[1] == "scores.json"

    def test_get_returns_content_when_present(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = ({"round": 1},)

        result = get_audit_trail_file(conn, 1, "snapshot.json")
        assert result == {"round": 1}

    def test_get_returns_none_when_missing(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        result = get_audit_trail_file(conn, 1, "nonexistent.json")
        assert result is None


# ---------------------------------------------------------------------------
# IPFSPublisherService.publish
# ---------------------------------------------------------------------------


class TestPublish:
    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_returns_cid_on_success(self, mock_settings):
        mock_settings.scoring_model_id = "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
        mock_settings.scoring_model_name = "qwen3-next-80b-instruct"

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
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"

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
        expected_paths = {
            "snapshot.json",
            "scoring_config.json",
            "scores.json",
            "unl.json",
            "vl.json",
            "raw/vhs_validators.json",
            "raw/vhs_topology.json",
            "raw/crawl_probes.json",
            "raw/asn_lookups.json",
            "raw/geoip_lookups.json",
            "metadata.json",
        }
        assert set(pinned_files.keys()) == expected_paths

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_pinned_files_are_bytes(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"

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
    def test_metadata_includes_attribution(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"

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
        metadata = json.loads(pinned_files["metadata.json"])
        assert metadata["geolocation_attribution"] == "IP geolocation by DB-IP.com"
        assert metadata["ipfs_cid"] == "QmRootCID"

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_metadata_includes_file_hashes(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"

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
        metadata = json.loads(pinned_files["metadata.json"])
        file_hashes = metadata["file_hashes"]
        assert "snapshot.json" in file_hashes
        assert "scores.json" in file_hashes
        assert "raw/vhs_validators.json" in file_hashes
        assert all(len(h) == 64 for h in file_hashes.values())

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_stores_all_files_in_db(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"

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

        # 11 files: snapshot, scoring_config, scores, unl, vl, 5 raw, metadata
        assert cursor.execute.call_count == 11

    @patch("scoring_service.services.ipfs_publisher.settings")
    def test_includes_signed_vl(self, mock_settings):
        mock_settings.scoring_model_id = "test-model"
        mock_settings.scoring_model_name = "test"

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
        vl = json.loads(pinned_files["vl.json"])
        assert vl["version"] == 2
        assert vl["public_key"] == SAMPLE_SIGNED_VL["public_key"]
