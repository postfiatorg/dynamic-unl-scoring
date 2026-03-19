"""Tests for scoring pipeline data models."""

from datetime import datetime, timezone

from scoring_service.models import (
    AgreementScore,
    ASNInfo,
    GeoLocation,
    IdentityAttestation,
    NetworkContext,
    ScoringSnapshot,
    ValidatorProfile,
)


class TestAgreementScore:
    def test_defaults_to_none(self):
        score = AgreementScore()
        assert score.score is None
        assert score.total is None
        assert score.missed is None

    def test_full_construction(self):
        score = AgreementScore(score=0.99780, total=28672, missed=63)
        assert score.score == 0.99780
        assert score.total == 28672
        assert score.missed == 63

    def test_coerces_string_score_from_vhs(self):
        score = AgreementScore(score="1.00000", total=1194, missed=0)
        assert score.score == 1.0


class TestASNInfo:
    def test_defaults_to_none(self):
        info = ASNInfo()
        assert info.asn is None
        assert info.as_name is None

    def test_full_construction(self):
        info = ASNInfo(
            asn=20473,
            as_name="AS-VULTR - The Constant Company, LLC, US",
        )
        assert info.asn == 20473
        assert info.as_name == "AS-VULTR - The Constant Company, LLC, US"


class TestGeoLocation:
    def test_defaults_to_none(self):
        geo = GeoLocation()
        assert geo.country is None
        assert geo.continent is None

    def test_full_construction(self):
        geo = GeoLocation(
            continent="North America",
            country="United States",
            region="New Jersey",
            city="Piscataway",
        )
        assert geo.country == "United States"
        assert geo.region == "New Jersey"


class TestIdentityAttestation:
    def test_defaults_to_none(self):
        identity = IdentityAttestation()
        assert identity.verified is None
        assert identity.entity_type is None
        assert identity.domain_attested is None
        assert identity.name is None

    def test_full_construction(self):
        identity = IdentityAttestation(
            verified=True,
            entity_type="institutional",
            domain_attested=True,
            name="Acme Corp",
        )
        assert identity.verified is True
        assert identity.entity_type == "institutional"
        assert identity.name == "Acme Corp"


class TestValidatorProfile:
    def test_minimal_construction(self):
        v = ValidatorProfile(master_key="nHBtest1", signing_key="n9test1")
        assert v.master_key == "nHBtest1"
        assert v.domain is None
        assert v.agreement_1h.score is None
        assert v.unl is False
        assert v.base_fee is None
        assert v.ip is None
        assert v.asn is None
        assert v.geolocation is None
        assert v.identity is None

    def test_full_construction_with_enrichments(self):
        v = ValidatorProfile(
            master_key="nHBtest1",
            signing_key="n9test1",
            domain="postfiat.org",
            domain_verified=True,
            agreement_1h=AgreementScore(score=1.0, total=1194, missed=0),
            agreement_24h=AgreementScore(score=0.99916, total=28672, missed=24),
            agreement_30d=AgreementScore(score=0.96626, total=759204, missed=25612),
            server_version="3.0.0",
            unl=True,
            base_fee=10,
            ip="144.202.24.188",
            asn=ASNInfo(asn=20473, as_name="Vultr"),
            geolocation=GeoLocation(country="United States"),
            identity=IdentityAttestation(
                verified=True, entity_type="institutional", name="Post Fiat Foundation"
            ),
        )
        assert v.domain == "postfiat.org"
        assert v.agreement_30d.missed == 25612
        assert v.asn.asn == 20473
        assert v.identity.verified is True
        assert v.identity.name == "Post Fiat Foundation"

    def test_json_round_trip(self):
        v = ValidatorProfile(
            master_key="nHBtest1",
            signing_key="n9test1",
            agreement_1h=AgreementScore(score=1.0, total=1194, missed=0),
            asn=ASNInfo(asn=20473),
        )
        data = v.model_dump(mode="json")
        restored = ValidatorProfile(**data)
        assert restored == v


class TestNetworkContext:
    def test_defaults_to_empty(self):
        ctx = NetworkContext()
        assert ctx.node_count == 0
        assert ctx.country_distribution == {}
        assert ctx.asn_distribution == {}

    def test_full_construction(self):
        ctx = NetworkContext(
            node_count=10,
            country_distribution={"United States": 6, "Germany": 3, "Japan": 1},
            asn_distribution={"AS-VULTR": 5, "AS-HETZNER": 3, "AS-AWS": 2},
        )
        assert ctx.node_count == 10
        assert ctx.country_distribution["Germany"] == 3
        assert ctx.asn_distribution["AS-VULTR"] == 5


class TestScoringSnapshot:
    def _build_snapshot(self, **overrides):
        defaults = dict(
            round_number=1,
            network="testnet",
            snapshot_timestamp=datetime(2026, 3, 15, tzinfo=timezone.utc),
            snapshot_ledger_index=914785,
            validators=[
                ValidatorProfile(
                    master_key="nHBtest1",
                    signing_key="n9test1",
                    agreement_1h=AgreementScore(score=1.0, total=1194, missed=0),
                ),
            ],
            network_context=NetworkContext(
                node_count=10,
                country_distribution={"United States": 6, "Germany": 4},
                asn_distribution={"AS-VULTR": 7, "AS-HETZNER": 3},
            ),
        )
        defaults.update(overrides)
        return ScoringSnapshot(**defaults)

    def test_construction(self):
        snapshot = self._build_snapshot()
        assert snapshot.round_number == 1
        assert snapshot.network == "testnet"
        assert snapshot.snapshot_ledger_index == 914785
        assert len(snapshot.validators) == 1
        assert snapshot.network_context.node_count == 10

    def test_content_hash_determinism(self):
        s1 = self._build_snapshot()
        s2 = self._build_snapshot()
        assert s1.content_hash() == s2.content_hash()

    def test_content_hash_changes_with_data(self):
        s1 = self._build_snapshot()
        s2 = self._build_snapshot(round_number=2)
        assert s1.content_hash() != s2.content_hash()

    def test_json_round_trip_preserves_hash(self):
        snapshot = self._build_snapshot()
        original_hash = snapshot.content_hash()
        data = snapshot.model_dump(mode="json")
        restored = ScoringSnapshot(**data)
        assert restored == snapshot
        assert restored.content_hash() == original_hash

    def test_empty_validators(self):
        snapshot = self._build_snapshot(validators=[])
        assert snapshot.content_hash()

    def test_defaults_for_optional_fields(self):
        snapshot = ScoringSnapshot(
            round_number=1,
            network="devnet",
            snapshot_timestamp=datetime(2026, 3, 15, tzinfo=timezone.utc),
            validators=[],
        )
        assert snapshot.snapshot_ledger_index is None
        assert snapshot.network_context.node_count == 0
        assert snapshot.network_context.country_distribution == {}
        assert snapshot.network_context.asn_distribution == {}
