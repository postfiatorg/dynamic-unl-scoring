"""Tests for the ASNClient IP-to-ASN resolution."""

from unittest.mock import MagicMock, patch

from scoring_service.clients.asn import ASNClient
from scoring_service.models import ASNInfo, ValidatorProfile


def _make_validator(ip=None):
    return ValidatorProfile(
        master_key="nHBtest",
        signing_key="n9test",
        ip=ip,
    )


class TestLookup:
    @patch("scoring_service.clients.asn.pyasn.pyasn")
    def test_returns_asn_info_for_valid_ip(self, mock_pyasn_cls):
        db = MagicMock()
        db.lookup.return_value = (20473, "149.28.0.0/16")
        db.get_as_name.return_value = "Choopa, LLC"
        mock_pyasn_cls.return_value = db

        client = ASNClient()
        result = client.lookup("149.28.100.5")

        assert result is not None
        assert result.asn == 20473
        assert result.as_name == "Choopa, LLC"
        db.lookup.assert_called_once_with("149.28.100.5")

    @patch("scoring_service.clients.asn.pyasn.pyasn")
    def test_returns_none_for_null_ip(self, mock_pyasn_cls):
        mock_pyasn_cls.return_value = MagicMock()
        client = ASNClient()

        assert client.lookup(None) is None
        assert client.lookup("") is None

    @patch("scoring_service.clients.asn.pyasn.pyasn")
    def test_returns_empty_asn_info_for_missing_prefix(self, mock_pyasn_cls):
        db = MagicMock()
        db.lookup.return_value = (None, None)
        mock_pyasn_cls.return_value = db

        client = ASNClient()
        result = client.lookup("192.0.2.1")

        assert result is not None
        assert result.asn is None
        assert result.as_name is None

    @patch("scoring_service.clients.asn.pyasn.pyasn")
    def test_returns_empty_asn_info_for_invalid_ip(self, mock_pyasn_cls):
        db = MagicMock()
        db.lookup.side_effect = ValueError("not a valid IP")
        mock_pyasn_cls.return_value = db

        client = ASNClient()
        result = client.lookup("not-an-ip")

        assert result is not None
        assert result.asn is None
        assert result.as_name is None

    @patch("scoring_service.clients.asn.pyasn.pyasn")
    def test_handles_asn_with_no_name(self, mock_pyasn_cls):
        db = MagicMock()
        db.lookup.return_value = (64496, "198.51.100.0/24")
        db.get_as_name.return_value = None
        mock_pyasn_cls.return_value = db

        client = ASNClient()
        result = client.lookup("198.51.100.1")

        assert result is not None
        assert result.asn == 64496
        assert result.as_name is None


class TestEnrichValidators:
    @patch("scoring_service.clients.asn.pyasn.pyasn")
    def test_enriches_validators_with_ips(self, mock_pyasn_cls):
        db = MagicMock()
        db.lookup.return_value = (20473, "149.28.0.0/16")
        db.get_as_name.return_value = "Choopa, LLC"
        mock_pyasn_cls.return_value = db

        v = _make_validator(ip="149.28.100.5")
        client = ASNClient()
        raw = client.enrich_validators([v])

        assert v.asn == ASNInfo(asn=20473, as_name="Choopa, LLC")
        assert "149.28.100.5" in raw
        assert raw["149.28.100.5"]["asn"] == 20473

    @patch("scoring_service.clients.asn.pyasn.pyasn")
    def test_null_ip_validators_get_none_asn(self, mock_pyasn_cls):
        mock_pyasn_cls.return_value = MagicMock()

        v = _make_validator(ip=None)
        client = ASNClient()
        raw = client.enrich_validators([v])

        assert v.asn is None
        assert raw == {}

    @patch("scoring_service.clients.asn.pyasn.pyasn")
    def test_mixed_validators(self, mock_pyasn_cls):
        db = MagicMock()
        db.lookup.side_effect = [
            (20473, "149.28.0.0/16"),
            (None, None),
        ]
        db.get_as_name.return_value = "Choopa, LLC"
        mock_pyasn_cls.return_value = db

        validators = [
            _make_validator(ip="149.28.100.5"),
            _make_validator(ip=None),
            _make_validator(ip="192.0.2.1"),
        ]
        client = ASNClient()
        raw = client.enrich_validators(validators)

        assert validators[0].asn is not None
        assert validators[0].asn.asn == 20473
        assert validators[1].asn is None
        assert validators[2].asn is not None
        assert validators[2].asn.asn is None
        assert len(raw) == 2

    @patch("scoring_service.clients.asn.pyasn.pyasn")
    def test_empty_validator_list(self, mock_pyasn_cls):
        mock_pyasn_cls.return_value = MagicMock()

        client = ASNClient()
        raw = client.enrich_validators([])
        assert raw == {}
