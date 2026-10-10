"""Offline orchestration regressions for verification-before-sealing."""
from unittest.mock import MagicMock, patch

import pytest

from scoring_service.services import convergence_ingestion as ingestion


@pytest.mark.parametrize("failure", [RuntimeError("query failed"), ValueError("bad evidence")])
def test_failed_verification_defers_sealing_and_next_pass_recovers(failure):
    conn = MagicMock()
    client = MagicMock()
    stats = {"pages": 1, "reveals": 1}
    with (
        patch.object(ingestion, "get_db", return_value=conn),
        patch.object(ingestion, "read_cursor", return_value=20),
        patch.object(ingestion, "run_ingestion_pass", return_value=stats),
        patch.object(ingestion, "verify_active_rounds", side_effect=[failure, []]) as verify,
        patch.object(ingestion, "seal_due_rounds") as seal,
        patch.object(ingestion, "IPFSPublisherService") as ipfs,
        patch.object(ingestion, "OnChainPublisherService") as chain,
    ):
        assert ingestion._run_pass_with_own_connection(client, "synthetic") == stats
        verify.assert_called_once_with(conn)
        seal.assert_not_called()
        client.latest_validated_ledger_close_time.assert_not_called()
        ipfs.assert_not_called()
        chain.assert_not_called()
        conn.close.assert_called_once()
        assert conn.autocommit is True
        assert ingestion._run_pass_with_own_connection(client, "synthetic") == stats
        assert verify.call_count == 2
        seal.assert_called_once_with(
            conn, client.latest_validated_ledger_close_time.return_value,
            ipfs_publisher=ipfs.return_value, onchain_publisher=chain.return_value,
        )
        assert conn.close.call_count == 2


def test_successful_verification_precedes_sealing():
    conn = MagicMock()
    events = []
    with (
        patch.object(ingestion, "get_db", return_value=conn),
        patch.object(ingestion, "read_cursor", return_value=20),
        patch.object(ingestion, "run_ingestion_pass", return_value={"pages": 1}),
        patch.object(ingestion, "verify_active_rounds", side_effect=lambda _: events.append("verify")),
        patch.object(ingestion, "seal_due_rounds", side_effect=lambda *a, **k: events.append("seal")),
        patch.object(ingestion, "IPFSPublisherService"),
        patch.object(ingestion, "OnChainPublisherService"),
    ):
        ingestion._run_pass_with_own_connection(MagicMock(), "synthetic")
    assert events == ["verify", "seal"]
    conn.close.assert_called_once()
