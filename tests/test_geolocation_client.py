"""Tests for the GeolocationClient DB-IP Lite geolocation."""

from unittest.mock import MagicMock, patch

from scoring_service.clients.geolocation import GeolocationClient
from scoring_service.models import GeoLocation, ValidatorProfile


def _make_validator(ip=None):
    return ValidatorProfile(
        master_key="nHBtest",
        signing_key="n9test",
        ip=ip,
    )


DBIP_RECORD_US = {
    "country": {"names": {"en": "United States"}},
}

DBIP_RECORD_DE = {
    "country": {"names": {"en": "Germany"}},
}


class TestLookup:
    @patch("scoring_service.clients.geolocation.maxminddb")
    @patch("scoring_service.clients.geolocation.DBIP_PATH")
    def test_returns_geolocation_for_valid_ip(self, mock_path, mock_mmdb):
        mock_path.exists.return_value = True
        mock_reader = MagicMock()
        mock_reader.get.return_value = DBIP_RECORD_US
        mock_mmdb.open_database.return_value = mock_reader

        client = GeolocationClient()
        result = client.lookup("144.202.24.188")

        assert result is not None
        assert result.country == "United States"
        mock_reader.get.assert_called_once_with("144.202.24.188")

    @patch("scoring_service.clients.geolocation.maxminddb")
    @patch("scoring_service.clients.geolocation.DBIP_PATH")
    def test_returns_none_for_null_ip(self, mock_path, mock_mmdb):
        mock_path.exists.return_value = True
        mock_mmdb.open_database.return_value = MagicMock()

        client = GeolocationClient()
        assert client.lookup(None) is None
        assert client.lookup("") is None

    @patch("scoring_service.clients.geolocation.maxminddb")
    @patch("scoring_service.clients.geolocation.DBIP_PATH")
    def test_returns_empty_geolocation_for_unknown_ip(self, mock_path, mock_mmdb):
        mock_path.exists.return_value = True
        mock_reader = MagicMock()
        mock_reader.get.return_value = None
        mock_mmdb.open_database.return_value = mock_reader

        client = GeolocationClient()
        result = client.lookup("192.0.2.1")

        assert result is not None
        assert result.country is None

    @patch("scoring_service.clients.geolocation.maxminddb")
    @patch("scoring_service.clients.geolocation.DBIP_PATH")
    def test_returns_empty_geolocation_on_reader_error(self, mock_path, mock_mmdb):
        mock_path.exists.return_value = True
        mock_reader = MagicMock()
        mock_reader.get.side_effect = Exception("corrupt database")
        mock_mmdb.open_database.return_value = mock_reader

        client = GeolocationClient()
        result = client.lookup("144.202.24.188")

        assert result is not None
        assert result.country is None

    @patch("scoring_service.clients.geolocation.DBIP_PATH")
    def test_returns_none_when_database_missing(self, mock_path):
        mock_path.exists.return_value = False
        client = GeolocationClient()

        assert client.lookup("144.202.24.188") is None
        assert client._reader is None


class TestEnrichValidators:
    @patch("scoring_service.clients.geolocation.maxminddb")
    @patch("scoring_service.clients.geolocation.DBIP_PATH")
    def test_enriches_validators_with_ips(self, mock_path, mock_mmdb):
        mock_path.exists.return_value = True
        mock_reader = MagicMock()
        mock_reader.get.return_value = DBIP_RECORD_US
        mock_mmdb.open_database.return_value = mock_reader

        v = _make_validator(ip="144.202.24.188")
        client = GeolocationClient()
        raw = client.enrich_validators([v])

        assert v.geolocation == GeoLocation(country="United States")
        assert "144.202.24.188" in raw
        assert raw["144.202.24.188"]["country"] == "United States"

    @patch("scoring_service.clients.geolocation.maxminddb")
    @patch("scoring_service.clients.geolocation.DBIP_PATH")
    def test_null_ip_validators_get_none_geolocation(self, mock_path, mock_mmdb):
        mock_path.exists.return_value = True
        mock_mmdb.open_database.return_value = MagicMock()

        v = _make_validator(ip=None)
        client = GeolocationClient()
        raw = client.enrich_validators([v])

        assert v.geolocation is None
        assert raw == {}

    @patch("scoring_service.clients.geolocation.maxminddb")
    @patch("scoring_service.clients.geolocation.DBIP_PATH")
    def test_mixed_validators(self, mock_path, mock_mmdb):
        mock_path.exists.return_value = True
        mock_reader = MagicMock()
        mock_reader.get.side_effect = [DBIP_RECORD_US, None]
        mock_mmdb.open_database.return_value = mock_reader

        validators = [
            _make_validator(ip="144.202.24.188"),
            _make_validator(ip=None),
            _make_validator(ip="192.0.2.1"),
        ]
        client = GeolocationClient()
        raw = client.enrich_validators(validators)

        assert validators[0].geolocation is not None
        assert validators[0].geolocation.country == "United States"
        assert validators[1].geolocation is None
        assert validators[2].geolocation is not None
        assert validators[2].geolocation.country is None
        assert len(raw) == 2

    @patch("scoring_service.clients.geolocation.DBIP_PATH")
    def test_no_op_when_database_missing(self, mock_path):
        mock_path.exists.return_value = False
        validators = [
            _make_validator(ip="144.202.24.188"),
            _make_validator(ip=None),
        ]
        client = GeolocationClient()
        raw = client.enrich_validators(validators)

        assert validators[0].geolocation is None
        assert validators[1].geolocation is None
        assert raw == {"144.202.24.188": None}

    @patch("scoring_service.clients.geolocation.maxminddb")
    @patch("scoring_service.clients.geolocation.DBIP_PATH")
    def test_empty_validator_list(self, mock_path, mock_mmdb):
        mock_path.exists.return_value = True
        mock_mmdb.open_database.return_value = MagicMock()

        client = GeolocationClient()
        raw = client.enrich_validators([])
        assert raw == {}
