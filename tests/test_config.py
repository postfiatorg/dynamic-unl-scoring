from scoring_service.config import QWEN_NON_THINKING_EXTRA_BODY, Settings


def test_scoring_defaults_use_qwen36_contract():
    settings = Settings(_env_file=None)

    assert settings.scoring_model_id == "Qwen/Qwen3.6-27B-FP8"
    assert settings.scoring_model_name == "qwen36-27b-fp8"
    assert settings.scoring_disable_thinking is True
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
