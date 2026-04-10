"""Tests for the DataCollectorService."""

from unittest.mock import MagicMock, patch

from scoring_service.models import ValidatorProfile
from scoring_service.services.collector import DataCollectorService, _content_hash


def _make_validators():
    return [
        ValidatorProfile(master_key="nHBval1", signing_key="n9sign1"),
        ValidatorProfile(master_key="nHBval2", signing_key="n9sign2"),
    ]


VHS_RAW = {"validators": [{"master_key": "nHBval1"}, {"master_key": "nHBval2"}]}
TOPOLOGY_RAW = {"nodes": [{"ip": "10.0.0.1", "node_public_key": "n9node1"}]}
TOPOLOGY_PARSED = [{"ip": "10.0.0.1", "port": 2559, "node_public_key": "n9node1"}]
CRAWL_RAW = [{"ip": "10.0.0.1", "port": 2559, "pubkey_validator": "nHBval1"}]
ASN_RAW = {"10.0.0.1": {"asn": 20473, "as_name": "Choopa, LLC"}}
GEOIP_RAW = {"10.0.0.1": {"country": "United States"}}


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
    def test_skips_archival_when_raw_is_none(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        mock_vhs = MagicMock()
        mock_vhs.fetch_validators.return_value = ([], None)
        mock_vhs.fetch_topology.return_value = ([], None)

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
        assert len(insert_calls) == 0
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
