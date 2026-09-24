import pytest
from pydantic import ValidationError

from scoring_service.config import QWEN_NON_THINKING_EXTRA_BODY, Settings
from scoring_service.server_version import ServerVersion


def test_vl_effective_lookahead_hours_rejects_negative():
    # A negative lookahead would place activation before publication and defeat
    # the pending-blob mechanism, so it must fail closed at config load.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, vl_effective_lookahead_hours=-1)


def test_vl_effective_lookahead_hours_allows_zero():
    settings = Settings(_env_file=None, vl_effective_lookahead_hours=0)
    assert settings.vl_effective_lookahead_hours == 0


def test_scoring_defaults_use_qwen36_contract():
    settings = Settings(_env_file=None)

    assert settings.scoring_model_id == "Qwen/Qwen3.6-27B-FP8"
    assert settings.scoring_model_name == "qwen36-27b-fp8"
    assert settings.scoring_model_revision == ""
    assert settings.scoring_service_git_commit == ""
    assert settings.scoring_sglang_image_tag.endswith(
        "@sha256:5d9ec71597ade6b8237d61ae6f01b976cb3d5ad2c1e3cf4e0acaf27a9ff49a65"
    )
    assert settings.scoring_gpu_type == "H100"
    assert settings.scoring_quantization == ""
    assert settings.scoring_attention_backend == ""
    assert settings.scoring_tp == 1
    assert settings.scoring_mem_fraction == "0.75"
    assert settings.scoring_chunked_prefill == 4096
    assert settings.scoring_max_reqs == 1
    assert settings.scoring_reasoning_parser == "qwen3"
    assert settings.sglang_flashinfer_workspace_size == "2147483648"
    assert settings.scoring_disable_thinking is True
    assert settings.modal_key == ""
    assert settings.modal_secret == ""
    assert settings.modal_request_timeout_seconds == 2100
    assert QWEN_NON_THINKING_EXTRA_BODY == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


@pytest.mark.parametrize("value", [0, -1])
def test_unl_max_size_below_one_is_rejected(value):
    with pytest.raises(ValidationError, match="unl_max_size"):
        Settings(_env_file=None, unl_max_size=value)


def test_unl_max_size_of_one_is_allowed():
    assert Settings(_env_file=None, unl_max_size=1).unl_max_size == 1


def test_default_excluded_validator_server_versions():
    settings = Settings(_env_file=None)

    assert settings.excluded_validator_server_versions == "3.0.0"
    assert settings.excluded_validator_server_version_set == frozenset({"3.0.0"})


def test_excluded_validator_server_versions_parse_comma_separated_values():
    settings = Settings(
        _env_file=None,
        excluded_validator_server_versions="3.0.0, 2.9.0, ,1.0.0 ",
    )

    assert settings.excluded_validator_server_version_set == frozenset({
        "3.0.0",
        "2.9.0",
        "1.0.0",
    })


def test_minimum_safe_version_is_disabled_by_default():
    settings = Settings(_env_file=None)

    assert settings.minimum_safe_version == ""
    assert settings.minimum_safe_server_version is None


def test_minimum_safe_version_is_parsed():
    settings = Settings(_env_file=None, minimum_safe_version=" 1.0.8 ")

    assert settings.minimum_safe_version == "1.0.8"
    assert settings.minimum_safe_server_version == ServerVersion(
        release=(1, 0, 8), is_final=True
    )


@pytest.mark.parametrize("value", ["1.0.x", "1", "1.0.8-rc1", "1.0.8+DEBUG", "1.0.8.1"])
def test_minimum_safe_version_must_be_a_plain_final_release(value):
    with pytest.raises(ValidationError, match="MINIMUM_SAFE_VERSION"):
        Settings(_env_file=None, minimum_safe_version=value)


def test_minimum_safe_version_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("MINIMUM_SAFE_VERSION", "1.0.8")

    assert Settings(_env_file=None).minimum_safe_version == "1.0.8"
