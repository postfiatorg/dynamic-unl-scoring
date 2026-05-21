"""Helpers for pinning Hugging Face model revisions in Modal deployments."""

from pathlib import Path


def normalize_model_revision(revision: str | None) -> str | None:
    """Return a non-empty model revision string or ``None``."""
    if revision is None:
        return None
    normalized = revision.strip()
    return normalized or None


def repo_cache_name(repo_id: str) -> str:
    """Return Hugging Face Hub's cache directory name for a model repo."""
    return "models--" + repo_id.replace("/", "--")


def expected_snapshot_path(
    repo_id: str,
    revision: str | None,
    cache_path: str,
) -> str | None:
    """Return the expected local snapshot path for a pinned revision."""
    normalized_revision = normalize_model_revision(revision)
    if normalized_revision is None:
        return None
    return str(
        Path(cache_path)
        / repo_cache_name(repo_id)
        / "snapshots"
        / normalized_revision
    )


def find_cached_snapshot(
    repo_id: str,
    cache_path: str,
    revision: str | None = None,
) -> str | None:
    """Find a cached Hugging Face snapshot, optionally requiring a revision."""
    pinned_snapshot = expected_snapshot_path(repo_id, revision, cache_path)
    if pinned_snapshot is not None:
        snapshot_dir = Path(pinned_snapshot)
        if snapshot_dir.is_dir() and any(snapshot_dir.glob("*.safetensors")):
            return str(snapshot_dir)
        return None

    snapshots_dir = Path(cache_path) / repo_cache_name(repo_id) / "snapshots"
    if not snapshots_dir.exists():
        return None

    for snapshot_dir in snapshots_dir.iterdir():
        if snapshot_dir.is_dir() and any(snapshot_dir.glob("*.safetensors")):
            return str(snapshot_dir)
    return None


def snapshot_download_kwargs(repo_id: str, revision: str | None) -> dict[str, str]:
    """Build keyword arguments for ``huggingface_hub.snapshot_download``."""
    kwargs = {"repo_id": repo_id}
    normalized_revision = normalize_model_revision(revision)
    if normalized_revision is not None:
        kwargs["revision"] = normalized_revision
    return kwargs
