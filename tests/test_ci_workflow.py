"""Guards the CI workflow's trigger contract: CI must run on pushes to main."""

from pathlib import Path

import pytest

# PyYAML is a test-time dependency pinned in requirements.txt. The deploy
# pipelines install only requirements-docker.txt, so skip there rather than
# erroring — the trigger contract is exercised by the CI workflow itself.
yaml = pytest.importorskip("yaml")

CI_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_runs_on_push_to_main():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())
    # PyYAML parses the YAML key `on` as the boolean True, so the trigger block
    # is keyed by True rather than the string "on".
    triggers = workflow.get(True, {})
    push = triggers.get("push") or {}
    assert "main" in push.get("branches", [])
