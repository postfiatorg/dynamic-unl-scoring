"""Tests for the GeoIPClient MaxMind geolocation."""

from unittest.mock import MagicMock, patch

import geoip2.errors

from scoring_service.clients.geoip import GeoIPClient
from scoring_service.models import GeoLocation, ValidatorProfile


def _make_validator(ip=None):
    return ValidatorProfile(
        master_key="nHBtest",
        signing_key="n9test",
        ip=ip,
    )


def _mock_insights_response(continent="North America", country="United States", region="New Jersey", city="Piscataway"):
    response = MagicMock()
    response.continent.name = continent
    response.country.name = country
    response.subdivisions.most_specific.name = region
    response.city.name = city
    return response


class TestLookup:
    @patch("scoring_service.clients.geoip.geoip2.webservice.Client")
    def test_returns_geolocation_for_valid_ip(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.insights.return_value = _mock_insights_response()
        mock_client_cls.return_value = mock_client

        client = GeoIPClient(account_id="123", license_key="abc")
        result = client.lookup("149.28.100.5")

        assert result is not None
        assert result.continent == "North America"
        assert result.country == "United States"
        assert result.region == "New Jersey"
        assert result.city == "Piscataway"
        mock_client.insights.assert_called_once_with("149.28.100.5")

    @patch("scoring_service.clients.geoip.geoip2.webservice.Client")
    def test_returns_none_for_null_ip(self, mock_client_cls):
        mock_client_cls.return_value = MagicMock()
        client = GeoIPClient(account_id="123", license_key="abc")

        assert client.lookup(None) is None
        assert client.lookup("") is None

    @patch("scoring_service.clients.geoip.geoip2.webservice.Client")
    def test_returns_empty_geolocation_for_unknown_ip(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.insights.side_effect = geoip2.errors.AddressNotFoundError("not found")
        mock_client_cls.return_value = mock_client

        client = GeoIPClient(account_id="123", license_key="abc")
        result = client.lookup("192.0.2.1")

        assert result is not None
        assert result.continent is None
        assert result.country is None

    @patch("scoring_service.clients.geoip.geoip2.webservice.Client")
    def test_returns_empty_geolocation_on_auth_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.insights.side_effect = geoip2.errors.AuthenticationError("invalid key")
        mock_client_cls.return_value = mock_client

        client = GeoIPClient(account_id="123", license_key="bad")
        result = client.lookup("149.28.100.5")

        assert result is not None
        assert result.continent is None

    @patch("scoring_service.clients.geoip.geoip2.webservice.Client")
    def test_returns_empty_geolocation_on_generic_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.insights.side_effect = geoip2.errors.GeoIP2Error("service unavailable")
        mock_client_cls.return_value = mock_client

        client = GeoIPClient(account_id="123", license_key="abc")
        result = client.lookup("149.28.100.5")

        assert result is not None
        assert result.continent is None

    @patch("scoring_service.clients.geoip.settings")
    def test_returns_none_when_credentials_missing(self, mock_settings):
        mock_settings.maxmind_account_id = ""
        mock_settings.maxmind_license_key = ""
        client = GeoIPClient(account_id="", license_key="")

        assert client.lookup("149.28.100.5") is None
        assert client._client is None


class TestEnrichValidators:
    @patch("scoring_service.clients.geoip.geoip2.webservice.Client")
    def test_enriches_validators_with_ips(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.insights.return_value = _mock_insights_response()
        mock_client_cls.return_value = mock_client

        v = _make_validator(ip="149.28.100.5")
        client = GeoIPClient(account_id="123", license_key="abc")
        client.enrich_validators([v])

        assert v.geolocation == GeoLocation(
            continent="North America",
            country="United States",
            region="New Jersey",
            city="Piscataway",
        )

    @patch("scoring_service.clients.geoip.geoip2.webservice.Client")
    def test_null_ip_validators_get_none_geolocation(self, mock_client_cls):
        mock_client_cls.return_value = MagicMock()

        v = _make_validator(ip=None)
        client = GeoIPClient(account_id="123", license_key="abc")
        client.enrich_validators([v])

        assert v.geolocation is None

    @patch("scoring_service.clients.geoip.geoip2.webservice.Client")
    def test_mixed_validators(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.insights.side_effect = [
            _mock_insights_response(),
            geoip2.errors.AddressNotFoundError("not found"),
        ]
        mock_client_cls.return_value = mock_client

        validators = [
            _make_validator(ip="149.28.100.5"),
            _make_validator(ip=None),
            _make_validator(ip="192.0.2.1"),
        ]
        client = GeoIPClient(account_id="123", license_key="abc")
        client.enrich_validators(validators)

        assert validators[0].geolocation is not None
        assert validators[0].geolocation.country == "United States"
        assert validators[1].geolocation is None
        assert validators[2].geolocation is not None
        assert validators[2].geolocation.country is None

    @patch("scoring_service.clients.geoip.settings")
    def test_no_op_when_credentials_missing(self, mock_settings):
        mock_settings.maxmind_account_id = ""
        mock_settings.maxmind_license_key = ""
        validators = [
            _make_validator(ip="149.28.100.5"),
            _make_validator(ip=None),
        ]
        client = GeoIPClient(account_id="", license_key="")
        client.enrich_validators(validators)

        assert validators[0].geolocation is None
        assert validators[1].geolocation is None

    @patch("scoring_service.clients.geoip.geoip2.webservice.Client")
    def test_empty_validator_list(self, mock_client_cls):
        mock_client_cls.return_value = MagicMock()

        client = GeoIPClient(account_id="123", license_key="abc")
        client.enrich_validators([])
