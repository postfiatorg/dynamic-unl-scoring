"""Tests for the CrawlClient validator IP resolution."""

from unittest.mock import MagicMock, patch

import httpx

from scoring_service.clients.crawl import CrawlClient
from scoring_service.constants import PEER_PROTOCOL_PORT


MASTER_KEYS = {"nHBvalidator1", "nHBvalidator2", "nHBvalidator3"}

TOPOLOGY_NODES = [
    {"ip": "10.0.0.1", "port": PEER_PROTOCOL_PORT, "node_public_key": "n9node1"},
    {"ip": "10.0.0.2", "port": PEER_PROTOCOL_PORT, "node_public_key": "n9node2"},
    {"ip": "10.0.0.3", "port": PEER_PROTOCOL_PORT, "node_public_key": "n9node3"},
    {"ip": "10.0.0.4", "port": PEER_PROTOCOL_PORT, "node_public_key": "n9node4"},
]


def _crawl_response(pubkey_validator=None):
    """Build a mock /crawl JSON response."""
    server = {"server_state": "full", "version": "3.0.0"}
    if pubkey_validator:
        server["pubkey_validator"] = pubkey_validator
    return {"server": server, "overlay": [], "unl": {}}


def _mock_response(json_data, status_code=200):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


class TestProbeNode:
    @patch.object(httpx.Client, "get")
    def test_extracts_pubkey_validator(self, mock_get):
        mock_get.return_value = _mock_response(_crawl_response("nHBvalidator1"))
        client = CrawlClient()
        result = client._probe_node("10.0.0.1", PEER_PROTOCOL_PORT)
        assert result == "nHBvalidator1"
        mock_get.assert_called_once_with(f"https://10.0.0.1:{PEER_PROTOCOL_PORT}/crawl")

    @patch.object(httpx.Client, "get")
    def test_returns_none_on_missing_pubkey(self, mock_get):
        mock_get.return_value = _mock_response(_crawl_response())
        client = CrawlClient()
        result = client._probe_node("10.0.0.1", PEER_PROTOCOL_PORT)
        assert result is None

    @patch.object(httpx.Client, "get")
    def test_returns_none_on_missing_server_section(self, mock_get):
        mock_get.return_value = _mock_response({"overlay": []})
        client = CrawlClient()
        result = client._probe_node("10.0.0.1", PEER_PROTOCOL_PORT)
        assert result is None

    @patch.object(httpx.Client, "get")
    def test_returns_none_on_timeout(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("Connection timed out")
        client = CrawlClient()
        result = client._probe_node("10.0.0.1", PEER_PROTOCOL_PORT)
        assert result is None

    @patch.object(httpx.Client, "get")
    def test_returns_none_on_connect_error(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        client = CrawlClient()
        result = client._probe_node("10.0.0.1", PEER_PROTOCOL_PORT)
        assert result is None


class TestResolveValidators:
    @patch.object(CrawlClient, "_probe_node")
    def test_resolves_matching_validators(self, mock_probe):
        mock_probe.side_effect = ["nHBvalidator1", "nHBvalidator2", None, None]
        client = CrawlClient()
        result = client.resolve_validators(TOPOLOGY_NODES, MASTER_KEYS)
        assert result == {"nHBvalidator1": "10.0.0.1", "nHBvalidator2": "10.0.0.2"}

    @patch.object(CrawlClient, "_probe_node")
    def test_skips_non_validators(self, mock_probe):
        mock_probe.side_effect = ["nHBunknown_key", None, None, None]
        client = CrawlClient()
        result = client.resolve_validators(TOPOLOGY_NODES, MASTER_KEYS)
        assert result == {}

    @patch.object(CrawlClient, "_probe_node")
    def test_skips_nodes_with_null_ip(self, mock_probe):
        nodes = [
            {"ip": None, "port": PEER_PROTOCOL_PORT, "node_public_key": "n9null"},
            {"ip": "10.0.0.1", "port": PEER_PROTOCOL_PORT, "node_public_key": "n9node1"},
        ]
        mock_probe.return_value = "nHBvalidator1"
        client = CrawlClient()
        result = client.resolve_validators(nodes, MASTER_KEYS)
        assert result == {"nHBvalidator1": "10.0.0.1"}
        mock_probe.assert_called_once_with("10.0.0.1", PEER_PROTOCOL_PORT)

    @patch.object(CrawlClient, "_probe_node")
    def test_uses_default_port_when_missing(self, mock_probe):
        nodes = [{"ip": "10.0.0.1", "port": None, "node_public_key": "n9node1"}]
        mock_probe.return_value = "nHBvalidator1"
        client = CrawlClient()
        client.resolve_validators(nodes, MASTER_KEYS)
        mock_probe.assert_called_once_with("10.0.0.1", PEER_PROTOCOL_PORT)

    @patch.object(CrawlClient, "_probe_node")
    def test_returns_empty_for_empty_topology(self, mock_probe):
        client = CrawlClient()
        result = client.resolve_validators([], MASTER_KEYS)
        assert result == {}
        mock_probe.assert_not_called()

    @patch.object(CrawlClient, "_probe_node")
    def test_mixed_topology(self, mock_probe):
        """Some nodes resolve, some fail, some aren't validators."""
        nodes = [
            {"ip": "10.0.0.1", "port": PEER_PROTOCOL_PORT, "node_public_key": "n9a"},
            {"ip": "10.0.0.2", "port": PEER_PROTOCOL_PORT, "node_public_key": "n9b"},
            {"ip": None, "port": None, "node_public_key": "n9c"},
            {"ip": "10.0.0.4", "port": PEER_PROTOCOL_PORT, "node_public_key": "n9d"},
            {"ip": "10.0.0.5", "port": PEER_PROTOCOL_PORT, "node_public_key": "n9e"},
        ]
        mock_probe.side_effect = [
            "nHBvalidator1",    # matches
            None,               # unreachable
            # null IP skipped
            "nHBunknown",       # not a validator
            "nHBvalidator3",    # matches
        ]
        client = CrawlClient()
        result = client.resolve_validators(nodes, MASTER_KEYS)
        assert result == {"nHBvalidator1": "10.0.0.1", "nHBvalidator3": "10.0.0.5"}
