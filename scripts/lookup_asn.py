"""Look up ASN data for all topology node IPs in a validator snapshot.

Uses a local pyasn database (built from BGP routing table dumps) to resolve
each IP to its AS number, prefix, and ISP/organization name. All data is
from public WHOIS/RIR sources and freely publishable.

Usage:
    python scripts/lookup_asn.py --ip 144.202.24.188
    python scripts/lookup_asn.py
    python scripts/lookup_asn.py --snapshot data/testnet_snapshot.json
    python scripts/lookup_asn.py --db data/asn/ipasn_20260317.dat
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pyasn

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT = REPO_ROOT / "data" / "testnet_snapshot.json"
DEFAULT_ASN_DB = REPO_ROOT / "data" / "asn" / "ipasn_20260317.dat"
DEFAULT_AS_NAMES = REPO_ROOT / "data" / "asn" / "asnames.json"
OUTPUT_DIR = REPO_ROOT / "data" / "asn"


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text())


def lookup_all_nodes(snapshot: dict, db: pyasn.pyasn) -> list[dict]:
    """Look up ASN data for every topology node with an IP address."""
    nodes = snapshot.get("network_topology", {}).get("nodes", [])
    results = []

    for node in nodes:
        ip = node.get("ip")
        if not ip:
            continue

        asn, prefix = db.lookup(ip)
        as_name = db.get_as_name(asn) if asn else None

        results.append({
            "node_public_key": node.get("node_public_key", ""),
            "ip": ip,
            "asn": asn,
            "as_name": as_name,
            "prefix": prefix,
            "country": node.get("country"),
            "country_code": node.get("country_code"),
            "city": node.get("city"),
        })

    results.sort(key=lambda r: r["asn"] or 0)
    return results


def build_concentration_report(results: list[dict]) -> dict:
    """Compute ASN and ISP concentration across all nodes."""
    asn_counts = Counter()
    name_counts = Counter()

    for r in results:
        if r["asn"]:
            label = f"AS{r['asn']}"
            asn_counts[label] += 1
        if r["as_name"]:
            name_counts[r["as_name"]] += 1

    return {
        "total_nodes": len(results),
        "unique_asns": len(asn_counts),
        "by_asn": dict(asn_counts.most_common()),
        "by_provider": dict(name_counts.most_common()),
    }


def print_report(results: list[dict], concentration: dict) -> None:
    print(f"\n{'IP':<20} {'ASN':<10} {'Prefix':<22} {'Provider'}")
    print("-" * 90)
    for r in results:
        asn_str = f"AS{r['asn']}" if r["asn"] else "N/A"
        name = r["as_name"] or "Unknown"
        prefix = r["prefix"] or "N/A"
        print(f"{r['ip']:<20} {asn_str:<10} {prefix:<22} {name}")

    print(f"\n--- Concentration Report ---")
    print(f"Total nodes: {concentration['total_nodes']}")
    print(f"Unique ASNs: {concentration['unique_asns']}")
    print(f"\nBy provider:")
    for name, count in concentration["by_provider"].items():
        pct = count / concentration["total_nodes"] * 100
        print(f"  {name:<50} {count:>3} nodes ({pct:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="ASN lookup for topology node IPs")
    parser.add_argument("--ip", type=str, help="Look up a single IP address")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--db", type=Path, default=DEFAULT_ASN_DB)
    parser.add_argument("--names", type=Path, default=DEFAULT_AS_NAMES)
    parser.add_argument("--save", action="store_true", help="Save results to JSON")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Error: ASN database not found at {args.db}", file=sys.stderr)
        print("Run: pyasn_util_download.py --latest && pyasn_util_convert.py --single <file> <output>", file=sys.stderr)
        return 1

    names_file = str(args.names) if args.names.exists() else None
    db = pyasn.pyasn(str(args.db), as_names_file=names_file)

    if args.ip:
        asn, prefix = db.lookup(args.ip)
        if not asn:
            print(f"{args.ip}: no ASN found")
            return 1
        as_name = db.get_as_name(asn) or "Unknown"
        print(f"{args.ip} -> AS{asn} ({as_name}), prefix {prefix}")
        return 0

    snapshot = load_snapshot(args.snapshot)
    results = lookup_all_nodes(snapshot, db)
    concentration = build_concentration_report(results)
    print_report(results, concentration)

    if args.save:
        output = {
            "snapshot_source": str(args.snapshot.name),
            "asn_database": str(args.db.name),
            "node_lookups": results,
            "concentration": concentration,
        }
        output_path = OUTPUT_DIR / "asn_lookup_results.json"
        output_path.write_text(json.dumps(output, indent=2))
        print(f"\nResults saved to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
