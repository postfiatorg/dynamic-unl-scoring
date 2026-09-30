"""Transaction recovery and connection ownership for private dry-runs."""
from unittest.mock import MagicMock
import pytest
from scoring_service.services import orchestrator as module

class TransactionConnection:
    def __init__(self, fail_status, fail_recording=False):
        self.fail_status, self.fail_recording = fail_status, fail_recording
        self.aborted, self.events, self.failure = False, [], None
    def cursor(self):
        cursor = MagicMock()
        cursor.execute.side_effect = self.execute
        return cursor
    def execute(self, sql, params):
        if self.aborted:
            raise RuntimeError("transaction is aborted")
        status = params[0]
        self.events.append(status)
        if status == self.fail_status or (status == "FAILED" and self.fail_recording):
            self.aborted = True
            raise RuntimeError(f"SQL failed at {status}")
        if status == "FAILED":
            self.failure = params[1]
    def rollback(self):
        self.events.append("rollback")
        self.aborted = False
    def commit(self):
        assert not self.aborted
        self.events.append("commit")
    def close(self):
        self.events.append("close")

def make_orchestrator(monkeypatch, conn):
    monkeypatch.setattr(module, "get_db", lambda: conn)
    monkeypatch.setattr(module, "_get_previous_unl", lambda _: None)
    monkeypatch.setattr(module, "parse_response", lambda *_: MagicMock(complete=True))
    monkeypatch.setattr(module, "apply_formula", lambda value: value)
    monkeypatch.setattr(module, "select_unl", lambda *_: MagicMock(unl=[]))
    collector = MagicMock()
    collector.collect_dry_run.return_value = (MagicMock(), {})
    prompt = MagicMock()
    prompt.build.return_value = ([], {})
    return module.ScoringOrchestrator(
        collector=collector, prompt_builder=prompt, modal_client=MagicMock(),
        rpc_client=MagicMock(), ipfs_publisher=MagicMock(),
        onchain_publisher=MagicMock(), github_pages_client=MagicMock())

@pytest.mark.parametrize("status,phase", [
    ("COLLECTING", "COLLECTING"), ("SCORED", "SCORED"),
    ("SELECTED", "SELECTED"), ("DRY_RUN_COMPLETE", "DRY_RUN_ARTIFACTS")])
def test_recovers_aborted_phase_transaction(monkeypatch, status, phase):
    conn = TransactionConnection(status)
    result = make_orchestrator(monkeypatch, conn).run_dry_run(dry_run_id=123)
    assert result["status"] == "FAILED"
    assert conn.failure == f"{phase}: SQL failed at {status}"
    assert conn.events[-4:] == ["rollback", "FAILED", "commit", "close"]
    assert conn.events.count("close") == 1

def test_failure_recording_error_still_closes(monkeypatch):
    conn = TransactionConnection("SCORED", fail_recording=True)
    with pytest.raises(RuntimeError, match="SQL failed at FAILED"):
        make_orchestrator(monkeypatch, conn).run_dry_run(dry_run_id=123)
    assert conn.events[-3:] == ["rollback", "FAILED", "close"]

def test_creation_error_still_closes(monkeypatch):
    conn = TransactionConnection(None)
    orchestrator = make_orchestrator(monkeypatch, conn)
    def fail_creation(_):
        raise RuntimeError("create failed")
    monkeypatch.setattr(module, "create_dry_run", fail_creation)
    with pytest.raises(RuntimeError, match="create failed"):
        orchestrator.run_dry_run()
    assert conn.events == ["close"]

def test_success_closes_once_without_rollback(monkeypatch):
    conn = TransactionConnection(None)
    result = make_orchestrator(monkeypatch, conn).run_dry_run(dry_run_id=123)
    assert result["status"] == "DRY_RUN_COMPLETE"
    assert conn.events.count("close") == 1
    assert "rollback" not in conn.events
