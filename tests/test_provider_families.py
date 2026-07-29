"""Tests for provider-family normalization and concentration aggregates."""

from datetime import datetime, timezone

from scoring_service.models import (
    AgreementScore,
    ASNInfo,
    GeoLocation,
    ValidatorProfile,
)
from scoring_service.services.provider_families import (
    UNKNOWN_FAMILY,
    compute_concentration,
    family_for,
    normalize_provider_name,
)


def _validator(master_key, as_name=None, country=None):
    return ValidatorProfile(
        master_key=master_key,
        signing_key=f"sign-{master_key}",
        agreement_1h=AgreementScore(score=1.0, total=100, missed=0),
        agreement_24h=AgreementScore(score=1.0, total=100, missed=0),
        agreement_30d=AgreementScore(score=1.0, total=100, missed=0),
        server_version="1.0.4",
        asn=ASNInfo(asn=1, as_name=as_name) if as_name else None,
        geolocation=GeoLocation(country=country) if country else None,
    )


class TestNormalizeProviderName:
    def test_strips_case_country_and_legal_suffixes(self):
        assert normalize_provider_name("CONTABO, DE") == "contabo"
        assert normalize_provider_name("Contabo Inc., US") == "contabo"
        assert normalize_provider_name("DigitalOcean, LLC, US") == "digitalocean"
        assert normalize_provider_name("CABLE ONE, INC., US") == "cable one"

    def test_strips_asn_decorations_and_numeric_suffixes(self):
        assert normalize_provider_name("CHERRYSERVERS4-AS, LT") == "cherryservers"
        assert normalize_provider_name("HOSTKEY, US") == "hostkey"
        assert normalize_provider_name("CONTABO-40021 - Contabo Inc., US") == "contabo"

    def test_unseen_provider_normalizes_to_its_own_name(self):
        assert normalize_provider_name("NEWCLOUD SARL, FR") == "newcloud sarl"
        assert normalize_provider_name("EXAMPLE-AS, JP") == "example"


class TestFamilyFor:
    def test_hetzner_variants_share_one_family(self):
        assert family_for("HETZNER-AS, DE") == "hetzner"
        assert family_for("HETZNER-CLOUD2-AS, DE") == "hetzner"
        assert family_for("HETZNER-CLOUD3-AS, DE") == "hetzner"

    def test_multi_name_corporate_families(self):
        assert family_for("The Constant Company, LLC, US") == "vultr"
        assert family_for("Vultr Holdings, LLC") == "vultr"
        assert family_for("AKAMAI-LINODE-AP Akamai Connected Cloud, SG") == "akamai"

    def test_contabo_entities_unify_generically(self):
        assert family_for("CONTABO, DE") == family_for("CONTABO-40021 - Contabo Inc., US")

    def test_unseen_provider_becomes_own_family(self):
        assert family_for("NEWCLOUD SARL, FR") == "newcloud sarl"

    def test_family_needles_match_whole_tokens_only(self):
        assert family_for("Constantine Hosting, DZ") == "constantine hosting"

    def test_unicode_names_are_preserved(self):
        assert family_for("Türk Telekom, TR") == "türk telekom"

    def test_degenerate_resolved_name_stays_its_own_family(self):
        assert family_for("AS12876") == "as12876"
        assert family_for("AS-12345") == "as-12345"

    def test_missing_asn_maps_to_unknown(self):
        assert family_for(None) == UNKNOWN_FAMILY
        assert family_for("") == UNKNOWN_FAMILY


class TestComputeConcentration:
    def test_counts_families_countries_and_unresolved(self):
        validators = [
            _validator("nHB1", "HETZNER-AS, DE", "Germany"),
            _validator("nHB2", "HETZNER-CLOUD2-AS, DE", "United States"),
            _validator("nHB3", "The Constant Company, LLC, US", "United States"),
            _validator("nHB4", "HOSTKEY, US", "United States"),
            _validator("nHB5"),
        ]

        result = compute_concentration(validators)

        assert result["provider_families"] == [
            {"family": "hetzner", "validators": 2},
            {"family": "hostkey", "validators": 1},
            {"family": "vultr", "validators": 1},
        ]
        assert result["countries"] == [
            {"country": "United States", "validators": 3},
            {"country": "Germany", "validators": 1},
        ]
        assert result["unresolved_endpoints"] == 1

    def test_degenerate_resolved_name_is_not_counted_unresolved(self):
        validators = [
            _validator("nHB1", "AS12876", "France"),
            _validator("nHB2"),
        ]

        result = compute_concentration(validators)

        assert result["provider_families"] == [{"family": "as12876", "validators": 1}]
        assert result["unresolved_endpoints"] == 1

    def test_ordering_is_deterministic_for_ties(self):
        validators = [
            _validator("nHB1", "HOSTKEY, US", "Japan"),
            _validator("nHB2", "CABLE ONE, INC., US", "Australia"),
        ]

        result = compute_concentration(validators)

        assert [f["family"] for f in result["provider_families"]] == [
            "cable one",
            "hostkey",
        ]
        assert [c["country"] for c in result["countries"]] == ["Australia", "Japan"]
