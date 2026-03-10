"""Fetch validator and topology data from VHS testnet API, save as a unified snapshot."""

import json
import sys
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


def build_snapshot() -> dict:
    print(f"Fetching validators from {VALIDATORS_URL}")
    validators_resp = fetch_json(VALIDATORS_URL)
    validators = validators_resp.get("validators", validators_resp)
    if isinstance(validators, dict):
        validators = list(validators.values())
    print(f"  Got {len(validators)} validators")

    print(f"Fetching topology from {TOPOLOGY_URL}")
    topology_resp = fetch_json(TOPOLOGY_URL)
    nodes = topology_resp.get("nodes", topology_resp)
    if isinstance(nodes, dict):
        nodes = list(nodes.values())
    print(f"  Got {len(nodes)} nodes")

    node_by_key = {}
    for node in nodes:
        pub_key = node.get("node_public_key") or node.get("public_key")
        if pub_key:
            node_by_key[pub_key] = node

    enriched = []
    for v in validators:
        master_key = (
            v.get("master_key")
            or v.get("validation_public_key")
            or v.get("public_key", "")
        )
        signing_key = v.get("signing_key") or v.get("validation_public_key", "")

        node_data = node_by_key.get(signing_key, {})
        if not node_data and master_key:
            node_data = node_by_key.get(master_key, {})

        entry = {
            "master_key": master_key,
            "signing_key": signing_key,
            "domain": v.get("domain", ""),
            "domain_verified": v.get("domain_state") == "verified"
            or v.get("domain_verified", False),
            "agreement_score": v.get("agreement_1h", {}).get("score")
            or v.get("agreement_score"),
            "agreement_total": v.get("agreement_24h", {}).get("total")
            or v.get("agreement_total"),
            "agreement_missed": v.get("agreement_24h", {}).get("missed")
            or v.get("agreement_missed"),
            "server_version": v.get("server_version", ""),
            "unl": v.get("unl", False),
            "current_index": v.get("current_index"),
            "fee_vote": v.get("fee", {}),
            "amendments": v.get("amendments"),
            "ip": node_data.get("ip"),
            "port": node_data.get("port"),
            "city": node_data.get("city"),
            "country": node_data.get("country"),
            "country_code": node_data.get("country_code"),
            "region": node_data.get("region"),
            "isp": node_data.get("isp") or node_data.get("org"),
            "asn": node_data.get("asn"),
            "latency_ms": node_data.get("latency"),
            "inbound_peers": node_data.get("inbound_count"),
            "outbound_peers": node_data.get("outbound_count"),
            "uptime_seconds": node_data.get("uptime"),
            "server_state": node_data.get("server_state"),
        }
        enriched.append(entry)

    enriched.sort(key=lambda x: x["master_key"])

    return {
        "network": "testnet",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "validator_count": len(enriched),
        "validators": enriched,
    }


def main():
    snapshot = build_snapshot()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "testnet_snapshot.json"
    output_path.write_text(json.dumps(snapshot, indent=2))
    print(f"\nSnapshot saved to {output_path}")
    print(f"  {snapshot['validator_count']} validators")
    geo_count = sum(1 for v in snapshot["validators"] if v.get("country"))
    print(f"  {geo_count} with geographic data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
