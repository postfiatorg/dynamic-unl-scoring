"""Provider-family normalization and concentration aggregates for scoring.

Groups validator ASN names into provider families so the scoring prompt can
carry precomputed concentration counts instead of asking the model to count
provider representation across the candidate set itself. Grouping is three
layers: generic name normalization (case, punctuation, legal suffixes,
numeric ASN decorations, trailing country codes), a small explicit mapping
for corporate families whose ASN names share no common token, and an
own-family fallback so a previously unseen provider forms its own
single-member family without code changes.
"""

import re
from collections import Counter

from scoring_service.models import ValidatorProfile

# Tokens that carry no provider identity: legal forms and the "AS" suffix.
_NOISE_TOKENS = {
    "as",
    "asn",
    "inc",
    "llc",
    "ltd",
    "gmbh",
    "ag",
    "sa",
    "srl",
    "bv",
    "co",
    "corp",
    "corporation",
    "company",
    "holdings",
}

_TRAILING_COUNTRY_RE = re.compile(r",\s*[A-Za-z]{2}$")
_NON_WORD_RE = re.compile(r"[\W_]+")
_TRAILING_DIGITS_RE = re.compile(r"\d+$")

# Explicit corporate families whose ASN names cannot be unified generically:
# either the names share no common token (Vultr registers as "The Constant
# Company", Linode as part of Akamai) or the family spans distinct ASN name
# stems (Hetzner's cloud ASNs). Needles match whole normalized tokens, never
# substrings, so "constant" cannot absorb an unrelated "Constantine". Keep
# this list short; the normalization plus the own-family fallback handles
# every single-name provider automatically.
_FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hetzner", ("hetzner",)),
    ("vultr", ("vultr", "constant",)),
    ("akamai", ("akamai", "linode")),
)

UNKNOWN_FAMILY = "unknown"


def normalize_provider_name(as_name: str) -> str:
    """Reduce a raw ASN name to its provider-identifying tokens.

    "CONTABO-40021 - Contabo Inc., US" and "CONTABO, DE" both normalize to
    "contabo"; "CHERRYSERVERS4-AS, LT" normalizes to "cherryservers".
    """
    name = _TRAILING_COUNTRY_RE.sub("", as_name.strip())
    if " - " in name:
        name = name.split(" - ", 1)[1]
    name = _NON_WORD_RE.sub(" ", name.lower())

    tokens = []
    for token in name.split():
        token = _TRAILING_DIGITS_RE.sub("", token)
        if token and token not in _NOISE_TOKENS:
            tokens.append(token)
    return " ".join(tokens)


def family_for(as_name: str | None) -> str:
    """Map an ASN name to its provider family.

    None or empty input maps to the unknown family: the validator's endpoint
    could not be resolved, so its infrastructure concentration is unknown.
    A resolved name that normalizes to nothing (pure ASN decoration such as
    "AS12876") stays its own family under the raw lowercased name — a
    resolved endpoint must never be reported as unresolved.
    """
    if not as_name:
        return UNKNOWN_FAMILY

    normalized = normalize_provider_name(as_name)
    if not normalized:
        return as_name.strip().lower()

    tokens = set(normalized.split())
    for family, needles in _FAMILY_RULES:
        if any(needle in tokens for needle in needles):
            return family
    return normalized


def compute_concentration(validators: list[ValidatorProfile]) -> dict:
    """Compute provider-family and country concentration for a candidate set.

    Returns a JSON-serializable dict with counts sorted by size (largest
    first, ties by name) so the rendered prompt is deterministic for
    identical evidence. Validators without resolved endpoints are reported
    as a separate unresolved count rather than inflating any family.
    """
    family_counts: Counter[str] = Counter()
    country_counts: Counter[str] = Counter()
    unresolved = 0

    for validator in validators:
        as_name = validator.asn.as_name if validator.asn else None
        family = family_for(as_name)
        if family == UNKNOWN_FAMILY:
            unresolved += 1
        else:
            family_counts[family] += 1

        country = validator.geolocation.country if validator.geolocation else None
        if country:
            country_counts[country] += 1

    def _sorted(counts: Counter[str], key_name: str) -> list[dict]:
        return [
            {key_name: name, "validators": count}
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    return {
        "provider_families": _sorted(family_counts, "family"),
        "countries": _sorted(country_counts, "country"),
        "unresolved_endpoints": unresolved,
    }
