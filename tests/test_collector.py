"""Tests for the DataCollectorService."""

import json
from unittest.mock import MagicMock, patch

import pytest

from scoring_service.models import ValidatorProfile
from scoring_service.services.collector import (
    DataCollectorService,
    _content_hash,
    _filter_eligible_validators,
)


def _make_validators():
    return [
        ValidatorProfile(
            master_key="nHBval1",
            signing_key="n9sign1",
            server_version="1.0.4",
        ),
        ValidatorProfile(
            master_key="nHBval2",
            signing_key="n9sign2",
            server_version="1.0.4",
        ),
    ]


VHS_RAW = {"validators": [{"master_key": "nHBval1"}, {"master_key": "nHBval2"}]}
TOPOLOGY_RAW = {"nodes": [{"ip": "10.0.0.1", "node_public_key": "n9node1"}]}
TOPOLOGY_PARSED = [{"ip": "10.0.0.1", "port": 2559, "node_public_key": "n9node1"}]
CRAWL_RAW = [{"ip": "10.0.0.1", "port": 2559, "pubkey_validator": "nHBval1"}]
ASN_RAW = {"10.0.0.1": {"asn": 20473, "as_name": "Choopa, LLC"}}
GEOIP_RAW = {"10.0.0.1": {"country": "United States"}}


class TestValidatorEligibility:
    def test_excludes_configured_server_versions_by_exact_match(self):
        validators = [
            ValidatorProfile(
                master_key="nHBcurrent",
                signing_key="n9current",
                server_version="1.0.4",
            ),
            ValidatorProfile(
                master_key="nHBlegacy",
                signing_key="n9legacy",
                server_version="3.0.0",
            ),
            ValidatorProfile(
                master_key="nHBfuture",
                signing_key="n9future",
                server_version="3.0.1",
            ),
        ]

        eligible, excluded = _filter_eligible_validators(
            validators,
            frozenset({"3.0.0"}),
        )

        assert [v.master_key for v in eligible] == ["nHBcurrent", "nHBfuture"]
        assert [v.master_key for v in excluded] == ["nHBlegacy"]

    def test_missing_and_malformed_versions_remain_eligible_unless_configured(self):
        validators = [
            ValidatorProfile(master_key="nHBmissing", signing_key="n9missing"),
            ValidatorProfile(
                master_key="nHBmalformed",
                signing_key="n9malformed",
                server_version="not-semver",
            ),
        ]

        eligible, excluded = _filter_eligible_validators(
            validators,
            frozenset({"3.0.0"}),
        )

        assert eligible == validators
        assert excluded == []


class TestCollect:
    @patch("scoring_service.services.collector.get_db")
    def test_full_collection_sequence(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        validators = _make_validators()

        mock_vhs = MagicMock()
        mock_vhs.fetch_validators.return_value = (validators, VHS_RAW)
        mock_vhs.fetch_topology.return_value = (TOPOLOGY_PARSED, TOPOLOGY_RAW)

        mock_crawl = MagicMock()
        mock_crawl.resolve_validators.return_value = ({"nHBval1": "10.0.0.1"}, CRAWL_RAW)

        mock_asn = MagicMock()
        mock_asn.enrich_validators.return_value = ASN_RAW

        mock_geoip = MagicMock()
        mock_geoip.enrich_validators.return_value = GEOIP_RAW

        service = DataCollectorService(
            vhs_client=mock_vhs,
            crawl_client=mock_crawl,
            asn_client=mock_asn,
            geoip_client=mock_geoip,
        )
        snapshot = service.collect(round_number=1, network="testnet")

        assert snapshot.round_number == 1
        assert snapshot.network == "testnet"
        assert len(snapshot.validators) == 2
        assert snapshot.validators[0].ip == "10.0.0.1"
        assert snapshot.validators[1].ip is None

        mock_vhs.fetch_validators.assert_called_once()
        mock_vhs.fetch_topology.assert_called_once()
        mock_crawl.resolve_validators.assert_called_once()
        mock_asn.enrich_validators.assert_called_once_with(validators)
        mock_geoip.enrich_validators.assert_called_once_with(validators)
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("scoring_service.services.collector.get_db")
    def test_excludes_configured_versions_before_scoring_snapshot(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        validators = [
            ValidatorProfile(
                master_key="nHBcurrent",
                signing_key="n9current",
                server_version="1.0.4",
            ),
            ValidatorProfile(
                master_key="nHBlegacy",
                signing_key="n9legacy",
                server_version="3.0.0",
            ),
            ValidatorProfile(master_key="nHBmissing", signing_key="n9missing"),
            ValidatorProfile(
                master_key="nHBmalformed",
                signing_key="n9malformed",
                server_version="not-semver",
            ),
        ]
        raw_validators = {
            "validators": [
                {"master_key": v.master_key, "server_version": v.server_version}
                for v in validators
            ],
        }

        mock_vhs = MagicMock()
        mock_vhs.fetch_validators.return_value = (validators, raw_validators)
        mock_vhs.fetch_topology.return_value = (TOPOLOGY_PARSED, TOPOLOGY_RAW)

        mock_crawl = MagicMock()
        mock_crawl.resolve_validators.return_value = (
            {
                "nHBcurrent": "10.0.0.1",
                "nHBlegacy": "10.0.0.2",
                "nHBmissing": "10.0.0.3",
            },
            CRAWL_RAW,
        )

        mock_asn = MagicMock()
        mock_asn.enrich_validators.return_value = ASN_RAW

        mock_geoip = MagicMock()
        mock_geoip.enrich_validators.return_value = GEOIP_RAW

        service = DataCollectorService(
            vhs_client=mock_vhs,
            crawl_client=mock_crawl,
            asn_client=mock_asn,
            geoip_client=mock_geoip,
        )
        snapshot = service.collect(round_number=1, network="testnet")

        assert [v.master_key for v in snapshot.validators] == [
            "nHBcurrent",
            "nHBmissing",
            "nHBmalformed",
        ]
        assert snapshot.validators[0].ip == "10.0.0.1"
        assert snapshot.validators[1].ip == "10.0.0.3"
        assert snapshot.validators[2].ip is None

        mock_crawl.resolve_validators.assert_called_once_with(
            TOPOLOGY_PARSED,
            {"nHBcurrent", "nHBmissing", "nHBmalformed"},
        )
        mock_asn.enrich_validators.assert_called_once_with(snapshot.validators)
        mock_geoip.enrich_validators.assert_called_once_with(snapshot.validators)

        vhs_insert = next(
            c for c in mock_cursor.execute.call_args_list
            if c[0][1][1] == "vhs_validators"
        )
        saved_raw = json.loads(vhs_insert[0][1][2])
        saved_master_keys = {
            validator["master_key"]
            for validator in saved_raw["validators"]
        }
        assert "nHBlegacy" in saved_master_keys

    @patch("scoring_service.services.collector.get_db")
    def test_saves_five_raw_evidence_rows(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        mock_vhs = MagicMock()
        mock_vhs.fetch_validators.return_value = (_make_validators(), VHS_RAW)
        mock_vhs.fetch_topology.return_value = (TOPOLOGY_PARSED, TOPOLOGY_RAW)

        mock_crawl = MagicMock()
        mock_crawl.resolve_validators.return_value = ({}, CRAWL_RAW)

        mock_asn = MagicMock()
        mock_asn.enrich_validators.return_value = ASN_RAW

        mock_geoip = MagicMock()
        mock_geoip.enrich_validators.return_value = GEOIP_RAW

        service = DataCollectorService(
            vhs_client=mock_vhs,
            crawl_client=mock_crawl,
            asn_client=mock_asn,
            geoip_client=mock_geoip,
        )
        service.collect(round_number=1, network="testnet")

        insert_calls = [c for c in mock_cursor.execute.call_args_list if "INSERT INTO raw_evidence" in str(c)]
        assert len(insert_calls) == 5

    @patch("scoring_service.services.collector.get_db")
    def test_publishable_flag_true_for_all_sources(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        mock_vhs = MagicMock()
        mock_vhs.fetch_validators.return_value = (_make_validators(), VHS_RAW)
        mock_vhs.fetch_topology.return_value = (TOPOLOGY_PARSED, TOPOLOGY_RAW)

        mock_crawl = MagicMock()
        mock_crawl.resolve_validators.return_value = ({}, CRAWL_RAW)

        mock_asn = MagicMock()
        mock_asn.enrich_validators.return_value = ASN_RAW

        mock_geoip = MagicMock()
        mock_geoip.enrich_validators.return_value = GEOIP_RAW

        service = DataCollectorService(
            vhs_client=mock_vhs,
            crawl_client=mock_crawl,
            asn_client=mock_asn,
            geoip_client=mock_geoip,
        )
        service.collect(round_number=1, network="testnet")

        insert_calls = mock_cursor.execute.call_args_list
        for c in insert_calls:
            if "INSERT INTO raw_evidence" in str(c):
                args = c[0][1]
                publishable = args[4]
                assert publishable is True

    @patch("scoring_service.services.collector.get_db")
    def test_rolls_back_on_failure(self, mock_get_db):
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn

        mock_vhs = MagicMock()
        mock_vhs.fetch_validators.side_effect = RuntimeError("VHS down")

        service = DataCollectorService(
            vhs_client=mock_vhs,
            crawl_client=MagicMock(),
            asn_client=MagicMock(),
            geoip_client=MagicMock(),
        )

        try:
            service.collect(round_number=1, network="testnet")
        except RuntimeError:
            pass

        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("scoring_service.services.collector.get_db")
    def test_fails_when_vhs_validators_raw_evidence_is_missing(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        mock_vhs = MagicMock()
        mock_vhs.fetch_validators.return_value = ([], None)

        service = DataCollectorService(
            vhs_client=mock_vhs,
            crawl_client=MagicMock(),
            asn_client=MagicMock(),
            geoip_client=MagicMock(),
        )

        with pytest.raises(RuntimeError, match="VHS validators response unavailable"):
            service.collect(round_number=1, network="testnet")

        mock_conn.rollback.assert_called_once()

    @patch("scoring_service.services.collector.get_db")
    def test_successful_empty_vhs_response_produces_empty_snapshot(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        mock_vhs = MagicMock()
        mock_vhs.fetch_validators.return_value = ([], {"validators": []})
        mock_vhs.fetch_topology.return_value = ([], {"nodes": []})

        mock_crawl = MagicMock()
        mock_crawl.resolve_validators.return_value = ({}, [])

        mock_asn = MagicMock()
        mock_asn.enrich_validators.return_value = {}

        mock_geoip = MagicMock()
        mock_geoip.enrich_validators.return_value = {}

        service = DataCollectorService(
            vhs_client=mock_vhs,
            crawl_client=mock_crawl,
            asn_client=mock_asn,
            geoip_client=mock_geoip,
        )
        snapshot = service.collect(round_number=1, network="testnet")

        insert_calls = [c for c in mock_cursor.execute.call_args_list if "INSERT INTO raw_evidence" in str(c)]
        assert len(insert_calls) == 2
        assert len(snapshot.validators) == 0

    @patch("scoring_service.services.collector.get_db")
    def test_snapshot_has_content_hash(self, mock_get_db):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()
        mock_get_db.return_value = mock_conn

        mock_vhs = MagicMock()
        mock_vhs.fetch_validators.return_value = (_make_validators(), VHS_RAW)
        mock_vhs.fetch_topology.return_value = (TOPOLOGY_PARSED, TOPOLOGY_RAW)

        mock_crawl = MagicMock()
        mock_crawl.resolve_validators.return_value = ({}, CRAWL_RAW)

        mock_asn = MagicMock()
        mock_asn.enrich_validators.return_value = ASN_RAW

        mock_geoip = MagicMock()
        mock_geoip.enrich_validators.return_value = GEOIP_RAW

        service = DataCollectorService(
            vhs_client=mock_vhs,
            crawl_client=mock_crawl,
            asn_client=mock_asn,
            geoip_client=mock_geoip,
        )
        snapshot = service.collect(round_number=1, network="testnet")

        content_hash = snapshot.content_hash()
        assert len(content_hash) == 64
        assert content_hash == snapshot.content_hash()


class TestContentHash:
    def test_deterministic(self):
        data = {"key": "value", "number": 42}
        assert _content_hash(data) == _content_hash(data)

    def test_different_data_different_hash(self):
        assert _content_hash({"a": 1}) != _content_hash({"a": 2})

    def test_key_order_independent(self):
        assert _content_hash({"b": 2, "a": 1}) == _content_hash({"a": 1, "b": 2})
