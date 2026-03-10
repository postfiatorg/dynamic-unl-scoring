"""Fetch validator and topology data from VHS testnet API, save as a unified snapshot.

VHS tracks validators and topology nodes separately with different key types
(validator signing/master keys vs node identity keys). These cannot be joined
directly. The snapshot includes both datasets — validator performance data is
the primary scoring input, while topology provides network-level geographic context.

In the full Phase 1 pipeline, per-validator geolocation will come from MaxMind
GeoIP lookups on validator IPs collected by the foundation.
"""

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

VHS_BASE = "https://vhs.testnet.postfiat.org/v1"
VALIDATORS_URL = f"{VHS_BASE}/network/validators"
TOPOLOGY_URL = f"{VHS_BASE}/network/topology/nodes"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
TIMEOUT = 30


def fetch_json(url: str) -> dict:
    response = httpx.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def build_validators(raw_validators: list) -> list:
    enriched = []
    for v in raw_validators:
        master_key = v.get("master_key") or v.get("validation_public_key", "")
        signing_key = v.get("signing_key") or v.get("validation_public_key", "")

        agreement_1h = v.get("agreement_1h", {})
        agreement_24h = v.get("agreement_24h", {})
        agreement_30d = v.get("agreement_30day", {})

        enriched.append({
            "master_key": master_key,
            "signing_key": signing_key,
            "domain": v.get("domain", ""),
            "domain_verified": v.get("domain_verified", False),
            "agreement_1h_score": agreement_1h.get("score"),
            "agreement_1h_total": agreement_1h.get("total"),
            "agreement_1h_missed": agreement_1h.get("missed"),
            "agreement_24h_score": agreement_24h.get("score"),
            "agreement_24h_total": agreement_24h.get("total"),
            "agreement_24h_missed": agreement_24h.get("missed"),
            "agreement_30d_score": agreement_30d.get("score"),
            "agreement_30d_total": agreement_30d.get("total"),
            "agreement_30d_missed": agreement_30d.get("missed"),
            "server_version": v.get("server_version", ""),
            "unl": v.get("unl", False),
            "current_index": v.get("current_index"),
            "partial": v.get("partial", False),
            "base_fee": v.get("base_fee"),
            "reserve_base": v.get("reserve_base"),
            "reserve_inc": v.get("reserve_inc"),
        })

    enriched.sort(key=lambda x: x["master_key"])
    return enriched


def build_network_topology(raw_nodes: list) -> dict:
    """Summarize topology nodes for network-level geographic context."""
    nodes = []
    for n in raw_nodes:
        nodes.append({
            "node_public_key": n.get("node_public_key", ""),
            "ip": n.get("ip"),
            "port": n.get("port"),
            "version": n.get("version", ""),
            "server_state": n.get("server_state"),
            "uptime_seconds": n.get("uptime"),
            "io_latency_ms": n.get("io_latency_ms"),
            "inbound_peers": n.get("inbound_count"),
            "outbound_peers": n.get("outbound_count"),
            "country": n.get("country"),
            "country_code": n.get("country_code"),
            "region": n.get("region"),
            "city": n.get("city"),
        })

    country_counts = Counter(n["country"] for n in nodes if n.get("country"))

    return {
        "node_count": len(nodes),
        "country_distribution": dict(country_counts.most_common()),
        "nodes": sorted(nodes, key=lambda x: x["node_public_key"]),
    }


def build_snapshot() -> dict:
    print(f"Fetching validators from {VALIDATORS_URL}")
    validators_resp = fetch_json(VALIDATORS_URL)
    raw_validators = validators_resp.get("validators", [])
    if isinstance(raw_validators, dict):
        raw_validators = list(raw_validators.values())
    print(f"  Got {len(raw_validators)} validators")

    print(f"Fetching topology from {TOPOLOGY_URL}")
    topology_resp = fetch_json(TOPOLOGY_URL)
    raw_nodes = topology_resp.get("nodes", [])
    if isinstance(raw_nodes, dict):
        raw_nodes = list(raw_nodes.values())
    print(f"  Got {len(raw_nodes)} nodes")

    validators = build_validators(raw_validators)
    topology = build_network_topology(raw_nodes)

    return {
        "network": "testnet",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "validator_count": len(validators),
        "validators": validators,
        "network_topology": topology,
    }


def main():
    snapshot = build_snapshot()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "testnet_snapshot.json"
    output_path.write_text(json.dumps(snapshot, indent=2))

    topo = snapshot["network_topology"]
    print(f"\nSnapshot saved to {output_path}")
    print(f"  {snapshot['validator_count']} validators")
    print(f"  {topo['node_count']} topology nodes")
    print(f"  Country distribution: {topo['country_distribution']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
