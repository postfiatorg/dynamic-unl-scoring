# Milestone 0.4: ASN Data Source Setup

## Decision

**Selected:** `pyasn` with local RIR/BGP routing table database and IANA AS name registry.

**Alternatives evaluated:**
- Team Cymru IP-to-ASN — free, but DNS-based with no REST API
- ipinfo.io — clean REST API, but external dependency and rate limits
- RIPE RIS — authoritative but slower and more complex to query
- pyasn — fast, offline, no API key, no rate limits, data is public/freely publishable

pyasn was chosen for zero operational risk: no external API calls, no rate limits, no API keys, and the underlying data (BGP routing tables from RouteViews, AS names from IANA) is public domain.

## How It Works

pyasn uses two data files:

1. **IP-to-ASN database** (`ipasn_YYYYMMDD.dat`) — built from BGP MRT/RIB routing table dumps published by [RouteViews](http://archive.routeviews.org). Maps IP prefixes to AS numbers. ~22 MB.
2. **AS names file** (`asnames.json`) — downloaded from IANA AS number registry. Maps AS numbers to organization names. ~5.3 MB.

Both files are generated locally and gitignored (regenerate with the commands below).

## Setup

```bash
# Install pyasn (already in requirements.txt)
pip install pyasn

# Download the latest BGP routing table dump
pyasn_util_download.py --latest

# Convert to pyasn database format
pyasn_util_convert.py --single rib.YYYYMMDD.HHMM.bz2 data/asn/ipasn_YYYYMMDD.dat

# Download AS name mapping from IANA
pyasn_util_asnames.py -o data/asn/asnames.json

# Clean up the raw MRT dump
rm rib.*.bz2
```

Update the `DEFAULT_ASN_DB` path in `scripts/lookup_asn.py` if the date in the filename changes.

## Usage

```bash
# Look up a single IP address
python scripts/lookup_asn.py --ip 144.202.24.188

# Run ASN lookup against all topology node IPs
python scripts/lookup_asn.py

# Save results to data/asn/asn_lookup_results.json
python scripts/lookup_asn.py --save

# Use a different snapshot or database
python scripts/lookup_asn.py --snapshot data/testnet_snapshot.json --db data/asn/ipasn_20260317.dat
```

## Data Source Split (Licensing)

| Data | Source | License | Publishable |
|------|--------|---------|-------------|
| AS number, prefix | BGP routing tables (RouteViews) | Public domain | Yes — included in IPFS audit trail |
| ISP/organization name | IANA AS number registry | Public domain | Yes — included in IPFS audit trail |
| City/country geolocation | MaxMind GeoIP2 Insights | Commercial EULA | No — internal use only, not published to IPFS |

This split ensures the scoring pipeline has full geographic and infrastructure context while respecting MaxMind's EULA restrictions on republishing extracted data points.

## Initial Results (2026-03-17)

44 topology nodes across 13 unique ASNs. Top providers:

| Provider | Nodes | Share |
|----------|-------|-------|
| Vultr (AS20473) | 11 | 25.0% |
| Hetzner (AS24940) | 10 | 22.7% |
| Cherry Servers (AS204770) | 7 | 15.9% |
| Contabo (AS51167) | 3 | 6.8% |
| Hetzner Cloud (AS213230) | 3 | 6.8% |

If Hetzner ASNs are grouped (AS24940 + AS212317 + AS213230), Hetzner controls 15 of 44 nodes (34.1%) — the single largest infrastructure concentration in the network.

## Database Refresh

The BGP routing table should be refreshed periodically (monthly is sufficient — ASN assignments change infrequently). In Phase 1, the data collection pipeline will automate this as part of snapshot assembly.
