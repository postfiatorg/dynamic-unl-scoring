"""Tests for the validator manifest store."""

from unittest.mock import MagicMock

from scoring_service.services.manifest_store import (
    ManifestResolution,
    load_stored_manifests,
    refresh_manifest_store,
    remember_manifests,
    resolve_manifests,
)


def _conn(stored_rows=None):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = stored_rows or []
    conn.cursor.return_value = cursor
    return conn, cursor


class TestRememberManifests:
    def test_upserts_each_manifest_and_commits(self):
        conn, cursor = _conn()

        remember_manifests(conn, {"nHU_a": "manifest-a", "nHU_b": "manifest-b"})

        assert cursor.execute.call_count == 2
        params = [c.args[1] for c in cursor.execute.call_args_list]
        assert params == [("nHU_a", "manifest-a"), ("nHU_b", "manifest-b")]
        assert "ON CONFLICT (master_key) DO UPDATE" in cursor.execute.call_args_list[0].args[0]
        conn.commit.assert_called_once()

    def test_no_op_when_empty(self):
        conn, cursor = _conn()

        remember_manifests(conn, {})

        cursor.execute.assert_not_called()
        conn.commit.assert_not_called()


class TestLoadStoredManifests:
    def test_returns_mapping_for_requested_keys(self):
        conn, cursor = _conn(stored_rows=[("nHU_a", "manifest-a")])

        result = load_stored_manifests(conn, ["nHU_a", "nHU_b"])

        assert result == {"nHU_a": "manifest-a"}
        assert cursor.execute.call_args.args[1] == (["nHU_a", "nHU_b"],)

    def test_skips_query_when_no_keys(self):
        conn, cursor = _conn()

        assert load_stored_manifests(conn, []) == {}
        cursor.execute.assert_not_called()


class TestRefreshManifestStore:
    def test_fetches_only_keys_the_store_does_not_know(self):
        conn, cursor = _conn(stored_rows=[("nHU_known", "manifest-known")])
        rpc = MagicMock()
        rpc.fetch_manifests.return_value = {"nHU_new": "manifest-new"}

        remembered = refresh_manifest_store(conn, rpc, ["nHU_known", "nHU_new", "nHU_gone"])

        rpc.fetch_manifests.assert_called_once_with(["nHU_new", "nHU_gone"])
        assert remembered == 1
        upserts = [c.args[1] for c in cursor.execute.call_args_list if len(c.args) > 1 and c.args[0].lstrip().startswith("INSERT")]
        assert upserts == [("nHU_new", "manifest-new")]

    def test_skips_rpc_when_everything_is_known(self):
        conn, _ = _conn(stored_rows=[("nHU_a", "m-a"), ("nHU_b", "m-b")])
        rpc = MagicMock()

        assert refresh_manifest_store(conn, rpc, ["nHU_a", "nHU_b"]) == 0
        rpc.fetch_manifests.assert_not_called()


class TestResolveManifests:
    def test_prefers_rpc_and_remembers_it(self):
        conn, cursor = _conn(stored_rows=[])
        rpc = MagicMock()
        rpc.fetch_manifests.return_value = {"nHU_a": "manifest-a"}

        resolution = resolve_manifests(conn, rpc, ["nHU_a"])

        assert resolution == ManifestResolution(
            manifests={"nHU_a": "manifest-a"},
            from_rpc=["nHU_a"],
            from_store=[],
            missing=[],
        )
        upserts = [c.args[1] for c in cursor.execute.call_args_list if c.args[0].lstrip().startswith("INSERT")]
        assert upserts == [("nHU_a", "manifest-a")]

    def test_falls_back_to_store_for_keys_the_node_forgot(self):
        conn, cursor = _conn(stored_rows=[("nHU_b", "manifest-b-stored")])
        rpc = MagicMock()
        rpc.fetch_manifests.return_value = {"nHU_a": "manifest-a"}

        resolution = resolve_manifests(conn, rpc, ["nHU_a", "nHU_b", "nHU_c"])

        assert resolution.manifests == {"nHU_a": "manifest-a", "nHU_b": "manifest-b-stored"}
        assert resolution.from_rpc == ["nHU_a"]
        assert resolution.from_store == ["nHU_b"]
        assert resolution.missing == ["nHU_c"]
        # Only the keys the node did not answer are looked up in the store.
        select_calls = [c for c in cursor.execute.call_args_list if c.args[0].lstrip().startswith("SELECT")]
        assert select_calls[0].args[1] == (["nHU_b", "nHU_c"],)
        assert resolution.as_check() == {
            "from_rpc": ["nHU_a"],
            "from_store": ["nHU_b"],
            "missing": ["nHU_c"],
        }

    def test_all_missing_when_neither_source_knows(self):
        conn, _ = _conn(stored_rows=[])
        rpc = MagicMock()
        rpc.fetch_manifests.return_value = {}

        resolution = resolve_manifests(conn, rpc, ["nHU_a"])

        assert resolution.manifests == {}
        assert resolution.missing == ["nHU_a"]
