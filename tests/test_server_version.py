"""Tests for validator server version ordering."""

import pytest

from scoring_service.server_version import (
    ServerVersion,
    meets_minimum_version,
    parse_release_version,
    parse_server_version,
)

MINIMUM = ServerVersion(release=(1, 0, 8), is_final=True)


class TestParseServerVersion:
    def test_parses_a_final_release(self):
        assert parse_server_version("1.0.8") == MINIMUM

    def test_marks_prerelease_suffixes_as_not_final(self):
        assert parse_server_version("1.0.8-rc1") == ServerVersion(release=(1, 0, 8), is_final=False)
        assert parse_server_version("1.0.8-b2") == ServerVersion(release=(1, 0, 8), is_final=False)

    def test_ignores_build_metadata(self):
        assert parse_server_version("1.0.8+DEBUG") == MINIMUM

    def test_tolerates_surrounding_whitespace(self):
        assert parse_server_version(" 1.0.8 ") == MINIMUM

    @pytest.mark.parametrize(
        "value",
        ["", "unknown", "v1.0.8", "1.0.x", "1..8", "postfiatd-1.0.8", "1.0", "1.0.8.1", "1.0." + "9" * 5000],
    )
    def test_rejects_values_that_are_not_versions(self, value):
        assert parse_server_version(value) is None


class TestParseReleaseVersion:
    def test_parses_a_plain_final_release(self):
        assert parse_release_version(" 1.0.8 ") == MINIMUM

    @pytest.mark.parametrize("value", ["", "1", "1.0", "1.0.8.1", "1.0.8-rc1", "1.0.8+DEBUG", "1.0.x"])
    def test_rejects_anything_but_a_plain_final_release(self, value):
        assert parse_release_version(value) is None


class TestMeetsMinimumVersion:
    @pytest.mark.parametrize("version", ["1.0.0", "1.0.4", "1.0.7", "0.9.99", "1.0.8-rc1"])
    def test_older_versions_do_not_meet_the_minimum(self, version):
        assert meets_minimum_version(version, MINIMUM) is False

    @pytest.mark.parametrize("version", ["1.0.8", "1.0.9", "1.0.10", "1.1.0", "2.0.0", "1.0.9-rc1", "1.0.8+DEBUG"])
    def test_same_and_newer_versions_meet_the_minimum(self, version):
        assert meets_minimum_version(version, MINIMUM) is True

    def test_components_compare_as_numbers_not_text(self):
        assert meets_minimum_version("1.0.10", ServerVersion(release=(1, 0, 9), is_final=True)) is True
        assert meets_minimum_version("1.0.9", ServerVersion(release=(1, 0, 10), is_final=True)) is False

    @pytest.mark.parametrize("version", ["", "unknown", "v1.0.9"])
    def test_missing_or_unreadable_versions_do_not_meet_the_minimum(self, version):
        assert meets_minimum_version(version, MINIMUM) is False
