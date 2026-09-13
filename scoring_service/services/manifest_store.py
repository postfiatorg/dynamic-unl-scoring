"""Validator manifest store.

Since postfiatd 1.0.6 a node keeps only a bounded set of manifests for
validators outside its list and forgets them on restart, so the RPC node may
not know a candidate's manifest at the moment it is selected for the UNL.
Every manifest the RPC node returns is remembered in ``validator_manifests``;
VL signing asks the node first and falls back to the stored copy.
"""

import logging
from dataclasses import dataclass

from scoring_service.clients.rpc import RPCClient

logger = logging.getLogger(__name__)


@dataclass
class ManifestResolution:
    """Where each requested validator's manifest came from."""

    manifests: dict[str, str]
    from_rpc: list[str]
    from_store: list[str]
    missing: list[str]

    def as_check(self) -> dict:
        return {
            "from_rpc": self.from_rpc,
            "from_store": self.from_store,
            "missing": self.missing,
        }


def remember_manifests(conn, manifests: dict[str, str]) -> None:
    """Upsert manifests returned by the RPC node."""
    if not manifests:
        return
    cursor = conn.cursor()
    for master_key, manifest in manifests.items():
        cursor.execute(
            """
            INSERT INTO validator_manifests (master_key, manifest)
            VALUES (%s, %s)
            ON CONFLICT (master_key) DO UPDATE SET
                manifest = EXCLUDED.manifest,
                updated_at = NOW()
            """,
            (master_key, manifest),
        )
    cursor.close()
    conn.commit()


def load_stored_manifests(conn, master_keys: list[str]) -> dict[str, str]:
    """Return the stored manifests for the given master keys."""
    if not master_keys:
        return {}
    cursor = conn.cursor()
    cursor.execute(
        "SELECT master_key, manifest FROM validator_manifests WHERE master_key = ANY(%s)",
        (list(master_keys),),
    )
    rows = cursor.fetchall()
    cursor.close()
    return {row[0]: row[1] for row in rows}


def refresh_manifest_store(conn, rpc: RPCClient, master_keys: list[str]) -> int:
    """Remember manifests for validators the store does not know yet.

    Only keys absent from the store are asked from the RPC node, so a round
    normally costs no lookups here and an unreachable node delays it only for
    genuinely new validators. Returns the number of manifests remembered.
    """
    stored = load_stored_manifests(conn, master_keys)
    unknown = [key for key in master_keys if key not in stored]
    if not unknown:
        return 0
    fetched = rpc.fetch_manifests(unknown)
    remember_manifests(conn, fetched)
    return len(fetched)


def resolve_manifests(conn, rpc: RPCClient, master_keys: list[str]) -> ManifestResolution:
    """Resolve manifests for VL signing: RPC node first, then the store."""
    fetched = rpc.fetch_manifests(master_keys)
    remember_manifests(conn, fetched)

    not_on_node = [key for key in master_keys if key not in fetched]
    stored = load_stored_manifests(conn, not_on_node)

    manifests = dict(fetched)
    manifests.update(stored)
    from_store = [key for key in not_on_node if key in stored]
    missing = [key for key in not_on_node if key not in stored]

    if from_store:
        logger.warning(
            "RPC node has no manifest for %d validator(s); using stored copies: %s",
            len(from_store),
            ", ".join(from_store),
        )
    if missing:
        logger.error(
            "No manifest available for %d validator(s): %s",
            len(missing),
            ", ".join(missing),
        )

    return ManifestResolution(
        manifests=manifests,
        from_rpc=[key for key in master_keys if key in fetched],
        from_store=from_store,
        missing=missing,
    )
