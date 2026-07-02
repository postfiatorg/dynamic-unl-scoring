import pytest
from pydantic import ValidationError

from scoring_service.config import QWEN_NON_THINKING_EXTRA_BODY, Settings


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
