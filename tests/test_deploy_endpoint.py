import importlib
import os
import sys
import types
from pathlib import Path

from infra.model_revision import (
    expected_snapshot_path,
    find_cached_snapshot,
    snapshot_download_kwargs,
)


MODEL_ID = "Qwen/Qwen3.6-27B-FP8"
REVISION = "e89b16ebf1988b3d6befa7de50abc2d76f26eb09"
SNAPSHOT_PATH = (
    "/model-cache/huggingface/models--Qwen--Qwen3.6-27B-FP8/"
    f"snapshots/{REVISION}"
)


class FakeImage:
    last_instance = None

    def __init__(self):
        self.run_commands_calls = []
        self.run_function_calls = []
        self.local_python_source_calls = []
        self.env_values = {}
        FakeImage.last_instance = self

    @classmethod
    def from_registry(cls, image_tag):
        image = cls()
        image.image_tag = image_tag
        return image

    def entrypoint(self, entrypoint):
        self.entrypoint_value = entrypoint
        return self

    def pip_install(self, *packages):
        self.packages = packages
        return self

    def env(self, env_values):
        self.env_values = env_values
        return self

    def run_function(self, function, **kwargs):
        self.run_function_calls.append({"function": function, **kwargs})
        return self

    def run_commands(self, commands, **kwargs):
        self.run_commands_calls.append({"commands": commands, **kwargs})
        return self

    def add_local_python_source(self, *modules, **kwargs):
        self.local_python_source_calls.append({
            "modules": modules,
            "kwargs": kwargs,
        })
        return self

    def imports(self):
        return _FakeContext()


class _FakeContext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeRequestException(Exception):
    pass


def _fake_requests_module():
    return types.SimpleNamespace(
        get=lambda *args, **kwargs: types.SimpleNamespace(status_code=200),
        exceptions=types.SimpleNamespace(RequestException=FakeRequestException),
    )


class FakeVolume:
    @classmethod
    def from_name(cls, name, create_if_missing=False):
        return {"name": name, "create_if_missing": create_if_missing}


class FakeApp:
    def __init__(self, name):
        self.name = name

    def cls(self, **kwargs):
        self.cls_kwargs = kwargs
        return _identity_decorator

    def local_entrypoint(self):
        return _identity_decorator


def _identity_decorator(target):
    return target


def _modal_decorator(*args, **kwargs):
    return _identity_decorator


def _fake_modal_module():
    return types.SimpleNamespace(
        App=FakeApp,
        Image=FakeImage,
        Volume=FakeVolume,
        enter=_modal_decorator,
        exit=_modal_decorator,
        web_server=_modal_decorator,
    )


def _load_deploy_endpoint(monkeypatch, **env):
    for key in list(os.environ):
        if key.startswith("SCORING_"):
            monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    FakeImage.last_instance = None
    monkeypatch.setitem(sys.modules, "modal", _fake_modal_module())
    monkeypatch.setitem(sys.modules, "requests", _fake_requests_module())
    sys.modules.pop("infra.deploy_endpoint", None)
    sys.modules.pop("deploy_endpoint", None)
    module = importlib.import_module("infra.deploy_endpoint")
    return module, FakeImage.last_instance


def _clear_deploy_modules():
    sys.modules.pop("infra.deploy_endpoint", None)
    sys.modules.pop("infra.deploy_qwen36_endpoint", None)
    sys.modules.pop("infra.deploy_qwen3_next_endpoint", None)
    sys.modules.pop("deploy_endpoint", None)


def _flag_value(command, flag):
    return command[command.index(flag) + 1]


def _assert_infra_source_included(image, *, copied: bool):
    kwargs = {"copy": True} if copied else {}
    assert image.local_python_source_calls == [{
        "modules": ("infra",),
        "kwargs": kwargs,
    }]


def test_snapshot_helpers_require_exact_pinned_revision(tmp_path):
    cache_path = tmp_path / "huggingface"
    exact_snapshot = (
        cache_path
        / "models--Qwen--Qwen3.6-27B-FP8"
        / "snapshots"
        / REVISION
    )
    other_snapshot = (
        cache_path
        / "models--Qwen--Qwen3.6-27B-FP8"
        / "snapshots"
        / "different-revision"
    )
    exact_snapshot.mkdir(parents=True)
    other_snapshot.mkdir(parents=True)
    (exact_snapshot / "model.safetensors").write_text("weights")
    (other_snapshot / "model.safetensors").write_text("weights")

    assert expected_snapshot_path(MODEL_ID, REVISION, str(cache_path)) == str(
        exact_snapshot
    )
    assert find_cached_snapshot(MODEL_ID, str(cache_path), REVISION) == str(
        exact_snapshot
    )
    assert find_cached_snapshot(MODEL_ID, str(cache_path), "missing") is None
    assert snapshot_download_kwargs(MODEL_ID, REVISION) == {
        "repo_id": MODEL_ID,
        "revision": REVISION,
    }


def test_revision_is_downloaded_and_loaded_from_local_snapshot(monkeypatch):
    module, image = _load_deploy_endpoint(
        monkeypatch,
        SCORING_MODEL_REVISION=REVISION,
    )
    download_calls = []
    popen_calls = []

    def fake_download_model(repo_id, revision=None):
        download_calls.append((repo_id, revision))
        return SNAPSHOT_PATH

    class FakePopen:
        def __init__(self, command):
            popen_calls.append(command)

        def terminate(self):
            pass

    monkeypatch.setattr(module, "download_model", fake_download_model)
    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(module, "wait_for_server", lambda: None)

    module.ScoringEndpoint().start_server()

    assert image.env_values["SCORING_MODEL_ID"] == MODEL_ID
    assert image.env_values["SCORING_MODEL_REVISION"] == REVISION
    _assert_infra_source_included(image, copied=False)
    assert image.run_commands_calls[0]["gpu"] == "H100"
    assert download_calls == [(MODEL_ID, REVISION)]
    command = popen_calls[0]
    assert _flag_value(command, "--model-path") == SNAPSHOT_PATH
    assert _flag_value(command, "--served-model-name") == MODEL_ID


def test_qwen36_wrapper_loads_model_revision_from_repo_env(monkeypatch):
    env_file_reads = []
    original_exists = Path.exists
    original_read_text = Path.read_text

    def fake_exists(path):
        if path.name == ".env":
            return True
        return original_exists(path)

    def fake_read_text(path, *args, **kwargs):
        if path.name == ".env":
            env_file_reads.append(path)
            return f"SCORING_MODEL_REVISION={REVISION}\n"
        return original_read_text(path, *args, **kwargs)

    for key in list(os.environ):
        if key.startswith("SCORING_"):
            monkeypatch.delenv(key, raising=False)

    FakeImage.last_instance = None
    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "read_text", fake_read_text)
    monkeypatch.setitem(sys.modules, "modal", _fake_modal_module())
    monkeypatch.setitem(sys.modules, "requests", _fake_requests_module())
    _clear_deploy_modules()

    try:
        module = importlib.import_module("infra.deploy_qwen36_endpoint")

        assert env_file_reads
        assert env_file_reads[0].name == ".env"
        assert module.ScoringEndpoint.__module__ == "infra.deploy_endpoint"
        assert FakeImage.last_instance.env_values["SCORING_MODEL_REVISION"] == REVISION
        _assert_infra_source_included(FakeImage.last_instance, copied=False)
    finally:
        for key in list(os.environ):
            if key.startswith("SCORING_"):
                os.environ.pop(key, None)


def test_qwen3_next_wrapper_uses_packaged_infra_import(monkeypatch):
    for key in list(os.environ):
        if key.startswith("SCORING_"):
            monkeypatch.delenv(key, raising=False)

    FakeImage.last_instance = None
    monkeypatch.setitem(sys.modules, "modal", _fake_modal_module())
    monkeypatch.setitem(sys.modules, "requests", _fake_requests_module())
    _clear_deploy_modules()

    try:
        module = importlib.import_module("infra.deploy_qwen3_next_endpoint")

        assert module.ScoringEndpoint.__module__ == "infra.deploy_endpoint"
        assert FakeImage.last_instance.env_values["SCORING_MODEL_ID"] == (
            "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
        )
        assert FakeImage.last_instance.env_values["SCORING_MODEL_REVISION"] == ""
        _assert_infra_source_included(FakeImage.last_instance, copied=True)
    finally:
        for key in list(os.environ):
            if key.startswith("SCORING_"):
                os.environ.pop(key, None)


def test_without_revision_uses_served_model_id_as_model_path(monkeypatch):
    module, image = _load_deploy_endpoint(monkeypatch)
    popen_calls = []

    def fail_download_model(repo_id, revision=None):
        raise AssertionError("download_model should not run without a pinned revision")

    class FakePopen:
        def __init__(self, command):
            popen_calls.append(command)

        def terminate(self):
            pass

    monkeypatch.setattr(module, "download_model", fail_download_model)
    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(module, "wait_for_server", lambda: None)

    module.ScoringEndpoint().start_server()

    command = popen_calls[0]
    assert _flag_value(command, "--model-path") == MODEL_ID
    assert _flag_value(command, "--served-model-name") == MODEL_ID
    assert image.run_commands_calls[0]["commands"] == [
        "python3 -m sglang.compile_deep_gemm "
        f"--model {MODEL_ID} --tp 1 --trust-remote-code"
    ]


def test_deepgemm_compile_uses_pinned_snapshot_path(monkeypatch):
    _module, image = _load_deploy_endpoint(
        monkeypatch,
        SCORING_MODEL_REVISION=REVISION,
    )

    commands = image.run_commands_calls[0]["commands"]

    assert commands[0] == (
        "python3 - <<'PY'\n"
        "from huggingface_hub import snapshot_download\n"
        "snapshot_download("
        f"repo_id='{MODEL_ID}', revision='{REVISION}'"
        ")\n"
        "PY"
    )
    assert commands[1] == (
        "python3 -m sglang.compile_deep_gemm "
        f"--model {SNAPSHOT_PATH} --tp 1 --trust-remote-code"
    )
