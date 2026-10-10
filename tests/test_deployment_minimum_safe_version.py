"""Keep checked-in and deployed minimum-safe-version policy in sync."""

import re
from pathlib import Path

from scoring_service.server_version import parse_release_version


ROOT = Path(__file__).resolve().parents[1]
POLICY_FILES = (
    ROOT / ".env.devnet",
    ROOT / ".env.testnet",
    ROOT / ".github" / "workflows" / "deploy-devnet.yml",
    ROOT / ".github" / "workflows" / "deploy-testnet.yml",
)
ASSIGNMENT = re.compile(r"(?m)^\s*MINIMUM_SAFE_VERSION=(\S+)\s*$")


def test_deployment_minimum_safe_versions_are_valid_and_identical():
    values = {}

    for path in POLICY_FILES:
        matches = ASSIGNMENT.findall(path.read_text())
        assert len(matches) == 1, f"expected one MINIMUM_SAFE_VERSION in {path}"
        value = matches[0]
        assert parse_release_version(value) is not None, (
            f"MINIMUM_SAFE_VERSION in {path} must be a plain final release"
        )
        values[path.relative_to(ROOT).as_posix()] = value

    assert len(set(values.values())) == 1, f"deployment policy drift: {values}"
