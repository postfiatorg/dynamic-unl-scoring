"""Tests for VHS data collection client."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from scoring_service.services.vhs_client import VHSClient, _parse_validator


VHS_VALIDATOR_RESPONSE = {
    "validators": [
        {
            "validation_public_key": "nHBtest1",
            "signing_key": "n9sign1",
            "master_key": "nHBtest1",
            "domain": "postfiat.org",
            "domain_verified": True,
            "server_version": "3.0.0",
            "unl": "rpc",
            "current_index": 914785,
            "partial": False,
            "base_fee": 10,
            "reserve_base": 10000000,
            "reserve_inc": 2000000,
            "agreement_1h": {"missed": 0, "total": 1194, "score": "1.00000", "incomplete": False},
            "agreement_24h": {"missed": 0, "total": 28672, "score": "1.00000", "incomplete": False},
            "agreement_30day": {"missed": 2, "total": 855080, "score": "1.00000", "incomplete": True},
        },
        {
            "validation_public_key": "nHBtest2",
            "signing_key": "n9sign2",
            "master_key": "nHBtest2",
            "domain": None,
            "domain_verified": None,
            "server_version": "3.0.0",
            "unl": False,
            "current_index": 914784,
            "partial": False,
            "base_fee": 10,
            "reserve_base": 10000000,
            "reserve_inc": 2000000,
            "agreement_1h": {"missed": 63, "total": 1194, "score": "0.94724", "incomplete": False},
            "agreement_24h": {"missed": 100, "total": 28672, "score": "0.99651", "incomplete": False},
            "agreement_30day": {"missed": 15897, "total": 358462, "score": "0.95565", "incomplete": False},
        },
    ]
}

def _mock_response(json_data, status_code=200):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


def _mock_error_response(status_code=500):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=response
    )
    return response


class TestParseValidator:
    def test_parses_full_validator(self):
        raw = VHS_VALIDATOR_RESPONSE["validators"][0]
        v = _parse_validator(raw)
        assert v.master_key == "nHBtest1"
        assert v.signing_key == "n9sign1"
        assert v.domain == "postfiat.org"
        assert v.domain_verified is True
        assert v.agreement_1h.score == 1.0
        assert v.agreement_1h.total == 1194
        assert v.agreement_1h.missed == 0
        assert v.agreement_30d.score == 1.0
        assert v.agreement_30d.total == 855080
        assert v.server_version == "3.0.0"
        assert v.unl is True
        assert v.base_fee == 10

    def test_normalizes_unl_string_to_true(self):
        raw = {**VHS_VALIDATOR_RESPONSE["validators"][0], "unl": "rpc"}
        v = _parse_validator(raw)
        assert v.unl is True

    def test_normalizes_unl_false(self):
        raw = {**VHS_VALIDATOR_RESPONSE["validators"][1], "unl": False}
        v = _parse_validator(raw)
        assert v.unl is False

    def test_handles_null_domain(self):
        raw = VHS_VALIDATOR_RESPONSE["validators"][1]
        v = _parse_validator(raw)
        assert v.domain is None
        assert v.domain_verified is None

    def test_falls_back_to_validation_public_key(self):
        raw = {"validation_public_key": "nHBfallback", "agreement_1h": {}, "agreement_24h": {}, "agreement_30day": {}}
        v = _parse_validator(raw)
        assert v.master_key == "nHBfallback"
        assert v.signing_key == "nHBfallback"

    def test_handles_missing_agreement_data(self):
        raw = {"master_key": "nHBtest", "signing_key": "n9test"}
        v = _parse_validator(raw)
        assert v.agreement_1h.score is None
        assert v.agreement_24h.score is None
        assert v.agreement_30d.score is None


class TestFetchValidators:
    @patch("scoring_service.services.vhs_client._request_with_retry")
    def test_returns_parsed_validators(self, mock_request):
        mock_request.return_value = VHS_VALIDATOR_RESPONSE
        client = VHSClient(base_url="https://vhs.test.postfiat.org")
        validators = client.fetch_validators()
        assert len(validators) == 2
        assert validators[0].master_key == "nHBtest1"
        assert validators[1].master_key == "nHBtest2"

    @patch("scoring_service.services.vhs_client._request_with_retry")
    def test_sorts_by_master_key(self, mock_request):
        reversed_validators = list(reversed(VHS_VALIDATOR_RESPONSE["validators"]))
        mock_request.return_value = {"validators": reversed_validators}
        client = VHSClient(base_url="https://vhs.test.postfiat.org")
        validators = client.fetch_validators()
        assert validators[0].master_key < validators[1].master_key

    @patch("scoring_service.services.vhs_client._request_with_retry")
    def test_returns_empty_on_vhs_failure(self, mock_request):
        mock_request.return_value = None
        client = VHSClient(base_url="https://vhs.test.postfiat.org")
        validators = client.fetch_validators()
        assert validators == []

    @patch("scoring_service.services.vhs_client._request_with_retry")
    def test_handles_dict_format_response(self, mock_request):
        mock_request.return_value = {
            "validators": {
                "key1": VHS_VALIDATOR_RESPONSE["validators"][0],
                "key2": VHS_VALIDATOR_RESPONSE["validators"][1],
            }
        }
        client = VHSClient(base_url="https://vhs.test.postfiat.org")
        validators = client.fetch_validators()
        assert len(validators) == 2


class TestRequestRetry:
    def test_retries_on_http_error(self):
        client_mock = MagicMock(spec=httpx.Client)
        client_mock.get.side_effect = [
            _mock_error_response(500),
            _mock_error_response(500),
            _mock_response({"validators": []}),
        ]
        from scoring_service.services.vhs_client import _request_with_retry
        with patch("scoring_service.services.vhs_client.time.sleep"):
            result = _request_with_retry(client_mock, "https://vhs.test/v1/network/validators")
        assert result == {"validators": []}
        assert client_mock.get.call_count == 3

    def test_returns_none_after_max_retries(self):
        client_mock = MagicMock(spec=httpx.Client)
        client_mock.get.side_effect = [
            _mock_error_response(500),
            _mock_error_response(500),
            _mock_error_response(500),
        ]
        from scoring_service.services.vhs_client import _request_with_retry
        with patch("scoring_service.services.vhs_client.time.sleep"):
            result = _request_with_retry(client_mock, "https://vhs.test/v1/network/validators")
        assert result is None
        assert client_mock.get.call_count == 3
