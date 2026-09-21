"""Ordering of validator server versions.

postfiatd reports a semantic version: a three-part numeric release, an
optional pre-release suffix (`1.0.8-rc1`), and optional build metadata
(`1.0.8+DEBUG`). A pre-release sorts below its final release and build
metadata is ignored. Pre-releases of the same release are not ordered
against each other.
"""

import re
from typing import NamedTuple

# The digit bound keeps int() from raising on an absurdly long component.
_VERSION_PATTERN = re.compile(
    r"^(?P<release>\d{1,9}\.\d{1,9}\.\d{1,9})"
    r"(?P<prerelease>-[0-9A-Za-z.-]+)?"
    r"(?P<build>\+[0-9A-Za-z.-]+)?$"
)


class ServerVersion(NamedTuple):
    """Comparable server version; a pre-release sorts below its final release."""

    release: tuple[int, ...]
    is_final: bool


def _from_match(match: re.Match[str]) -> ServerVersion:
    return ServerVersion(
        release=tuple(int(part) for part in match.group("release").split(".")),
        is_final=match.group("prerelease") is None,
    )


def parse_server_version(value: str) -> ServerVersion | None:
    """Parse a server version string, or return None when it is not one."""
    match = _VERSION_PATTERN.match(value.strip())
    return _from_match(match) if match else None


def parse_release_version(value: str) -> ServerVersion | None:
    """Parse a plain final release such as `1.0.8`, refusing any suffix."""
    match = _VERSION_PATTERN.match(value.strip())
    if match is None or match.group("prerelease") or match.group("build"):
        return None
    return _from_match(match)


def meets_minimum_version(server_version: str, minimum: ServerVersion) -> bool:
    """Return True only when the version is readable and not older than the minimum.

    A missing or unreadable version cannot be shown to be safe, so it does
    not meet the minimum.
    """
    parsed = parse_server_version(server_version)
    return parsed is not None and parsed >= minimum
