"""ASN lookup client for ISP/provider identification.

Resolves validator IP addresses to Autonomous System Numbers and provider
names using a local pyasn BGP routing table. All data is from public
WHOIS/RIR sources and freely publishable in the IPFS audit trail.
"""

import logging
from pathlib import Path
from typing import Optional

import pyasn

from scoring_service.models import ASNInfo, ValidatorProfile

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "asn"
DEFAULT_ASN_DB = DATA_DIR / "ipasn_20260317.dat"
DEFAULT_AS_NAMES = DATA_DIR / "asnames.json"


class ASNClient:
    """Resolves IP addresses to ASN and provider name via local BGP table."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        names_path: Optional[Path] = None,
    ):
        db_path = db_path or DEFAULT_ASN_DB
        names_path = names_path or DEFAULT_AS_NAMES

        names_file = str(names_path) if names_path.exists() else None
        self._db = pyasn.pyasn(str(db_path), as_names_file=names_file)
        logger.info("Loaded ASN database from %s", db_path.name)

    def lookup(self, ip: Optional[str]) -> Optional[ASNInfo]:
        """Look up ASN for a single IP. Returns None for null IPs."""
        if not ip:
            return None

        try:
            asn, _prefix = self._db.lookup(ip)
        except ValueError as exc:
            logger.warning("Invalid IP address %s — %s", ip, exc)
            return ASNInfo()

        if not asn:
            logger.warning("No BGP prefix found for %s", ip)
            return ASNInfo()

        as_name = self._db.get_as_name(asn)
        return ASNInfo(asn=asn, as_name=as_name)

    def enrich_validators(self, validators: list[ValidatorProfile]) -> None:
        """Attach ASN info to each validator that has a resolved IP."""
        resolved = 0
        for validator in validators:
            result = self.lookup(validator.ip)
            validator.asn = result
            if result and result.asn:
                resolved += 1

        logger.info(
            "ASN enrichment: %d/%d validators resolved",
            resolved,
            len(validators),
        )
